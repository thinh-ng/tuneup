"""Pre-wipe snapshot of the metadata the sanitizer is about to destroy.

The sanitizer keeps title, artist, album and year in the file itself, so this
snapshot is not needed to tag later. It exists as the audit record for a
destructive, irreversible run: it names what each file held before the wipe, so
a bad decision can be traced and reversed by hand.

It is not a full backup. Tags the wipe discards but does not preserve -- track
number, composer, comment, lyrics, replay gain, the cover art bytes -- are not
captured here. Back the library up before running with --apply.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import HARVEST_CHECKPOINT_EVERY, HARVEST_FILENAME, sidecar_dir
from .errors import HarvestMissing
from .track import SourceTags

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HarvestRecord:
    """Everything read from one file before the wipe."""

    title: str | None
    artist: str | None
    album: str | None
    release_year: int | None
    original_year: int | None
    length_seconds: float | None
    had_artwork: bool


class HarvestStore:
    """Owns the harvest snapshot for one library root."""

    def __init__(self, library: Path):
        self.library = library
        self.path = sidecar_dir(library) / HARVEST_FILENAME
        self._records: dict[str, HarvestRecord] = self._existing()
        self._unsaved = 0

    def record(self, path: Path, tags: SourceTags, had_artwork: bool) -> None:
        """Add ``path``'s pre-wipe state, keeping any earlier run's record."""
        key = self._key(path)
        if key in self._records:
            return
        self._records[key] = HarvestRecord(
            title=tags.title,
            artist=tags.artist,
            album=tags.album,
            release_year=tags.release_year,
            original_year=tags.original_year,
            length_seconds=tags.length_seconds,
            had_artwork=had_artwork,
        )
        self._unsaved += 1

    def checkpoint(self) -> None:
        """Flush to disk once enough records have accumulated.

        The wipe is irreversible, so the snapshot is written as the run goes
        rather than only at the end; a run killed outright still leaves a
        usable record of the files it had already rewritten.
        """
        if self._unsaved >= HARVEST_CHECKPOINT_EVERY:
            self.save()

    def save(self) -> Path:
        """Write the snapshot to disk and return its path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(value) for key, value in self._records.items()}
        if not payload:
            return self.path
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._unsaved = 0
        log.info("wrote harvest snapshot for %d files to %s", len(payload), self.path)
        return self.path

    def load(self) -> dict[str, HarvestRecord]:
        """Return the snapshot from disk.

        Raises HarvestMissing when the sanitizer has not run for this library.
        """
        if not self.path.exists():
            raise HarvestMissing(
                f"no snapshot at {str(self.path)!r}; run tuneup-sanitize first"
            )
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {key: HarvestRecord(**value) for key, value in raw.items()}

    def _existing(self) -> dict[str, "HarvestRecord"]:
        """Return any snapshot already on disk, so a re-run does not erase it.

        A second --apply pass reads post-wipe metadata. Merging rather than
        truncating keeps the original pre-wipe values for files the first run
        already recorded.
        """
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("ignoring unreadable snapshot %s: %s", self.path, exc)
            return {}
        return {key: HarvestRecord(**value) for key, value in raw.items()}

    def _key(self, path: Path) -> str:
        return path.relative_to(self.library).as_posix()
