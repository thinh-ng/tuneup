"""Opt-in recovery of a missing release year from MusicBrainz.

Off by default, because a text search against MusicBrainz always returns
something. Searching for a track it has never heard of still yields a
confident-looking recording, and accepting that is how a library ends up
asserting a 2021 Vietnamese single was released in 2026 -- exactly the damage
this project exists to undo.

Every candidate therefore has to survive three checks before its year is used:
a search score, the recording title matching once bracketed suffixes are set
aside, and the credited artist matching the one on the file. Measured on a
library of 836 files, that turns "a year for all of them, many wrong" into a
year for roughly a quarter of them, most of which are right.

The remaining error is a reissue date: MusicBrainz knows when a recording was
first released, but a recording entry for a later remaster carries the later
date, and nothing in the metadata distinguishes them.
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
SEARCH_LIMIT = 5
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
    """Finds a first-release year for a track, or returns None rather than guess."""

    def __init__(self, contact: str = MUSICBRAINZ_CONTACT):
        musicbrainzngs.set_useragent(
            MUSICBRAINZ_APP, MUSICBRAINZ_VERSION, contact or None
        )
        self._limiter = RateLimiter(REQUEST_INTERVAL_SECONDS)
        self._cache: dict[tuple[str, str], int | None] = {}

    def find(self, artist: str | None, title: str | None) -> int | None:
        """Return the earliest plausible release year, or None when unsure.

        None is returned for anything that fails a check. A wrong year files a
        song under the wrong decade silently, whereas an absent one is visible
        as Unknown, so refusing to answer is the safer failure.
        """
        if not artist or not title:
            return None
        key = (_core(artist), _core(title))
        if not key[0] or not key[1]:
            return None
        if key in self._cache:
            return self._cache[key]
        year = self._search(artist, title)
        self._cache[key] = year
        return year

    def _search(self, artist: str, title: str) -> int | None:
        self._limiter.wait()
        try:
            result = musicbrainzngs.search_recordings(
                artist=artist, recording=title, limit=SEARCH_LIMIT
            )
        except musicbrainzngs.MusicBrainzError as exc:
            log.warning("year lookup failed for %r / %r: %s", artist, title, exc)
            return None
        for recording in result.get("recording-list", []):
            if not self._matches(recording, artist, title):
                continue
            year = self._earliest(recording)
            if year is not None:
                return year
        return None

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

    @staticmethod
    def _earliest(recording: dict) -> int | None:
        years = []
        for release in recording.get("release-list", []):
            group = release.get("release-group") or {}
            stamp = group.get("first-release-date") or release.get("date")
            match = LEADING_YEAR.match(stamp or "")
            if match:
                years.append(int(match.group(1)))
        plausible = [
            year for year in years if MIN_PLAUSIBLE_YEAR <= year <= current_year()
        ]
        return min(plausible) if plausible else None
