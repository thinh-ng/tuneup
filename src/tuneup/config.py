"""Constants and pure resolution functions for both tuneup pipelines.

Holds no state and performs no I/O beyond reading environment variables.
Edit ``DISCOGS_PARENT_TO_GENRE`` and ``GENRE_ARTIST_OVERRIDES`` to reshape the
genre taxonomy; :func:`genres` derives the producible set from them, and
nothing else in the package hardcodes a genre name.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus"})

SIDECAR_DIR_NAME = ".tuneup"
HARVEST_FILENAME = "harvest.json"
HARVEST_CHECKPOINT_EVERY = 25
ARTIST_MAP_FILENAME = "artists.json"
REPORT_FILENAME = "report.json"
TAGS_FILENAME = "tags.json"

DEFAULT_LANGUAGE = "English"
LANGUAGES = (
    "Vietnamese",
    "Chinese",
    "Korean",
    "Japanese",
    "Instrumental",
    DEFAULT_LANGUAGE,
)

DEFAULT_GENRE = "Other"

DISCOGS_PARENT_TO_GENRE = {
    "Blues": "Blues",
    "Brass & Military": "Classical",
    "Children's": "Other",
    "Classical": "Classical",
    "Electronic": "Electronic",
    "Folk, World, & Country": "Folk",
    "Funk / Soul": "R&B",
    "Hip Hop": "Hip Hop",
    "Jazz": "Jazz",
    "Latin": "Latin",
    "Non-Music": "Other",
    "Pop": "Pop",
    "Reggae": "Other",
    "Rock": "Rock",
    "Stage & Screen": "Soundtrack",
}

GENRE_ARTIST_OVERRIDES: dict[str, str] = {}


def genres() -> frozenset[str]:
    """Return every genre this configuration can actually produce.

    Derived from the mappings rather than declared separately, so the two
    cannot drift: a genre listed but unreachable through
    ``DISCOGS_PARENT_TO_GENRE`` or ``GENRE_ARTIST_OVERRIDES`` would never be
    written to a file.
    """
    return frozenset(
        set(DISCOGS_PARENT_TO_GENRE.values())
        | set(GENRE_ARTIST_OVERRIDES.values())
        | {DEFAULT_GENRE}
    )

NON_ARTIST_WORDS = frozenset({
    "remix", "beat", "karaoke", "acoustic", "live", "demo", "instrumental",
    "cover", "lyrics", "lyric", "audio", "video", "official", "ost", "mix",
    "extended", "radioedit", "nhac", "vietsub", "engsub", "sub", "fullalbum",
})

MOODS = ("Happy", "Sad", "Relaxed", "Aggressive", "Party", "Neutral")
DEFAULT_MOOD = "Neutral"

DURATION_BUCKETS = ("Under 10 min", "Over 10 min")
DURATION_SPLIT_SECONDS = 600

DECADE_UNKNOWN = "Unknown"
MIN_PLAUSIBLE_YEAR = 1900
REISSUE_GAP_YEARS = 5

INSTRUMENTAL_CONFIDENCE = 0.9
MOOD_CONFIDENCE = 0.6
GENRE_CONFIDENCE = 0.35

MODEL_DIR = Path(os.environ.get("TUNEUP_MODEL_DIR", "/models"))
EMBEDDING_MODEL = "discogs-effnet-bs64-1"
EMBEDDING_OUTPUT_NODE = "PartitionedCall:1"
GENRE_MODEL = "genre_discogs400-discogs-effnet-1"
GENRE_INPUT_NODE = "serving_default_model_Placeholder"
GENRE_OUTPUT_NODE = "PartitionedCall:0"
VOICE_MODEL = "voice_instrumental-discogs-effnet-1"
HEAD_OUTPUT_NODE = "model/Softmax"
MOOD_MODELS = {
    "Happy": "mood_happy-discogs-effnet-1",
    "Sad": "mood_sad-discogs-effnet-1",
    "Relaxed": "mood_relaxed-discogs-effnet-1",
    "Aggressive": "mood_aggressive-discogs-effnet-1",
    "Party": "mood_party-discogs-effnet-1",
}

ANALYSIS_SAMPLE_RATE = 16000
ANALYSIS_RESAMPLE_QUALITY = 4

MUSICBRAINZ_APP = "tuneup"
MUSICBRAINZ_VERSION = "0.1.0"
MUSICBRAINZ_CONTACT = os.environ.get("TUNEUP_MB_CONTACT", "")
MUSICBRAINZ_TIMEOUT = 15
MUSICBRAINZ_MIN_SCORE = 90

STRONG_VIETNAMESE_RANGES = ((0x1EA0, 0x1EF9),)
STRONG_VIETNAMESE_CHARS = frozenset("ơƠưƯđĐ")

SCRIPT_RANGES = {
    "Korean": ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7A3)),
    "Japanese": ((0x3040, 0x309F), (0x30A0, 0x30FF)),
    "Chinese": ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF)),
}


def current_year() -> int:
    """Return the current UTC year, used as the upper bound for a valid year."""
    return datetime.now(timezone.utc).year


def is_plausible_year(year: int | None) -> bool:
    """Return whether ``year`` could be a real release year for a music file."""
    if year is None:
        return False
    return MIN_PLAUSIBLE_YEAR <= year <= current_year()


def decade_for(year: int | None) -> str:
    """Return the decade label for ``year``, or ``Unknown`` if implausible."""
    if not is_plausible_year(year):
        return DECADE_UNKNOWN
    return f"{year // 10 * 10}s"


def duration_bucket(seconds: float | None) -> str | None:
    """Return the duration bucket for ``seconds``, or None if unknown."""
    if seconds is None or seconds <= 0:
        return None
    if seconds < DURATION_SPLIT_SECONDS:
        return DURATION_BUCKETS[0]
    return DURATION_BUCKETS[1]


def sidecar_dir(library: Path) -> Path:
    """Return the directory holding tuneup's own state for ``library``."""
    return library / SIDECAR_DIR_NAME


def model_path(name: str, suffix: str) -> Path:
    """Return the path to an Essentia model file or its label metadata."""
    return MODEL_DIR / f"{name}{suffix}"
