"""Shared pacing for the MusicBrainz web service.

MusicBrainz asks a client for no more than one request per second. Both the
cover-art and the year lookups go through this, so the two together still
respect one shared budget rather than one each.
"""

import time


class RateLimiter:
    """Blocks until the caller's turn, one request per interval."""

    def __init__(self, interval_seconds: float):
        self.interval = interval_seconds
        self._last = 0.0

    def wait(self) -> None:
        """Sleep for whatever remains of the interval since the last call."""
        elapsed = time.monotonic() - self._last
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last = time.monotonic()
