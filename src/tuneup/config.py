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
    "Spanish",
    "French",
    "German",
    "Italian",
    "Hindi",
    "Hebrew",
    "Lao",
    "Instrumental",
    DEFAULT_LANGUAGE,
)

DEFAULT_GENRE = "Other"

DISCOGS_PARENT_TO_GENRE = {
    "Blues": "Blues",
    "Brass & Military": "Classical",
    "Children's": "Soundtrack",
    "Classical": "Classical",
    "Electronic": "Electronic",
    "Folk, World, & Country": "Folk",
    "Funk / Soul": "R&B",
    "Hip Hop": "Hip Hop",
    "Jazz": "Jazz",
    # Discogs' Latin parent is a region, not a sound: its 35 styles run from
    # mariachi to reggaeton, and collapsing them to one label said only that
    # the singer was Latin American -- which the Language tag already records.
    # The styles are traditional dance forms, so they sum to Folk, and the
    # three that plainly do not are named in DISCOGS_STYLE_TO_GENRE.
    "Latin": "Folk",
    "Non-Music": "Other",
    "Pop": "Pop",
    "Reggae": "Reggae",
    "Rock": "Rock",
    "Stage & Screen": "Soundtrack",
}

# Consulted before the parent map, for a style whose parent would send it to
# the wrong genre. Keyed on the model's full label.
DISCOGS_STYLE_TO_GENRE = {
    "Latin---Reggaeton": "Hip Hop",
    "Latin---MPB": "Pop",
    "Latin---Bossanova": "Jazz",
}

GENRE_ARTIST_OVERRIDES: dict[str, str] = {
    # Trailer and production-library music. The Discogs taxonomy the model was
    # trained on has no epic/trailer parent, so it cannot produce this genre;
    # these are assigned by artist instead. Matching is on the normalised name,
    # so spelling variants and credit lists still hit.
    "Two Steps From Hell": "Epic",
    "Colossal Trailer Music": "Epic",
    "Cezame Trailers": "Epic",
    "Groove Addicts": "Epic",
    "Sonic Librarian": "Epic",
    "Switch. Trailer Music": "Epic",
    "C21 FX": "Epic",
    "Epic Music": "Epic",
    "Ardwin Winter": "Epic",
    "Phil Rey": "Epic",
    "Neal Acree": "Epic",
    "Samuel Kim": "Epic",
    "Audiomachine": "Epic",
    "Immediate Music": "Epic",
    "Really Slow Motion": "Epic",
    "Position Music": "Epic",
    "Thomas Bergersen": "Epic",
    "Nick Phoenix": "Epic",
    "John Dreamer": "Epic",
    "Mark Petrie": "Epic",
    "Marcus Warner": "Epic",
    "Claudie Mackula": "Epic",
    "Kari Sigurdsson": "Epic",
    "Evgeny Emelyanov": "Epic",
    "Ivan Torrent": "Epic",
    "Future World Music": "Epic",
    "Brand X Music": "Epic",
    "Secession Studios": "Epic",
    "Fired Earth Music": "Epic",
    "BrunuhVille": "Epic",
    "Antti Martikainen": "Epic",
    "Adrian von Ziegler": "Epic",
    # Musical theatre and film scores the model files under a parent that does
    # not survive the collapse to this taxonomy.
    "Les Miserables": "Soundtrack",
    "Les Misérables": "Soundtrack",
    "Finding Nemo": "Soundtrack",
    "Michael Giacchino": "Soundtrack",
    "Bojack Horseman": "Soundtrack",
    "Andrea Bocelli": "Classical",
    # Vietnamese repertoires the Discogs taxonomy has no parent for at all, so
    # the model can never produce them. Each name below was checked against a
    # pre-1975 or hai ngoai discography, because several are shared with a
    # modern artist of the same name -- see the note on Hoang Trang in README.
    "Trúc Mai": "Bolero",
    "Họa Mi": "Bolero",
    "Kim Anh": "Bolero",
    "Nguyên Khang": "Nhạc Trữ Tình",
    "Phương Phương Thảo": "Nhạc Trữ Tình",
}


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

LANGUAGE_ARTIST_OVERRIDES: dict[str, str] = {}

# Per-track overrides, keyed "artist - title" on the normalised form. An
# artist-level entry cannot express a catalogue that crosses languages or
# repertoires: Andrea Bocelli records in Italian, Spanish and English, and
# Truc Mai sang a cha-cha-cha as well as bolero. These win over both the
# artist table and the model.
LANGUAGE_TRACK_OVERRIDES: dict[str, str] = {
    "Andrea Bocelli - Vivo per lei": "Italian",
    "Andrea Bocelli - Pianissimo": "Italian",
    "Andrea Bocelli - Cuando Me Enamoro": "Spanish",
    "Andrea Bocelli - Quizás, Quizás, Quizás": "Spanish",
    "Toto Cutugno - L'Italiano": "Italian",
    "La Casa De Papel - Bella Ciao": "Italian",
    "Édith Piaf - Non, Je ne regrette rien": "French",
    "Maître Gims - Bella": "French",
    "Kendji Girac - Andalouse": "French",
    "Kids United - On écrit sur les murs": "French",
    "Magic System - Magic In The Air": "French",
    "Soprano - Cosmo": "French",
    "Téléphone - Hygiaphone": "French",
    "Camille - Le Festin": "French",
    "Faun - Federkleid": "German",
    "Juanes - Es Por Ti": "Spanish",
    "Juanes - Para Tu Amor": "Spanish",
    "Julieta Venegas - Me Voy": "Spanish",
    "Banda Roja de Jose Leon - La Camisa Negra": "Spanish",
    "Los Dorados - La Cucaracha": "Spanish",
    "Los Zafiros - He Venido": "Spanish",
    "Santana - La Flaca": "Spanish",
    "Udit Narayan - Yun Hi Chala Chal": "Hindi",
    "Omer Adam - Tel Aviv": "Hebrew",
    "Phouvieng - Pheng Lao Souk San Van Pi Mai": "Lao",
    "Chayanne - Bailando Bachata": "Spanish",
    "La Sonora Dinamita - Mi CuCu": "Spanish",
    "Los Panchos - Perfidia": "Spanish",
}

# Empty for now. A per-track genre entry is for a recording that genuinely
# departs from its artist's repertoire -- not for one whose rhythm happens to
# come from elsewhere. Y Vân wrote "Sài Gòn" over a cha-cha-chá, and it is
# still a pre-1975 Vietnamese song, so it belongs with the rest of Trúc Mai's.
GENRE_TRACK_OVERRIDES: dict[str, str] = {}

COUNTRY_LANGUAGE = {
    "VN": "Vietnamese",
    "KR": "Korean",
    "JP": "Japanese",
    "CN": "Chinese",
    "TW": "Chinese",
    "HK": "Chinese",
    "ES": "Spanish",
    "MX": "Spanish",
    "AR": "Spanish",
    "CO": "Spanish",
    "CU": "Spanish",
    "FR": "French",
    "DE": "German",
    "AT": "German",
    "IT": "Italian",
    "IN": "Hindi",
    "IL": "Hebrew",
    "LA": "Lao",
}

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
GENRE_CONFIDENCE = 0.03

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
    "Hebrew": ((0x0590, 0x05FF), (0xFB1D, 0xFB4F)),
    "Lao": ((0x0E80, 0x0EFF),),
    "Hindi": ((0x0900, 0x097F),),
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
