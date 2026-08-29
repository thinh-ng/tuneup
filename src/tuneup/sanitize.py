"""CLI: repair titles, unify artists, and wipe every other tag.

Runs before the tagger. Defaults to a dry run; writing requires both --apply
and --backup-confirmed, because the wipe is irreversible.
"""

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from . import artists, titles
from .audiofile import iter_audio_files, open_audio
from .config import (
    ARTIST_MAP_FILENAME,
    NON_ARTIST_WORDS,
    REPORT_FILENAME,
    sidecar_dir,
)
from .covers import CoverFetcher
from .errors import TuneupError
from .harvest import HarvestStore
from .track import (
    CoreTags,
    SanitizeOutcome,
    SourceTags,
    looks_like_reissue,
    preferred_year,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlannedChange:
    """One file's repaired identity tags plus the row describing the change."""

    path: Path
    core: CoreTags
    outcome: SanitizeOutcome


def collect_sources(paths: list[Path]) -> dict[Path, SourceTags]:
    """Read the current metadata of every file, skipping ones mutagen rejects."""
    sources: dict[Path, SourceTags] = {}
    for path in paths:
        try:
            sources[path] = open_audio(path).read()
        except TuneupError as exc:
            log.warning("skipping %s: %s", path, exc)
    return sources


def build_artist_pool(sources: dict[Path, SourceTags]) -> dict[str, int]:
    """Return the normalised names the library has evidence are artists.

    Two sources of evidence: a name written in an artist tag anywhere, and a
    name appearing on one side of a dashed filename more than once. Artists
    repeat across a library and song titles do not, so a repeated half is
    almost always the artist. This is what tells ``Title - Artist`` filenames
    apart from ``Artist - Title`` ones without assuming either convention.

    Production words are removed afterwards: a library with forty
    ``Song - Remix`` filenames would otherwise decide ``Remix`` is a very
    well-attested artist.
    """
    pool: Counter[str] = Counter()
    for tags in sources.values():
        if not tags.artist:
            continue
        pool[artists.normalise_key(tags.artist)] += 1
        for part in artists.split_credits(tags.artist):
            pool[artists.normalise_key(part)] += 1
    halves: Counter[str] = Counter()
    for path in sources:
        pair = titles.split_halves(path)
        if pair:
            halves.update(artists.normalise_key(half) for half in pair)
    for key, count in halves.items():
        if count > 1:
            pool[key] += count
    pool.pop("", None)
    for word in NON_ARTIST_WORDS:
        pool.pop(word, None)
    log.info("artist pool holds %d names", len(pool))
    return dict(pool)


def collect_artist_names(
    sources: dict[Path, SourceTags], pool: dict[str, int]
) -> list[str]:
    """Return every artist spelling seen, from metadata and from filenames.

    Filename hints have to be in this list too: once an embedded artist is
    rejected as an auto-tagger mismatch, the filename becomes the only source
    for that track, and it still needs unifying with the rest.
    """
    names = [tags.artist for tags in sources.values() if tags.artist]
    for path, tags in sources.items():
        hint = titles.from_filename(path, tags.artist, pool).artist_hint
        if hint:
            names.append(hint)
    return names


def plan(
    sources: dict[Path, SourceTags],
    artist_map: dict[str, str],
    pool: dict[str, int],
) -> list[PlannedChange]:
    """Return the repaired identity tags for every readable file.

    The embedded artist is kept only when the filename corroborates it. An
    embedded artist that matches neither half of an ``Artist - Title`` stem is
    the signature of a mis-matched auto-tag, so the filename wins.
    """
    changes: list[PlannedChange] = []
    for path, tags in sources.items():
        artist = artists.canonical_for(tags.artist, artist_map)
        choice = titles.choose(path, tags.title, artist, pool)
        artist_source = "metadata" if artist else "none"
        if choice.artist_hint and not choice.artist_confirmed:
            artist = artists.canonical_for(choice.artist_hint, artist_map)
            artist_source = "filename"
        elif choice.artist_confirmed:
            artist_source = "confirmed"
        album = (
            titles.normalise_case(titles.prettify(tags.album))
            if tags.album
            else None
        )
        core = CoreTags(
            title=choice.title,
            artist=artist,
            album=album or None,
            year=preferred_year(tags),
        )
        changes.append(
            PlannedChange(
                path=path,
                core=core,
                outcome=SanitizeOutcome(
                    path=str(path),
                    title_before=tags.title,
                    title_after=core.title,
                    artist_before=tags.artist,
                    artist_after=core.artist,
                    year=core.year,
                    title_source=choice.source,
                    artist_source=artist_source,
                    year_source="file" if core.year is not None else "none",
                    looks_like_reissue=looks_like_reissue(tags),
                ),
            )
        )
    return changes


def fill_album_years(changes: list[PlannedChange]) -> int:
    """Give a yearless track the year its album siblings agree on.

    A year is a property of a release, so a track missing one can borrow from
    the rest of its album. Only an album whose known years all agree is used --
    a compilation spanning decades supplies nothing, because there is no single
    right answer to copy.
    """
    years: dict[str, set[int]] = defaultdict(set)
    for change in changes:
        if change.core.album and change.core.year is not None:
            years[change.core.album.casefold()].add(change.core.year)

    filled = 0
    for index, change in enumerate(changes):
        if change.core.year is not None or not change.core.album:
            continue
        known = years.get(change.core.album.casefold(), set())
        if len(known) != 1:
            continue
        year = next(iter(known))
        changes[index] = replace(
            change,
            core=replace(change.core, year=year),
            outcome=replace(change.outcome, year=year, year_source="album"),
        )
        filled += 1
    if filled:
        log.info("filled %d years from album siblings", filled)
    return filled


def apply_changes(
    changes: list[PlannedChange],
    store: HarvestStore,
    fetcher: CoverFetcher | None = None,
) -> int:
    """Wipe and rewrite each file, recording its prior state. Returns failures.

    When ``fetcher`` is given, a file with no embedded art gets one lookup
    against the Cover Art Archive before it is rewritten.
    """
    failures = 0
    for change in changes:
        try:
            audio = open_audio(change.path)
            artwork = audio.read_artwork()
            store.record(change.path, audio.read(), artwork is not None)
            store.checkpoint()
            if artwork is None and fetcher is not None:
                artwork = fetcher.fetch(change.core.artist, change.core.album)
            audio.rewrite(change.core, artwork)
        except TuneupError as exc:
            log.error("could not rewrite %s: %s", change.path, exc)
            failures += 1
        except OSError as exc:
            log.error("filesystem error rewriting %s: %s", change.path, exc)
            failures += 1
    return failures


def write_reports(
    library: Path, changes: list[PlannedChange], artist_map: dict[str, str]
) -> None:
    """Write the per-file report and the artist mapping used for the run."""
    target = sidecar_dir(library)
    target.mkdir(parents=True, exist_ok=True)
    rows = [asdict(change.outcome) for change in changes]
    (target / REPORT_FILENAME).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / ARTIST_MAP_FILENAME).write_text(
        json.dumps(artist_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("wrote reports to %s", target)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``tuneup-sanitize``."""
    parser = argparse.ArgumentParser(
        description="Repair titles and artists, then clear all other metadata."
    )
    parser.add_argument("library", type=Path, help="root directory of the library")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write changes; without this the run only reports what it would do",
    )
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="required with --apply; confirms the library is backed up",
    )
    parser.add_argument(
        "--fetch-missing-art",
        action="store_true",
        help="look up cover art online for files that have none",
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
    if args.apply and not args.backup_confirmed:
        print(
            "--apply also requires --backup-confirmed: the wipe is irreversible",
            file=sys.stderr,
        )
        return 2

    paths = iter_audio_files(args.library)
    if not paths:
        print(f"no audio files under {args.library}", file=sys.stderr)
        return 1
    log.info("found %d audio files", len(paths))

    sources = collect_sources(paths)
    pool = build_artist_pool(sources)
    artist_map = artists.build_map(collect_artist_names(sources, pool))
    changes = plan(sources, artist_map, pool)
    fill_album_years(changes)
    write_reports(args.library, changes, artist_map)

    if not args.apply:
        renamed = sum(
            1
            for change in changes
            if change.outcome.title_before != change.outcome.title_after
        )
        reissues = sum(1 for change in changes if change.outcome.looks_like_reissue)
        print(f"dry run: {len(changes)} files, {renamed} titles would change")
        print(f"{len(artist_map)} artist spellings mapped, {reissues} look reissued")
        print(f"review {sidecar_dir(args.library) / REPORT_FILENAME} then use --apply")
        return 0

    store = HarvestStore(args.library)
    fetcher = CoverFetcher() if args.fetch_missing_art else None
    try:
        failures = apply_changes(changes, store, fetcher)
    finally:
        store.save()
        if fetcher is not None:
            fetcher.close()
    print(f"sanitized {len(changes) - failures} files, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
