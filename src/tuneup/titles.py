"""Title repair: strip download-site junk and recover the title from the filename.

The embedded title is the field the auto-tagger corrupted, so the filename is
treated as the more trustworthy source and the embedded title is the fallback.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .artists import normalise_key, normalise_words, split_credits

log = logging.getLogger(__name__)

SITE_TAG = re.compile(
    r"[\[\(\{]\s*(?:www\.)?(?:[\w-]+\.)+(?:com|net|org|info|biz|vn|me|tv|co)\b"
    r"[^\]\)\}]*"
    r"[\]\)\}]",
    re.IGNORECASE,
)
BARE_SITE = re.compile(
    r"\b(?:www\.)?(?:[\w-]+\.)+(?:com|net|org|info|biz|vn|me|tv|co)\b",
    re.IGNORECASE,
)
JUNK_BRACKET = re.compile(
    r"[\[\(\{]\s*(?:official\s*(?:music\s*)?(?:video|audio|mv|lyric\s*video)?"
    r"|lyrics?(?:\s*video)?|mv|m/v|hd|hq|full\s*hd|4k|1080p|720p"
    r"|audio|video|full|full\s*song|free\s*download|download"
    r"|\d{2,4}\s*kbps|nhac\s*chuong)\s*[\]\)\}]",
    re.IGNORECASE,
)
BITRATE = re.compile(r"[\s_-]*\d{2,4}\s*kbps\b", re.IGNORECASE)
BARE_JUNK_PHRASE = re.compile(
    r"\b(?:official|officiel)\s+(?:\w+\s+){0,2}?"
    r"(?:video|audio|mv|visualizer|visualiser|version|visual|lyrics?)\b"
    r"|\blyrics?\s*video\b|\bm/v\b|\bofficial\s*trailer\b",
    re.IGNORECASE,
)
EMPTY_BRACKET = re.compile(r"[\[\(\{][\s\-–—_.,]*[\]\)\}]")
BRACKET_PADDING = re.compile(r"([\[\(\{])\s+|\s+([\]\)\}])")
TRAILING_OFFICIAL = re.compile(r"[\s\-|]+official\s*$", re.IGNORECASE)
LEADING_TRACK_NUMBER = re.compile(r"^\s*(?:#\d{1,3}\s+|\d{1,3}\s*[.)\-_]\s*)(?=\D)")
SEPARATORS = re.compile(r"[_]+")
CJK_BRACKETS = re.compile(r"[「」『』【】〈〉《》]")
LEADING_BRACKET_TAG = re.compile(r"^\s*[\[\(\{][^\]\)\}]{1,30}[\]\)\}]\s*")
PIPE_SPLIT = re.compile(r"\s*[|｜]\s*")
FULLWIDTH_COLON = "："
MULTI_SPACE = re.compile(r"\s{2,}")
EDGE_JUNK = re.compile(r"^[\s\-–—_.·|]+|[\s\-–—_.·|]+$")
HAS_ALNUM = re.compile(r"[^\W_]", re.UNICODE)
ARTIST_JUNK = re.compile(
    r"\b(?:official|music\s*video|mv|lyrics?|audio|video|karaoke|cover|topic"
    r"|full\s*version|hd|ost)\b",
    re.IGNORECASE,
)
MAX_ARTIST_LENGTH = 40
MIN_CONTAINMENT_LENGTH = 4
ARTIST_TITLE_SPLIT = re.compile(r"\s+[-–—]\s+")
BRACKETED = re.compile(r"[\[\(\{][^\]\)\}]*[\]\)\}]")
BARE_FEATURE = re.compile(
    r"\b(?:feat|ft|featuring)\b\.?\s|\s[x\u00d7]\s",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TitleChoice:
    """A repaired title, where it came from, and the artist the stem implies.

    ``artist_confirmed`` is True when the embedded artist matched one half of
    an ``Artist - Title`` stem. When it is False the embedded artist agreed
    with nothing in the filename, which is the signature of an auto-tagger
    mismatch, so the caller should prefer ``artist_hint``.

    ``split_trusted`` is False when the stem contains a dash but neither half
    looks like an artist, which is what a video title reads like. The metadata
    is the better source for such a file, mangled as it may be elsewhere.
    """

    title: str
    source: str
    artist_hint: str | None
    artist_confirmed: bool = False
    split_trusted: bool = True


def prettify(text: str, is_filename: bool = False) -> str:
    """Return ``text`` with site tags, junk brackets and separator noise removed.

    ``is_filename`` enables the rules that only make sense for a download
    filename: a leading bracketed scene tag is dropped, but only when the stem
    also has a dash separator, so an album or song that genuinely opens with a
    parenthetical -- ``(I Can't Get No) Satisfaction`` -- keeps it.

    A leading track number is only stripped when a separator or a hash marks it
    as one and a non-digit follows, so ``500 Miles`` and ``1.21 Gigawatts``
    survive while ``16.Sky Over Tokyo`` loses its index.

    CJK quotation brackets are flattened to spaces, since a Japanese or Chinese
    video title wraps the song name in them and they carry no meaning here.

    Production labels are removed whether or not they are bracketed, but only
    as whole phrases: ``Official`` followed within two words by a medium word
    such as ``Video``. A bare ``Video`` or ``Audio`` is left alone, because
    ``Video Games`` is a song.

    Casing is left alone here. It is decided by the caller, which knows whether
    the text is a title or an artist name, and those want different rules.
    """
    cleaned = SEPARATORS.sub(" ", text).replace(FULLWIDTH_COLON, ":")
    cleaned = CJK_BRACKETS.sub(" ", cleaned)
    cleaned = _before_pipe(cleaned)
    cleaned = SITE_TAG.sub(" ", cleaned)
    cleaned = BARE_SITE.sub(" ", cleaned)
    cleaned = LEADING_TRACK_NUMBER.sub("", cleaned)
    if is_filename and ARTIST_TITLE_SPLIT.search(cleaned):
        cleaned = LEADING_BRACKET_TAG.sub("", cleaned)
        cleaned = LEADING_TRACK_NUMBER.sub("", cleaned)
    cleaned = JUNK_BRACKET.sub(" ", cleaned)
    cleaned = BITRATE.sub(" ", cleaned)
    cleaned = BARE_JUNK_PHRASE.sub(" ", cleaned)
    cleaned = JUNK_BRACKET.sub(" ", cleaned)
    cleaned = EMPTY_BRACKET.sub(" ", cleaned)
    cleaned = TRAILING_OFFICIAL.sub("", cleaned)
    cleaned = MULTI_SPACE.sub(" ", cleaned)
    return EDGE_JUNK.sub("", cleaned)


def without_junk(text: str) -> str:
    """Return ``text`` with production words removed and the wreckage tidied.

    Used to rescue a half of a filename that carries a marker such as
    ``(Acoustic Cover)``: the marker goes, the song name stays.
    """
    cleaned = ARTIST_JUNK.sub(" ", text)
    cleaned = EMPTY_BRACKET.sub(" ", cleaned)
    cleaned = MULTI_SPACE.sub(" ", cleaned)
    cleaned = BRACKET_PADDING.sub(lambda m: m.group(1) or m.group(2), cleaned)
    return EDGE_JUNK.sub("", cleaned)


def is_usable(text: str | None) -> bool:
    """Return whether a candidate title carries any alphanumeric content.

    Digits count: ``1973`` and ``5AM`` are real song titles, and rejecting
    them would send a correctly-named file to the fallback path.
    """
    if not text:
        return False
    return HAS_ALNUM.search(text.strip()) is not None


def is_plausible_artist(text: str) -> bool:
    """Return whether ``text`` could be an artist name rather than video junk.

    Rejects the long descriptive strings a video title puts before its dash,
    and anything carrying a production marker such as ``Official MV``, since
    no artist has one of those in their name.
    """
    if not text or len(text) > MAX_ARTIST_LENGTH:
        return False
    if ARTIST_JUNK.search(text):
        return False
    return HAS_ALNUM.search(text) is not None


def has_bare_credit(text: str) -> bool:
    """Return whether ``text`` carries a featuring marker outside any bracket.

    ``Thuy Chi ft. M4U`` and ``Phao x Masew`` are credit lists and therefore
    the artist side, while ``We Won't Be Alone (feat. Laura Brehm)`` keeps its
    marker inside brackets and is a title. Only the unbracketed form says
    anything about which half of a filename is which.
    """
    return BARE_FEATURE.search(BRACKETED.sub(" ", text)) is not None


def artist_evidence(name: str, pool: dict[str, int]) -> int:
    """Return how strongly ``pool`` says ``name`` is an artist.

    A combined credit counts as its strongest member, so a track credited to
    a pair still scores when only one of them is known elsewhere.
    """
    scores = [pool.get(normalise_key(name), 0)]
    scores.extend(pool.get(normalise_key(part), 0) for part in split_credits(name))
    return max(scores)


def trim_trailing_credits(title: str, pool: dict[str, int]) -> str:
    """Drop a credit list that the filename appended after the song name.

    ``CONG VIEC - 16 BrT, 16 Typh`` is one title and one credit list joined by
    a dash. The tail is removed only when the library recognises it as artists
    or it is an explicit comma-separated list, so
    ``Game of Thrones - Season 3 - Soundtrack`` keeps every part.
    """
    parts = ARTIST_TITLE_SPLIT.split(title)
    if len(parts) < 2:
        return title
    head, tail = " - ".join(parts[:-1]).strip(), parts[-1].strip()
    if not is_usable(head):
        return title
    credits = split_credits(tail)
    looks_like_credits = artist_evidence(tail, pool) > 0 or (
        "," in tail and len(credits) > 1
    )
    return head if looks_like_credits else title


def split_halves(path: Path) -> tuple[str, str] | None:
    """Return the two halves of a dashed stem, or None when it has no dash."""
    parts = ARTIST_TITLE_SPLIT.split(prettify(path.stem, is_filename=True), maxsplit=1)
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def from_filename(
    path: Path,
    known_artist: str | None = None,
    artist_pool: dict[str, int] | None = None,
) -> TitleChoice:
    """Derive a title from ``path``'s stem, casing the title for display.

    A stem such as ``16 Typh, Lil Wuyn - SUNDAY HIPHOP CYPHER`` is mixed case
    taken whole, so a whole-string rule would leave the shouted title alone;
    casing the title half on its own fixes it.

    The artist is never recased. ``BTS`` and ``ABBA`` write their names in
    capitals, and there is no way to tell those from shouting. Where a library
    holds several spellings of one artist the canonical pick still prefers the
    most readable one it has actually seen.
    """
    choice = _decide_from_filename(path, known_artist, artist_pool)
    return TitleChoice(
        title=_normalise_case(choice.title),
        source=choice.source,
        artist_hint=choice.artist_hint,
        artist_confirmed=choice.artist_confirmed,
        split_trusted=choice.split_trusted,
    )


def _decide_from_filename(
    path: Path,
    known_artist: str | None = None,
    artist_pool: dict[str, int] | None = None,
) -> TitleChoice:
    """Decide which half of ``path``'s stem is the title and which the artist.

    Western downloads name files ``Artist - Title`` while Vietnamese and other
    Asian ones commonly use ``Title - Artist``, so the order cannot be assumed.
    The decision uses, in order: the embedded artist matching a half, then
    ``artist_pool`` -- the names the rest of the library already knows to be
    artists -- then an unbracketed featuring marker, and only then the
    ``Artist - Title`` default. The featuring marker ranks below the pool
    because both ``Artist - Title feat. Guest`` and ``Title - Artist feat.
    Guest`` are common; it only decides when nothing better has.
    """
    pool = artist_pool or {}
    stem = prettify(path.stem, is_filename=True)
    halves = split_halves(path)
    if halves is None:
        return TitleChoice(title=stem, source="filename", artist_hint=None)
    left, right = halves
    if known_artist:
        right_match = _names_match(right, known_artist)
        left_match = _names_match(left, known_artist)
        if right_match and not left_match:
            return TitleChoice(
                title=left,
                source="filename",
                artist_hint=right,
                artist_confirmed=right_match == "exact",
            )
        if left_match and not right_match:
            return TitleChoice(
                title=right,
                source="filename",
                artist_hint=left,
                artist_confirmed=left_match == "exact",
            )
    left, right, dropped = _resolve_junk(left, right)
    if dropped == "left":
        return TitleChoice(title=right, source="filename", artist_hint=None)
    if dropped == "right":
        return TitleChoice(title=left, source="filename", artist_hint=None)
    left_score = artist_evidence(left, pool)
    right_score = artist_evidence(right, pool)
    if right_score > left_score:
        return TitleChoice(title=left, source="filename", artist_hint=right)
    if left_score > right_score:
        return TitleChoice(title=right, source="filename", artist_hint=left)
    left_credit = has_bare_credit(left)
    right_credit = has_bare_credit(right)
    if right_credit and not left_credit:
        return TitleChoice(title=left, source="filename", artist_hint=right)
    if left_credit and not right_credit:
        return TitleChoice(title=right, source="filename", artist_hint=left)
    if is_plausible_artist(left):
        return TitleChoice(title=right, source="filename", artist_hint=left)
    return TitleChoice(
        title=stem, source="filename", artist_hint=None, split_trusted=False
    )


def choose(
    path: Path,
    embedded: str | None,
    known_artist: str | None,
    artist_pool: dict[str, int] | None = None,
) -> TitleChoice:
    """Return the best available title for ``path``.

    Prefers the filename, falls back to the embedded title, and finally to the
    raw stem so that a file always ends up with some title.
    """
    pool = artist_pool or {}
    from_name = from_filename(path, known_artist, pool)
    from_metadata = normalise_case(prettify(embedded)) if embedded else ""
    if not from_name.split_trusted and is_usable(from_metadata):
        log.debug("stem of %s is not an artist-title pair, using metadata", path)
        return TitleChoice(title=from_metadata, source="metadata", artist_hint=None)
    if is_usable(from_name.title):
        trimmed = normalise_case(trim_trailing_credits(from_name.title, pool))
        if trimmed == from_name.title:
            return from_name
        return TitleChoice(
            title=trimmed,
            source=from_name.source,
            artist_hint=from_name.artist_hint,
            artist_confirmed=from_name.artist_confirmed,
            split_trusted=from_name.split_trusted,
        )
    if is_usable(from_metadata):
        log.debug("falling back to embedded title for %s", path)
        return TitleChoice(title=from_metadata, source="metadata", artist_hint=None)
    log.warning("no usable title for %s, keeping raw stem", path)
    return TitleChoice(title=path.stem, source="stem", artist_hint=None)


def _before_pipe(text: str) -> str:
    parts = PIPE_SPLIT.split(text)
    if len(parts) == 1:
        return text
    head = parts[0].strip()
    return head if len(head) >= 3 else text


def normalise_case(text: str) -> str:
    """Return ``text`` cased for display as a title.

    Only input that is entirely upper or entirely lower case is touched, since
    mixed case was probably typed by a human who meant it. Dotted acronyms such
    as ``R.I.C`` survive; an undotted one in an all-caps title does not, which
    is the unavoidable cost of not knowing which words are acronyms.
    """
    return _normalise_case(text)


def _normalise_case(text: str) -> str:
    if not text:
        return text
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return text
    if all(char.isupper() for char in letters) or all(
        char.islower() for char in letters
    ):
        return " ".join(_capitalise(word) for word in text.split(" ") if word)
    return text


def _capitalise(word: str) -> str:
    if "." in word and word.isupper():
        return word
    lowered = word.lower()
    for index, char in enumerate(lowered):
        if char.isalpha():
            return lowered[:index] + char.upper() + lowered[index + 1 :]
    return lowered


def _resolve_junk(left: str, right: str) -> tuple[str, str, str | None]:
    """Strip production markers from a dashed stem's halves.

    A half is only discarded when nothing survives the strip. ``Photograph
    (Acoustic Cover)`` keeps its song name and stays the title, while a half
    that is nothing but ``Lyric video`` is dropped so the other half wins.
    """
    left_junk = ARTIST_JUNK.search(left) is not None
    right_junk = ARTIST_JUNK.search(right) is not None
    if left_junk and not right_junk:
        cleaned = without_junk(left)
        return (cleaned, right, None) if is_usable(cleaned) else (left, right, "left")
    if right_junk and not left_junk:
        cleaned = without_junk(right)
        return (left, cleaned, None) if is_usable(cleaned) else (left, right, "right")
    return left, right, None


def _names_match(half: str, known_artist: str) -> str | None:
    """Return how ``known_artist`` matches ``half``: exact, loose, or not.

    ``exact`` covers an identical name or one named in the half's credit list.
    ``loose`` covers whole-word containment -- a file tagged ``GIMS`` against
    the half ``Maitre Gims``. Matching on word boundaries is what stops ``Rain``
    from matching ``Brain Damage``; it is still reported separately because the
    caller must not record a loose match as confirmed.
    """
    half_key = normalise_key(half)
    known_key = normalise_key(known_artist)
    if not half_key or not known_key:
        return None
    if half_key == known_key:
        return "exact"
    if known_key in {normalise_key(part) for part in split_credits(half)}:
        return "exact"
    half_words = f" {normalise_words(half)} "
    known_words = f" {normalise_words(known_artist)} "
    if len(known_key) >= MIN_CONTAINMENT_LENGTH and known_words.strip():
        if known_words in half_words or half_words in known_words:
            return "loose"
    return None
