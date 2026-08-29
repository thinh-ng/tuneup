"""Language detection from title and artist text, using script and diacritics.

No statistical model is involved. Scripts that occupy their own Unicode blocks
(Hangul, kana, Han) identify themselves, and Vietnamese is identified by the
hook-above, dot-below and horn marks that no other Latin orthography uses.

Only the languages this library actually contains are detected. Everything
else falls back to the default rather than guessing from a stray accent.

Titles written without tone marks carry no signal at all, so
:func:`propagate_by_artist` fills those in from an artist's other tracks.
"""

import logging
from collections import defaultdict

from .artists import normalise_key, split_credits
from .config import (
    LANGUAGE_ARTIST_OVERRIDES,
    SCRIPT_RANGES,
    STRONG_VIETNAMESE_CHARS,
    STRONG_VIETNAMESE_RANGES,
)

log = logging.getLogger(__name__)


def _in_ranges(char: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in ranges)


def _has_script(text: str, language: str) -> bool:
    ranges = SCRIPT_RANGES[language]
    return any(_in_ranges(char, ranges) for char in text)


def is_vietnamese(text: str) -> bool:
    """Return whether ``text`` carries a Vietnamese-exclusive diacritic.

    The Latin Extended Additional block is almost entirely Vietnamese, and the
    horn and stroked-d letters do not appear in the other languages a music
    library mixes, so a single hit is decisive.
    """
    for char in text:
        if char in STRONG_VIETNAMESE_CHARS:
            return True
        if _in_ranges(char, STRONG_VIETNAMESE_RANGES):
            return True
    return False


def detect(text: str | None) -> str | None:
    """Return the language of ``text``, or None when it carries no signal.

    Korean, Japanese and Chinese are separated by block: kana settle Japanese,
    and Han characters with no kana settle Chinese. Latin text with no
    Vietnamese tone marks yields nothing, because no accent set separates the
    remaining languages reliably enough to be worth a wrong answer.
    """
    if not text:
        return None
    if _has_script(text, "Korean"):
        return "Korean"
    if _has_script(text, "Japanese"):
        return "Japanese"
    if _has_script(text, "Chinese"):
        return "Chinese"
    if is_vietnamese(text):
        return "Vietnamese"
    return None


def detect_track(title: str | None, artist: str | None) -> str | None:
    """Return the language implied by a track's title, falling back to artist."""
    return detect(title) or detect(artist)


def _performers(credit: str | None) -> list[str]:
    """Return the normalised name of each performer named in a credit."""
    if not credit:
        return []
    return [key for key in (normalise_key(p) for p in split_credits(credit)) if key]


def propagate_by_artist(
    detected: dict[str, str | None], artist_by_key: dict[str, str | None]
) -> dict[str, str | None]:
    """Fill in unknown languages from other tracks by the same performers.

    A Vietnamese title typed without tone marks, or an English title on a
    Vietnamese song, carries no script signal at all. Evidence is gathered per
    *performer* rather than per credit string, so a track credited to
    ``16 Typh, Lil Wuyn`` inherits from anything either of them released under
    any other combination. A performer whose tracks disagree teaches nothing
    and is skipped.

    ``LANGUAGE_ARTIST_OVERRIDES`` is consulted first, for artists whose
    catalogue offers no signal anywhere in the library.
    """
    by_performer: dict[str, set[str]] = defaultdict(set)
    for key, language in detected.items():
        if not language:
            continue
        for performer in _performers(artist_by_key.get(key)):
            by_performer[performer].add(language)

    overrides = {
        normalise_key(name): value
        for name, value in LANGUAGE_ARTIST_OVERRIDES.items()
    }

    resolved = dict(detected)
    filled = 0
    for key, language in detected.items():
        if language is not None:
            continue
        performers = _performers(artist_by_key.get(key))
        if not performers:
            continue
        forced = {overrides[p] for p in performers if p in overrides}
        if len(forced) == 1:
            resolved[key] = next(iter(forced))
            filled += 1
            continue
        candidates: set[str] = set()
        for performer in performers:
            candidates |= by_performer.get(performer, set())
        if len(candidates) == 1:
            resolved[key] = next(iter(candidates))
            filled += 1
    if filled:
        log.info("propagated a language to %d tracks from their performers", filled)
    return resolved
