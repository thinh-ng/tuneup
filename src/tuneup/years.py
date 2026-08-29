"""Opt-in recovery of a missing release year from MusicBrainz.

A naive search cannot do this. MusicBrainz models a *recording* as one recorded
performance, so a song has many: the studio take, a live version, a remaster,
whatever a compilation used. Search ranks them by text similarity, which has
nothing to do with which came first, and the search response carries only a
partial release list with no first-release date. Taking the top hit therefore
dates ``Piano Man`` to 1984 and Daft Punk's ``Beyond`` to 2023.

So this asks a different question. Every candidate recording whose title and
artist check out is examined, each one's *complete* release list is browsed, the
releases are narrowed to studio albums, singles and EPs, and the earliest year
across all of them wins. The original release is in there somewhere; it is just
rarely the first result.

That costs one search plus a browse per candidate -- around ten requests a
track, paced at one per second. It is off by default and worth running once.
"""

import logging
import re
import unicodedata

import musicbrainzngs

from .config import (
    MIN_PLAUSIBLE_YEAR,
    MUSICBRAINZ_APP,
    MUSICBRAINZ_CONTACT,
    MUSICBRAINZ_MIN_SCORE,
    MUSICBRAINZ_VERSION,
    current_year,
)
from .musicbrainz import RateLimiter

log = logging.getLogger(__name__)

REQUEST_INTERVAL_SECONDS = 1.0
SEARCH_LIMIT = 8
RELEASE_LIMIT = 100
STUDIO_TYPES = frozenset({"Album", "Single", "EP"})
NOT_ORIGINAL = frozenset(
    {"Compilation", "Live", "Remix", "DJ-mix", "Interview", "Demo", "Mixtape/Street"}
)
BRACKETED = re.compile(r"[\[\(\{][^\]\)\}]*[\]\)\}]")
NON_ALNUM = re.compile(r"[^\w]", re.UNICODE)
LEADING_YEAR = re.compile(r"^(\d{4})")


def _core(text: str | None) -> str:
    """Return a comparison key: no brackets, no diacritics, no punctuation."""
    stripped = BRACKETED.sub(" ", text or "")
    decomposed = unicodedata.normalize("NFKD", stripped)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = folded.replace("đ", "d").replace("Đ", "D")
    return NON_ALNUM.sub("", folded).casefold()


class YearLookup:
    """Finds the earliest studio release year for a track, or None."""

    def __init__(self, contact: str = MUSICBRAINZ_CONTACT):
        musicbrainzngs.set_useragent(
            MUSICBRAINZ_APP, MUSICBRAINZ_VERSION, contact or None
        )
        self._limiter = RateLimiter(REQUEST_INTERVAL_SECONDS)
        self._cache: dict[tuple[str, str], int | None] = {}

    def find(self, artist: str | None, title: str | None) -> int | None:
        """Return the earliest plausible studio-release year, or None.

        None means no candidate survived verification. A wrong year files a
        song under the wrong decade invisibly, whereas a missing one shows up
        as Unknown, so declining to answer is the safer failure.
        """
        if not artist or not title:
            return None
        key = (_core(artist), _core(title))
        if not key[0] or not key[1]:
            return None
        if key not in self._cache:
            self._cache[key] = self._earliest_release(artist, title)
        return self._cache[key]

    def _earliest_release(self, artist: str, title: str) -> int | None:
        years: list[int] = []
        for recording in self._candidates(artist, title):
            years.extend(self._release_years(recording["id"]))
        plausible = [
            year for year in years if MIN_PLAUSIBLE_YEAR <= year <= current_year()
        ]
        return min(plausible) if plausible else None

    def _candidates(self, artist: str, title: str) -> list[dict]:
        """Return the search hits whose title and artist both match the file."""
        self._limiter.wait()
        try:
            result = musicbrainzngs.search_recordings(
                artist=artist, recording=title, limit=SEARCH_LIMIT
            )
        except musicbrainzngs.MusicBrainzError as exc:
            log.warning("year search failed for %r / %r: %s", artist, title, exc)
            return []
        return [
            recording
            for recording in result.get("recording-list", [])
            if self._matches(recording, artist, title)
        ]

    def _release_years(self, recording_id: str) -> list[int]:
        """Return the years of every studio release carrying this recording."""
        self._limiter.wait()
        try:
            browsed = musicbrainzngs.browse_releases(
                recording=recording_id,
                includes=["release-groups"],
                limit=RELEASE_LIMIT,
            )
        except musicbrainzngs.MusicBrainzError as exc:
            log.debug("release browse failed for %s: %s", recording_id, exc)
            return []
        years = []
        for release in browsed.get("release-list", []):
            group = release.get("release-group") or {}
            if group.get("primary-type") not in STUDIO_TYPES:
                continue
            if set(group.get("secondary-type-list") or []) & NOT_ORIGINAL:
                continue
            stamp = group.get("first-release-date") or release.get("date")
            match = LEADING_YEAR.match(stamp or "")
            if match:
                years.append(int(match.group(1)))
        return years

    @staticmethod
    def _matches(recording: dict, artist: str, title: str) -> bool:
        if int(recording.get("ext:score", 0)) < MUSICBRAINZ_MIN_SCORE:
            return False
        if _core(recording.get("title")) != _core(title):
            return False
        credited = " ".join(
            credit.get("artist", {}).get("name", "")
            for credit in recording.get("artist-credit", [])
            if isinstance(credit, dict)
        )
        wanted, found = _core(artist), _core(credited)
        return bool(wanted) and (wanted in found or found in wanted)
