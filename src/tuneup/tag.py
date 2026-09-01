"""CLI: write the five browsing tags onto an already-sanitized library.

Language and decade come from text and metadata; genre, mood and the
instrumental check come from Essentia. Passing --no-audio skips every model,
which produces language, decade and duration on a machine without Essentia.
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from . import language
from .artists import normalise_key, split_credits
from .analysis import Analyzer, AudioVerdict
from .audiofile import iter_audio_files, open_audio
from .config import (
    DEFAULT_LANGUAGE,
    GENRE_ARTIST_OVERRIDES,
    GENRE_TRACK_OVERRIDES,
    LANGUAGE_TRACK_OVERRIDES,
    INSTRUMENTAL_CONFIDENCE,
    TAGS_FILENAME,
    decade_for,
    duration_bucket,
    sidecar_dir,
)
from .errors import HarvestMissing, TuneupError
from .harvest import HarvestStore
from .origins import ArtistOrigin
from .titles import BARE_FEATURE, BRACKETED
from .track import ClassificationTags, SourceTags, preferred_year

log = logging.getLogger(__name__)

PROGRESS_EVERY = 25
MIN_OVERRIDE_MATCH = 8


@dataclass(frozen=True)
class TaggedTrack:
    """One file's resolved tags, for the run report."""

    path: str
    title: str | None
    artist: str | None
    language: str
    genre: str | None
    mood: str | None
    decade: str
    duration: str | None
    looks_empty: bool = False
    """True when the file carries no readable audio stream.

    A download that captured the metadata and cover art but none of the audio
    still tags cleanly, so nothing else in the run would notice it. The file is
    tagged anyway -- it is not this tool's place to decide a file is worthless
    -- but it is named in the report and in a warning at the end of the run.
    """


def read_library(paths: list[Path]) -> dict[Path, SourceTags]:
    """Read identity metadata from every file, skipping unreadable ones."""
    sources: dict[Path, SourceTags] = {}
    for path in paths:
        try:
            sources[path] = open_audio(path).read()
        except TuneupError as exc:
            log.warning("skipping %s: %s", path, exc)
    return sources


def resolve_languages(
    sources: dict[Path, SourceTags], origin: ArtistOrigin | None = None
) -> dict[Path, str | None]:
    """Detect a language per track, then fill the gaps from weaker evidence.

    Script and diacritics first, then the other tracks by the same performers,
    and finally -- only when ``origin`` is given -- the artist's country. Each
    step is weaker than the one before, so a later one never overrides an
    earlier one.
    """
    detected = {
        str(path): language.detect_track(tags.title, tags.artist)
        for path, tags in sources.items()
    }
    artist_by_key = {str(path): tags.artist for path, tags in sources.items()}
    resolved = language.propagate_by_artist(detected, artist_by_key)
    if origin is not None:
        filled = 0
        for key, value in resolved.items():
            if value is not None:
                continue
            found = origin.language_for(artist_by_key.get(key))
            if found:
                resolved[key] = found
                filled += 1
        log.info("resolved %d languages from the artist's country", filled)
    return {path: resolved[str(path)] for path in sources}


def _genre_override(credit: str | None, title: str | None = None) -> str | None:
    """Return the configured genre for any performer named in ``credit``.

    Matching folds case, punctuation and diacritics, and each credited
    performer is checked separately, so ``Two Steps From Hell`` still hits when
    the file credits ``Thomas Bergersen & Two Steps From Hell``.

    A long override name is also matched as a substring of the credit and the
    title together, because a cast credit does not split cleanly and the work
    is often named in only one of the two fields: ``Do you hear the people
    sing`` sits in the artist slot with ``Les Miserables`` as the title.
    """
    if not credit and not title:
        return None
    credit = credit or ""
    table = {normalise_key(k): v for k, v in GENRE_ARTIST_OVERRIDES.items()}
    for name in [credit, *split_credits(credit)]:
        found = table.get(normalise_key(name))
        if found:
            return found
    haystack = normalise_key(f"{credit} {title or ''}")
    for key, value in table.items():
        if len(key) >= MIN_OVERRIDE_MATCH and key in haystack:
            return value
    return None


def _track_key(artist: str | None, title: str | None) -> str | None:
    """Return the normalised ``artist - title`` key for the override tables."""
    if not artist or not title:
        return None
    return f"{normalise_key(artist)}-{normalise_key(title)}"


def _track_override(table, artist, title):
    """Return ``table``'s value for this track, matching on the folded key.

    Every credited performer is tried separately, so an entry for ``Andrea
    Bocelli`` still catches ``Andrea Bocelli & Giorgia``. The title is tried
    both whole and with a trailing credit removed, bracketed or bare, so
    ``Bella Ciao`` catches ``Bella Ciao (Money Heist)`` and ``La Flaca``
    catches ``La Flaca ft. Juanes``.
    """
    if not artist or not title:
        return None
    folded = {}
    for entry, value in table.items():
        if " - " not in entry:
            continue
        name, song = entry.split(" - ", 1)
        key = _track_key(name, song)
        if key:
            folded[key] = value
    if not folded:
        return None

    titles = [title]
    stripped = BRACKETED.sub("", title).strip()
    if stripped and stripped != title:
        titles.append(stripped)
    cut = BARE_FEATURE.split(stripped or title)[0].strip()
    if cut and cut not in titles:
        titles.append(cut)

    for name in [artist, *split_credits(artist)]:
        for candidate in titles:
            key = _track_key(name, candidate)
            if key and key in folded:
                return folded[key]
    return None


def classify(
    tags: SourceTags,
    detected_language: str | None,
    verdict: AudioVerdict | None,
) -> ClassificationTags:
    """Combine text detection, model output and file metadata into the five tags."""
    is_instrumental = (
        verdict is not None
        and verdict.instrumental_confidence >= INSTRUMENTAL_CONFIDENCE
    )
    track_language = _track_override(LANGUAGE_TRACK_OVERRIDES, tags.artist, tags.title)
    if track_language:
        resolved_language = track_language
    elif is_instrumental:
        resolved_language = "Instrumental"
    else:
        resolved_language = detected_language or DEFAULT_LANGUAGE

    override = _track_override(GENRE_TRACK_OVERRIDES, tags.artist, tags.title) or _genre_override(
        tags.artist, tags.title
    )
    genre = override or (verdict.genre if verdict else None)

    return ClassificationTags(
        language=resolved_language,
        genre=genre,
        mood=verdict.mood if verdict else None,
        decade=decade_for(preferred_year(tags)),
        duration=duration_bucket(tags.length_seconds),
    )


def run(
    sources: dict[Path, SourceTags],
    languages: dict[Path, str | None],
    analyzer: Analyzer | None,
    apply_changes: bool,
) -> tuple[list[TaggedTrack], int]:
    """Classify and optionally write every track. Returns the rows and failures."""
    rows: list[TaggedTrack] = []
    failures = 0
    for index, (path, tags) in enumerate(sources.items(), start=1):
        verdict = None
        if analyzer is not None:
            try:
                verdict = analyzer.analyse(path)
            except TuneupError as exc:
                log.warning("no audio verdict for %s: %s", path, exc)
        resolved = classify(tags, languages.get(path), verdict)
        if apply_changes:
            try:
                open_audio(path).write_classification(resolved)
            except TuneupError as exc:
                log.error("could not tag %s: %s", path, exc)
                failures += 1
                continue
            except OSError as exc:
                log.error("filesystem error tagging %s: %s", path, exc)
                failures += 1
                continue
        rows.append(
            TaggedTrack(
                path=str(path),
                title=tags.title,
                artist=tags.artist,
                language=resolved.language,
                genre=resolved.genre,
                mood=resolved.mood,
                decade=resolved.decade,
                duration=resolved.duration,
                looks_empty=not tags.length_seconds,
            )
        )
        if index % PROGRESS_EVERY == 0:
            log.info("processed %d/%d files", index, len(sources))
    return rows, failures


def write_report(library: Path, rows: list[TaggedTrack]) -> Path:
    """Write the per-track tag report and return its path."""
    target = sidecar_dir(library)
    target.mkdir(parents=True, exist_ok=True)
    path = target / TAGS_FILENAME
    path.write_text(
        json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``tuneup-tag``."""
    parser = argparse.ArgumentParser(
        description="Write Language, Genre, Mood, Decade and Duration tags."
    )
    parser.add_argument("library", type=Path, help="root directory of the library")
    parser.add_argument(
        "--apply", action="store_true", help="write tags; otherwise report only"
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="skip Essentia, producing language, decade and duration only",
    )
    parser.add_argument(
        "--lookup-languages",
        action="store_true",
        help="ask MusicBrainz for the country of artists whose language is "
        "still unknown; paces at one request per second",
    )
    parser.add_argument(
        "--limit", type=int, help="process only the first N files, for a trial run"
    )
    parser.add_argument("--verbose", action="store_true", help="log at debug level")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.library.is_dir():
        print(f"not a directory: {args.library}", file=sys.stderr)
        return 2

    try:
        HarvestStore(args.library).load()
    except HarvestMissing:
        log.warning(
            "no sanitizer snapshot for %s: titles and artists may still be the "
            "ones the auto-tagger wrote, which will skew Language",
            args.library,
        )

    paths = iter_audio_files(args.library)
    if args.limit is not None:
        paths = paths[: args.limit]
    if not paths:
        print(f"no audio files under {args.library}", file=sys.stderr)
        return 1
    log.info("tagging %d audio files", len(paths))

    sources = read_library(paths)
    origin = ArtistOrigin() if args.lookup_languages else None
    languages = resolve_languages(sources, origin)

    analyzer = None
    if not args.no_audio:
        try:
            analyzer = Analyzer()
        except TuneupError as exc:
            print(f"audio analysis unavailable: {exc}", file=sys.stderr)
            return 3

    rows, failures = run(sources, languages, analyzer, args.apply)
    report = write_report(args.library, rows)
    hollow = [row for row in rows if row.looks_empty]
    if hollow:
        log.warning(
            "%d file(s) carry no readable audio and are probably failed "
            "downloads. They were tagged, but they will not play:",
            len(hollow),
        )
        for row in hollow:
            log.warning("  %s", row.path)

    if not args.apply:
        print(f"dry run: classified {len(rows)} files, nothing written")
        print(f"review {report} then use --apply")
        return 0
    print(f"tagged {len(rows)} files, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
