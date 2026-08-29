"""Artist name unification.

Groups the spelling variants a mixed-source library accumulates (``Snoop_Dogg``,
``SNOOP DOGG``, ``snoop dogg``) under one key, then picks the most readable
spelling as canonical. Matching ignores diacritics so ``Dam Vinh Hung`` and
``Dam Vinh Hung`` with tone marks land together; the canonical pick then
prefers the spelling that kept its tone marks.
"""

import logging
import re
import unicodedata
from collections import defaultdict

log = logging.getLogger(__name__)

FEATURE_MARKER = re.compile(
    r"\b(?:feat|ft|featuring)\.?(?=\s|$)",
    re.IGNORECASE,
)
KEY_SEPARATOR = re.compile(r"[_\.\-]+")
DISPLAY_SEPARATOR = re.compile(r"[_]+")
NON_ALNUM = re.compile(r"[^\w\s]", re.UNICODE)
MULTI_SPACE = re.compile(r"\s{2,}")
TRAILING_SYMBOL = re.compile(r"\s+[^\w\s]+$", re.UNICODE)
CREDIT_SPLIT = re.compile(
    r"\s*(?:,|&|\+|\bvs\.?\b|\bfeat\.)\s*|(?<=\s)[x×](?=\s)",
    re.IGNORECASE,
)


def normalise_key(name: str) -> str:
    """Return the match key for ``name``.

    The key folds case, separators, punctuation, diacritics, whitespace and
    the several spellings of a featuring marker, so every variant of one
    artist collapses to the same string. Whitespace goes too, which is what
    lets ``Son Tung M-TP`` and ``Son Tung MTP`` meet. It is never displayed.
    """
    text = FEATURE_MARKER.sub(" feat ", name)
    text = KEY_SEPARATOR.sub(" ", text)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    stripped = NON_ALNUM.sub(" ", stripped)
    return "".join(stripped.split()).casefold()


def normalise_words(name: str) -> str:
    """Return the match key for ``name`` with word boundaries preserved.

    Same folding as :func:`normalise_key` but keeping single spaces, so a
    caller can test whether one name contains another as whole words rather
    than as an accidental substring.
    """
    text = FEATURE_MARKER.sub(" feat ", name)
    text = KEY_SEPARATOR.sub(" ", text)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    stripped = stripped.replace("đ", "d").replace("Đ", "D")
    stripped = NON_ALNUM.sub(" ", stripped)
    return " ".join(stripped.split()).casefold()


def tidy(name: str) -> str:
    """Return ``name`` with separators and featuring markers normalised.

    Unlike :func:`normalise_key` this keeps diacritics, case and hyphens,
    because the result is what gets written back to the file and a hyphen is
    part of names such as ``Son Tung M-TP`` and ``Jay-Z``.

    A dangling symbol is dropped, so ``Metallica !`` does not outrank
    ``Metallica`` as the canonical spelling. A symbol attached to a word --
    ``Boney M.`` -- is part of the name and stays.
    """
    text = DISPLAY_SEPARATOR.sub(" ", name)
    text = FEATURE_MARKER.sub("feat.", text)
    text = MULTI_SPACE.sub(" ", text)
    return TRAILING_SYMBOL.sub("", text).strip()


def readability_score(name: str) -> tuple[int, int, int, int]:
    """Return a sort key ranking how presentable a spelling is.

    Ordered by proper casing, word separation, retained diacritics and length,
    so ``Snoop Dogg`` outranks ``SNOOP DOGG`` and ``Jay-Z`` outranks ``JAY Z``.
    Casing leads because an all-caps spelling is the one least likely to be how
    the artist writes their own name.
    """
    letters = [char for char in name if char.isalpha()]
    is_single_case = bool(letters) and (
        all(char.isupper() for char in letters)
        or all(char.islower() for char in letters)
    )
    diacritics = sum(1 for char in name if ord(char) > 127)
    return (0 if is_single_case else 1, name.count(" "), diacritics, len(name))


def build_map(names: list[str]) -> dict[str, str]:
    """Return a mapping from every observed spelling to its canonical form.

    Names that normalise to the same key share one canonical spelling, chosen
    by :func:`readability_score` with a lexicographic tiebreak so repeated runs
    over the same library produce the same result.
    """
    clusters: dict[str, set[str]] = defaultdict(set)
    for name in names:
        cleaned = tidy(name)
        if not cleaned:
            continue
        clusters[normalise_key(cleaned)].add(cleaned)

    mapping: dict[str, str] = {}
    for key, variants in clusters.items():
        canonical = max(sorted(variants), key=readability_score)
        if len(variants) > 1:
            log.info(
                "unifying %d spellings of %r to %r", len(variants), key, canonical
            )
        for variant in variants:
            mapping[variant] = canonical
    return mapping


def split_credits(name: str) -> list[str]:
    """Return the individual performers named in a combined credit string.

    ``Nguyen Hai Phong, Pmar`` and ``Phao x Masew`` each name two artists. A
    library that credits one of them alone elsewhere is evidence about both,
    which is what lets a one-off filename still be read correctly.

    The name is tidied first so that ``ft.`` and ``featuring`` split the same
    way ``feat.`` does. ``x`` only separates when it stands alone between
    spaces, so ``X Japan`` and ``Malcolm X`` stay whole.
    """
    parts = [part.strip() for part in CREDIT_SPLIT.split(tidy(name))]
    return [part for part in parts if part]


def canonical_for(name: str | None, mapping: dict[str, str]) -> str | None:
    """Return the canonical spelling of ``name`` under ``mapping``."""
    if not name:
        return None
    cleaned = tidy(name)
    return mapping.get(cleaned, cleaned or None)
