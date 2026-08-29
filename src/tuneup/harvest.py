"""Pre-wipe snapshot of the metadata the sanitizer is about to destroy.

The sanitizer keeps title, artist, album and year in the file itself, so this
snapshot is not needed to tag later. It exists as the audit and rollback record
for a destructive, irreversible run.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import HARVEST_FILENAME, sidecar_dir
from .errors import HarvestMissing
from .track import SourceTags

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HarvestRecord:
    """Everything read from one file before the wipe."""

    title: str | None
    artist: str | None
    album: str | None
    release_year: int | None
    original_year: int | None
    length_seconds: float | None
    had_artwork: bool


class HarvestStore:
    """Owns the harvest snapshot for one library root."""

    def __init__(self, library: Path):
        self.library = library
        self.path = sidecar_dir(library) / HARVEST_FILENAME
        self._records: dict[str, HarvestRecord] = {}

    def record(self, path: Path, tags: SourceTags, had_artwork: bool) -> None:
        """Add ``path``'s pre-wipe state to the snapshot held in memory."""
        self._records[self._key(path)] = HarvestRecord(
            title=tags.title,
            artist=tags.artist,
            album=tags.album,
            release_year=tags.release_year,
            original_year=tags.original_year,
            length_seconds=tags.length_seconds,
            had_artwork=had_artwork,
        )

    def save(self) -> Path:
        """Write the snapshot to disk and return its path."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(value) for key, value in self._records.items()}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("wrote harvest snapshot for %d files to %s", len(payload), self.path)
        return self.path

    def load(self) -> dict[str, HarvestRecord]:
        """Return the snapshot from disk.

        Raises HarvestMissing when the sanitizer has not run for this library.
        """
        if not self.path.exists():
            raise HarvestMissing(
                f"no snapshot at {str(self.path)!r}; run tuneup-sanitize first"
            )
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {key: HarvestRecord(**value) for key, value in raw.items()}

    def _key(self, path: Path) -> str:
        return path.relative_to(self.library).as_posix()
