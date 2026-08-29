"""Opt-in language hints from an artist's country in MusicBrainz.

Covers the case nothing else can: a Vietnamese song with an English title by
artists whose other tracks in the library are also English-titled. No script
signal exists anywhere for it, so the only remaining evidence is who made it.

Artist search is fuzzy in the same way recording search is -- ``Lil Wuyn``
comes back as ``Lil Wayne`` with a perfect score -- so the returned name has to
match exactly before its country is believed. That rejection is the whole point
of this module; without it a Vietnamese rap cypher would be filed as American.

Many artists carry no country at all, so this fills some gaps and not others.
``LANGUAGE_ARTIST_OVERRIDES`` in config is the answer for the rest.
"""

import logging

import musicbrainzngs

from .artists import normalise_key, split_credits
from .config import (
    COUNTRY_LANGUAGE,
    MUSICBRAINZ_APP,
    MUSICBRAINZ_CONTACT,
    MUSICBRAINZ_VERSION,
)
from .musicbrainz import RateLimiter

log = logging.getLogger(__name__)

REQUEST_INTERVAL_SECONDS = 1.0
SEARCH_LIMIT = 3


class ArtistOrigin:
    """Resolves an artist's country to a language, or returns None."""

    def __init__(self, contact: str = MUSICBRAINZ_CONTACT):
        musicbrainzngs.set_useragent(
            MUSICBRAINZ_APP, MUSICBRAINZ_VERSION, contact or None
        )
        self._limiter = RateLimiter(REQUEST_INTERVAL_SECONDS)
        self._cache: dict[str, str | None] = {}

    def language_for(self, credit: str | None) -> str | None:
        """Return the language implied by the country of anyone in ``credit``.

        A credit naming four rappers matches no artist entry as a whole, so
        each performer is looked up separately. The first country that maps to
        a language wins; performers with no country teach nothing and are
        skipped rather than blocking the ones that do.

        None covers every uncertain case: no exact name match, no country on
        the entry, or a country with no single dominant music language.
        """
        if not credit:
            return None
        for performer in split_credits(credit) or [credit]:
            key = normalise_key(performer)
            if not key:
                continue
            if key not in self._cache:
                self._cache[key] = self._resolve(performer, key)
            if self._cache[key]:
                return self._cache[key]
        return None

    def _resolve(self, artist: str, key: str) -> str | None:
        self._limiter.wait()
        try:
            result = musicbrainzngs.search_artists(artist=artist, limit=SEARCH_LIMIT)
        except musicbrainzngs.MusicBrainzError as exc:
            log.warning("artist lookup failed for %r: %s", artist, exc)
            return None
        for entry in result.get("artist-list", []):
            if normalise_key(entry.get("name", "")) != key:
                continue
            country = entry.get("country") or (entry.get("area") or {}).get(
                "iso-3166-1-code-list", [None]
            )[0]
            language = COUNTRY_LANGUAGE.get(country) if country else None
            if language:
                log.debug("%r resolves to %s via %s", artist, language, country)
            return language
        return None
