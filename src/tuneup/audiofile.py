"""Container-specific metadata adapters built on mutagen.

Presents one interface over ID3 (MP3), Vorbis comments (FLAC, Ogg, Opus) and
MP4 atoms (M4A), so no pipeline above this module branches on file format.

Every mutagen failure is converted to :class:`UnreadableAudio` here, because
``mutagen.MutagenError`` derives from ``Exception`` rather than ``OSError`` and
would otherwise escape the per-file handlers and abort a whole run.

Knows nothing about how a tag value is decided, only how to store it.
"""

import base64
import contextlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TLAN,
    TMOO,
    TPE1,
    TXXX,
    ID3NoHeaderError,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

from .config import AUDIO_EXTENSIONS
from .errors import UnreadableAudio, UnsupportedContainer
from .track import Artwork, ClassificationTags, CoreTags, SourceTags

log = logging.getLogger(__name__)

DECADE_KEY = "DECADE"
DURATION_KEY = "DURATION"
LANGUAGE_KEY = "LANGUAGE"
MOOD_KEY = "MOOD"

FRONT_COVER = 3
VORBIS_PICTURE_KEY = "metadata_block_picture"

MP4_COVER_FORMATS = {
    "image/jpeg": MP4Cover.FORMAT_JPEG,
    "image/png": MP4Cover.FORMAT_PNG,
}


@contextlib.contextmanager
def _wrap_errors(path: Path) -> Iterator[None]:
    """Re-raise any mutagen failure for ``path`` as UnreadableAudio."""
    try:
        yield
    except mutagen.MutagenError as exc:
        raise UnreadableAudio(f"{str(path)!r}: {exc}") from exc


def _leading_year(value: object) -> int | None:
    text = str(value).strip()
    if len(text) < 4 or not text[:4].isdigit():
        return None
    return int(text[:4])


def _best_picture(pictures: list) -> object | None:
    """Return the front cover if one is present, else the first picture."""
    if not pictures:
        return None
    for picture in pictures:
        if getattr(picture, "type", None) == FRONT_COVER:
            return picture
    return pictures[0]


class AudioFile(ABC):
    """Read and rewrite the metadata of one audio file."""

    def __init__(self, path: Path):
        self.path = path

    @abstractmethod
    def read(self) -> SourceTags:
        """Return the metadata currently stored in the file."""

    @abstractmethod
    def read_artwork(self) -> Artwork | None:
        """Return embedded cover art, or None when the file carries none."""

    @abstractmethod
    def rewrite(self, core: CoreTags, artwork: Artwork | None) -> None:
        """Replace every tag with ``core`` and ``artwork`` in a single write.

        Destructive and irreversible for anything not carried in ``core``. The
        replacement is one write rather than a delete followed by a write, so a
        failure part-way cannot leave the file stripped of everything.
        """

    @abstractmethod
    def write_classification(self, tags: ClassificationTags) -> None:
        """Add the five browsing tags without disturbing the identity tags."""


class Mp3File(AudioFile):
    """ID3v2.4 adapter, reading original-release dates from TDOR and TORY."""

    def read(self) -> SourceTags:
        tag = self._tag()
        return SourceTags(
            title=self._text(tag, "TIT2"),
            artist=self._text(tag, "TPE1"),
            album=self._text(tag, "TALB"),
            release_year=self._year(tag, ("TDRC", "TDRL", "TYER")),
            original_year=self._year(tag, ("TDOR", "TORY")),
            length_seconds=self._length(),
        )

    def read_artwork(self) -> Artwork | None:
        frame = _best_picture(self._tag().getall("APIC"))
        if frame is None:
            return None
        return Artwork(data=frame.data, mime=frame.mime or "image/jpeg")

    def rewrite(self, core: CoreTags, artwork: Artwork | None) -> None:
        tag = ID3()
        tag.add(TIT2(encoding=3, text=core.title))
        if core.artist:
            tag.add(TPE1(encoding=3, text=core.artist))
        if core.album:
            tag.add(TALB(encoding=3, text=core.album))
        if core.year is not None:
            tag.add(TDRC(encoding=3, text=str(core.year)))
        if artwork is not None:
            tag.add(
                APIC(
                    encoding=3,
                    mime=artwork.mime,
                    type=FRONT_COVER,
                    desc="",
                    data=artwork.data,
                )
            )
        with _wrap_errors(self.path):
            tag.save(self.path, v1=0, v2_version=4)

    def write_classification(self, tags: ClassificationTags) -> None:
        tag = self._tag()
        tag.setall("TLAN", [TLAN(encoding=3, text=tags.language)])
        if tags.genre:
            tag.setall("TCON", [TCON(encoding=3, text=tags.genre)])
        if tags.mood:
            tag.setall("TMOO", [TMOO(encoding=3, text=tags.mood)])
        self._set_txxx(tag, DECADE_KEY, tags.decade)
        if tags.duration:
            self._set_txxx(tag, DURATION_KEY, tags.duration)
        with _wrap_errors(self.path):
            tag.save(self.path, v2_version=4)

    def _tag(self) -> ID3:
        try:
            return ID3(self.path)
        except ID3NoHeaderError:
            return ID3()
        except mutagen.MutagenError as exc:
            raise UnreadableAudio(f"{str(self.path)!r}: {exc}") from exc

    def _length(self) -> float | None:
        try:
            length = MP3(self.path).info.length
        except mutagen.MutagenError:
            log.warning("could not read stream length from %s", self.path)
            return None
        if length <= 0:
            log.warning(
                "%s reports zero length and is probably a truncated download",
                self.path,
            )
            return None
        return length

    @staticmethod
    def _text(tag: ID3, frame_id: str) -> str | None:
        frame = tag.get(frame_id)
        if frame is None or not frame.text:
            return None
        return str(frame.text[0]).strip() or None

    @staticmethod
    def _year(tag: ID3, frame_ids: tuple[str, ...]) -> int | None:
        for frame_id in frame_ids:
            frame = tag.get(frame_id)
            if frame is not None and frame.text:
                year = _leading_year(frame.text[0])
                if year is not None:
                    return year
        return None

    @staticmethod
    def _set_txxx(tag: ID3, key: str, value: str) -> None:
        tag.delall(f"TXXX:{key}")
        tag.add(TXXX(encoding=3, desc=key, text=value))


class VorbisFile(AudioFile):
    """FLAC, Ogg Vorbis and Opus adapter over plain uppercase comment keys.

    FLAC keeps cover art in picture blocks; Ogg and Opus keep it base64-encoded
    in a ``metadata_block_picture`` comment. Both are read and restored, so a
    rewrite does not silently drop the artwork of a non-FLAC file.
    """

    def __init__(self, path: Path, parsed: mutagen.FileType):
        super().__init__(path)
        self._file = parsed

    def read(self) -> SourceTags:
        return SourceTags(
            title=self._first("TITLE"),
            artist=self._first("ARTIST"),
            album=self._first("ALBUM"),
            release_year=self._year("DATE") or self._year("YEAR"),
            original_year=self._year("ORIGINALDATE") or self._year("ORIGINALYEAR"),
            length_seconds=self._file.info.length,
        )

    def read_artwork(self) -> Artwork | None:
        picture = _best_picture(list(getattr(self._file, "pictures", []) or []))
        if picture is None:
            picture = _best_picture(self._encoded_pictures())
        if picture is None:
            return None
        return Artwork(data=picture.data, mime=picture.mime or "image/jpeg")

    def rewrite(self, core: CoreTags, artwork: Artwork | None) -> None:
        if isinstance(self._file, FLAC):
            self._file.clear_pictures()
        if self._file.tags is None:
            self._file.add_tags()
        self._file.tags.clear()
        self._file["TITLE"] = core.title
        if core.artist:
            self._file["ARTIST"] = core.artist
        if core.album:
            self._file["ALBUM"] = core.album
        if core.year is not None:
            self._file["DATE"] = str(core.year)
        if artwork is not None:
            self._attach(artwork)
        with _wrap_errors(self.path):
            self._file.save()

    def write_classification(self, tags: ClassificationTags) -> None:
        self._file[LANGUAGE_KEY] = tags.language
        if tags.genre:
            self._file["GENRE"] = tags.genre
        if tags.mood:
            self._file[MOOD_KEY] = tags.mood
        self._file[DECADE_KEY] = tags.decade
        if tags.duration:
            self._file[DURATION_KEY] = tags.duration
        with _wrap_errors(self.path):
            self._file.save()

    def _encoded_pictures(self) -> list:
        pictures = []
        for encoded in self._file.get(VORBIS_PICTURE_KEY, []) or []:
            try:
                pictures.append(Picture(base64.b64decode(encoded)))
            except (ValueError, TypeError, mutagen.MutagenError):
                log.warning("unreadable embedded picture in %s", self.path)
        return pictures

    def _attach(self, artwork: Artwork) -> None:
        picture = Picture()
        picture.data = artwork.data
        picture.mime = artwork.mime
        picture.type = FRONT_COVER
        if isinstance(self._file, FLAC):
            self._file.add_picture(picture)
            return
        self._file[VORBIS_PICTURE_KEY] = [
            base64.b64encode(picture.write()).decode("ascii")
        ]

    def _first(self, key: str) -> str | None:
        values = self._file.get(key)
        if not values:
            return None
        return str(values[0]).strip() or None

    def _year(self, key: str) -> int | None:
        value = self._first(key)
        return _leading_year(value) if value else None


class Mp4File(AudioFile):
    """M4A adapter. MP4 has no standard original-release atom, so it reports None."""

    FREEFORM_PREFIX = "----:com.apple.iTunes:"

    def __init__(self, path: Path, parsed: MP4):
        super().__init__(path)
        self._file = parsed

    def read(self) -> SourceTags:
        return SourceTags(
            title=self._first("\xa9nam"),
            artist=self._first("\xa9ART"),
            album=self._first("\xa9alb"),
            release_year=self._year("\xa9day"),
            original_year=None,
            length_seconds=self._file.info.length,
        )

    def read_artwork(self) -> Artwork | None:
        covers = self._file.get("covr")
        if not covers:
            return None
        cover = covers[0]
        mime = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
        return Artwork(data=bytes(cover), mime=mime)

    def rewrite(self, core: CoreTags, artwork: Artwork | None) -> None:
        if self._file.tags is None:
            self._file.add_tags()
        self._file.tags.clear()
        self._file["\xa9nam"] = [core.title]
        if core.artist:
            self._file["\xa9ART"] = [core.artist]
        if core.album:
            self._file["\xa9alb"] = [core.album]
        if core.year is not None:
            self._file["\xa9day"] = [str(core.year)]
        if artwork is not None:
            image_format = MP4_COVER_FORMATS.get(artwork.mime, MP4Cover.FORMAT_JPEG)
            self._file["covr"] = [MP4Cover(artwork.data, imageformat=image_format)]
        with _wrap_errors(self.path):
            self._file.save()

    def write_classification(self, tags: ClassificationTags) -> None:
        if tags.genre:
            self._file["\xa9gen"] = [tags.genre]
        self._set_freeform(LANGUAGE_KEY, tags.language)
        if tags.mood:
            self._set_freeform(MOOD_KEY, tags.mood)
        self._set_freeform(DECADE_KEY, tags.decade)
        if tags.duration:
            self._set_freeform(DURATION_KEY, tags.duration)
        with _wrap_errors(self.path):
            self._file.save()

    def _set_freeform(self, key: str, value: str) -> None:
        atom = f"{self.FREEFORM_PREFIX}{key}"
        self._file[atom] = [MP4FreeForm(value.encode("utf-8"))]

    def _first(self, key: str) -> str | None:
        values = self._file.get(key)
        if not values:
            return None
        return str(values[0]).strip() or None

    def _year(self, key: str) -> int | None:
        value = self._first(key)
        return _leading_year(value) if value else None


def open_audio(path: Path) -> AudioFile:
    """Return the adapter for ``path``.

    Raises UnsupportedContainer for an extension with no adapter, and
    UnreadableAudio when mutagen cannot parse the file at all.
    """
    suffix = path.suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise UnsupportedContainer(f"{str(path)!r} has no adapter for {suffix!r}")
    if suffix == ".mp3":
        return Mp3File(path)
    with _wrap_errors(path):
        parsed = mutagen.File(path)
    if parsed is None:
        raise UnreadableAudio(f"{str(path)!r} was not recognised as audio")
    if isinstance(parsed, MP4):
        return Mp4File(path, parsed)
    return VorbisFile(path, parsed)


def iter_audio_files(library: Path) -> list[Path]:
    """Return every supported audio file under ``library``, sorted by path."""
    found = [
        path
        for path in library.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ]
    return sorted(found)
