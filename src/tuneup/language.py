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

from .config import (
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


def propagate_by_artist(
    detected: dict[str, str | None], artist_by_key: dict[str, str | None]
) -> dict[str, str | None]:
    """Fill in unknown languages from other tracks by the same artist.

    A Vietnamese title typed without tone marks is indistinguishable from
    English by script alone. When every confident detection for an artist
    agrees on one language, that language is applied to their unresolved
    tracks. Artists whose detections disagree are left alone.
    """
    by_artist: dict[str, set[str]] = defaultdict(set)
    for key, language in detected.items():
        artist = artist_by_key.get(key)
        if artist and language:
            by_artist[artist].add(language)

    resolved = dict(detected)
    filled = 0
    for key, language in detected.items():
        if language is not None:
            continue
        artist = artist_by_key.get(key)
        if not artist:
            continue
        candidates = by_artist.get(artist, set())
        if len(candidates) == 1:
            resolved[key] = next(iter(candidates))
            filled += 1
    if filled:
        log.info("propagated a language to %d tracks from their artist", filled)
    return resolved
