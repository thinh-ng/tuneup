"""Release-year lookups across several public music catalogues.

No one catalogue is reliable on its own. MusicBrainz is organised around
recordings, so a text search lands on a remaster or a live version as easily as
the original. Deezer answers with whichever release its search matched, which
is often a reissue. The iTunes Search API returns the release the track is
actually sold under, which in testing was the original far more often.

So they are asked in order of measured accuracy and the first verified answer
wins. Verification is the same in every case: the artist and title that come
back must match the ones that went out, once brackets, diacritics and
punctuation are set aside. An unverified answer is discarded, because a wrong
year files a song under the wrong decade invisibly while a missing one is
plainly Unknown.

Neither iTunes nor Deezer needs an API key.
"""

import json
import logging
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .artists import split_credits
from .config import MIN_PLAUSIBLE_YEAR, current_year
from .musicbrainz import RateLimiter

log = logging.getLogger(__name__)

USER_AGENT = "tuneup/0.1 (music library tagger)"
HTTP_TIMEOUT = 15
ITUNES_INTERVAL_SECONDS = 3.0
DEEZER_INTERVAL_SECONDS = 0.5
SEARCH_LIMIT = 5

BRACKETED = re.compile(r"[\[\(\{][^\]\)\}]*[\]\)\}]")
NON_ALNUM = re.compile(r"[^\w]", re.UNICODE)
LEADING_YEAR = re.compile(r"^(\d{4})")


def core(text: str | None) -> str:
    """Return a comparison key: no brackets, no diacritics, no punctuation."""
    stripped = BRACKETED.sub(" ", text or "")
    decomposed = unicodedata.normalize("NFKD", stripped)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = folded.replace("đ", "d").replace("Đ", "D")
    return NON_ALNUM.sub("", folded).casefold()


def names_agree(wanted: str, found: str | None) -> bool:
    """Return whether two names refer to the same thing, loosely compared."""
    left, right = core(wanted), core(found)
    if not left or not right:
        return False
    return left in right or right in left


def plausible(year: str | int | None) -> int | None:
    """Return ``year`` as an int when it could be a real release year."""
    match = LEADING_YEAR.match(str(year or ""))
    if not match:
        return None
    value = int(match.group(1))
    return value if MIN_PLAUSIBLE_YEAR <= value <= current_year() else None


def query_forms(artist: str, title: str) -> list[tuple[str, str]]:
    """Return the artist/title pairs to try, simplest first.

    A catalogue search is a keyword match, so extra words shrink the result set
    rather than refining it: ``Tan Tran x Freak D Bo Em Vao Balo (Lofi Ver.)``
    returns nothing while ``Tan Tran Bo Em Vao Balo`` returns the track. The
    lead artist and the bracket-free title are tried first, then the full
    strings for anything that needs them.
    """
    lead = (split_credits(artist) or [artist])[0]
    plain = BRACKETED.sub(" ", title).strip() or title
    forms = [(lead, plain), (artist, title), (lead, title), (artist, plain)]
    seen, unique = set(), []
    for form in forms:
        if form not in seen:
            seen.add(form)
            unique.append(form)
    return unique


def _fetch(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


class ItunesCatalog:
    """The iTunes Search API. Keyless, and the most accurate source tested."""

    name = "itunes"

    def __init__(self) -> None:
        self._limiter = RateLimiter(ITUNES_INTERVAL_SECONDS)

    def year_for(self, artist: str, title: str) -> int | None:
        """Return the release year of the first hit matching artist and title."""
        for term_artist, term_title in query_forms(artist, title):
            year = self._search(term_artist, term_title, artist, title)
            if year:
                return year
        return None

    def _search(
        self, term_artist: str, term_title: str, artist: str, title: str
    ) -> int | None:
        self._limiter.wait()
        query = urllib.parse.urlencode(
            {
                "term": f"{term_artist} {term_title}",
                "entity": "song",
                "limit": SEARCH_LIMIT,
            }
        )
        try:
            payload = _fetch(f"https://itunes.apple.com/search?{query}")
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            log.debug("itunes lookup failed for %r / %r: %s", artist, title, exc)
            return None
        for hit in payload.get("results", []):
            if not names_agree(artist, hit.get("artistName")):
                continue
            if not names_agree(title, hit.get("trackName")):
                continue
            year = plausible(hit.get("releaseDate"))
            if year:
                return year
        return None


class DeezerCatalog:
    """Deezer's public search. Keyless, but often answers with a reissue."""

    name = "deezer"

    def __init__(self) -> None:
        self._limiter = RateLimiter(DEEZER_INTERVAL_SECONDS)

    def year_for(self, artist: str, title: str) -> int | None:
        """Return the release year of the album carrying the first match."""
        self._limiter.wait()
        query = urllib.parse.urlencode({"q": f'artist:"{artist}" track:"{title}"'})
        try:
            payload = _fetch(f"https://api.deezer.com/search?{query}")
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            log.debug("deezer lookup failed for %r / %r: %s", artist, title, exc)
            return None
        for hit in payload.get("data", [])[:SEARCH_LIMIT]:
            if not names_agree(artist, (hit.get("artist") or {}).get("name")):
                continue
            if not names_agree(title, hit.get("title")):
                continue
            album_id = (hit.get("album") or {}).get("id")
            if not album_id:
                continue
            self._limiter.wait()
            try:
                album = _fetch(f"https://api.deezer.com/album/{album_id}")
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
                continue
            year = plausible(album.get("release_date"))
            if year:
                return year
        return None
