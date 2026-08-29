"""Best-effort cover art recovery from the Cover Art Archive.

Only used for files that lost their artwork or never had any. Lookups are
keyed on artist and album, so a track with neither is skipped rather than
guessed at.

MusicBrainz asks for one request per second from a client; the fetcher paces
itself rather than relying on the caller to.
"""

import logging
import time

import musicbrainzngs
import requests

from .config import (
    MUSICBRAINZ_APP,
    MUSICBRAINZ_CONTACT,
    MUSICBRAINZ_TIMEOUT,
    MUSICBRAINZ_VERSION,
)
from .track import Artwork

log = logging.getLogger(__name__)

COVER_ART_URL = "https://coverartarchive.org/release-group/{mbid}/front"
REQUEST_INTERVAL_SECONDS = 1.0
ACCEPTED_MIME = frozenset({"image/jpeg", "image/png"})


class CoverFetcher:
    """Looks up front cover art for an album, pacing its own requests."""

    def __init__(self, contact: str = MUSICBRAINZ_CONTACT):
        musicbrainzngs.set_useragent(
            MUSICBRAINZ_APP, MUSICBRAINZ_VERSION, contact or None
        )
        self._session = requests.Session()
        self._last_request = 0.0
        self._cache: dict[tuple[str, str], Artwork | None] = {}

    def fetch(self, artist: str | None, album: str | None) -> Artwork | None:
        """Return front cover art for ``album``, or None when nothing is found.

        Every album is looked up once, hit or miss, so a 40-track album costs
        one lookup and one download rather than forty of each.
        """
        if not artist or not album:
            return None
        key = (artist.casefold(), album.casefold())
        if key in self._cache:
            return self._cache[key]
        mbid = self._release_group_id(artist, album)
        artwork = self._download(mbid) if mbid else None
        self._cache[key] = artwork
        return artwork

    def close(self) -> None:
        """Release the pooled HTTP connections."""
        self._session.close()

    def _release_group_id(self, artist: str, album: str) -> str | None:
        self._wait_turn()
        try:
            result = musicbrainzngs.search_release_groups(
                artist=artist, releasegroup=album, limit=1
            )
        except musicbrainzngs.MusicBrainzError as exc:
            log.warning("MusicBrainz lookup failed for %r / %r: %s", artist, album, exc)
            return None
        groups = result.get("release-group-list") or []
        if not groups:
            return None
        return groups[0].get("id")

    def _download(self, mbid: str) -> Artwork | None:
        self._wait_turn()
        url = COVER_ART_URL.format(mbid=mbid)
        try:
            response = self._session.get(url, timeout=MUSICBRAINZ_TIMEOUT)
        except requests.RequestException as exc:
            log.warning("cover art request failed for %s: %s", mbid, exc)
            return None
        if response.status_code == 404:
            return None
        if not response.ok:
            log.warning("cover art returned %s for %s", response.status_code, mbid)
            return None
        mime = response.headers.get("Content-Type", "").split(";")[0].strip()
        if mime not in ACCEPTED_MIME:
            log.warning("ignoring cover art of type %r for %s", mime, mbid)
            return None
        return Artwork(data=response.content, mime=mime)

    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request = time.monotonic()
