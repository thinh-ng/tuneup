"""Dataclasses shared by the sanitize and tag pipelines.

Knows nothing about mutagen, Essentia or the filesystem.
"""

from dataclasses import dataclass

from .config import REISSUE_GAP_YEARS, is_plausible_year


@dataclass(frozen=True)
class Artwork:
    """Embedded cover art, carried across a metadata wipe."""

    data: bytes
    mime: str


@dataclass(frozen=True)
class SourceTags:
    """Metadata as found in a file, before any repair.

    ``release_year`` is the pressing this copy came from; ``original_year`` is
    the first release of the recording, when the container carries it.
    """

    title: str | None
    artist: str | None
    album: str | None
    release_year: int | None
    original_year: int | None
    length_seconds: float | None


@dataclass(frozen=True)
class CoreTags:
    """The identity metadata the sanitizer preserves and rewrites."""

    title: str
    artist: str | None
    album: str | None
    year: int | None


@dataclass(frozen=True)
class ClassificationTags:
    """The five browsing tags the tagger writes. Every value is single.

    ``genre`` and ``mood`` are None when audio analysis did not run, so a
    text-only pass leaves whatever genre the file already carries rather than
    overwriting it with a placeholder.
    """

    language: str
    genre: str | None
    mood: str | None
    decade: str
    duration: str | None


@dataclass(frozen=True)
class SanitizeOutcome:
    """One row of the sanitizer's report, for review after a run."""

    path: str
    title_before: str | None
    title_after: str
    artist_before: str | None
    artist_after: str | None
    year: int | None
    title_source: str
    artist_source: str
    year_source: str
    looks_like_reissue: bool


def preferred_year(tags: SourceTags) -> int | None:
    """Return the year that best represents when the recording first appeared.

    Prefers ``original_year`` whenever it is plausible, because a remaster or
    compilation carries the reissue date in ``release_year`` and filing it by
    that date would put a 1968 song in the 2010s.
    """
    if is_plausible_year(tags.original_year):
        return tags.original_year
    if is_plausible_year(tags.release_year):
        return tags.release_year
    return None


def looks_like_reissue(tags: SourceTags) -> bool:
    """Return whether the two year fields disagree by more than the threshold.

    A wide gap means the file is a reissue of an older recording, which is the
    case most likely to have been filed under the wrong decade.
    """
    if not is_plausible_year(tags.original_year):
        return False
    if not is_plausible_year(tags.release_year):
        return False
    return abs(tags.release_year - tags.original_year) > REISSUE_GAP_YEARS
