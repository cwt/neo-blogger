"""Fixed-window rate limiting (tech-req §4, spec Appendix B D5).

Used on the password-recovery endpoint, keyed by (client IP, normalized
email). Counters live in-process; failures never propagate as fatal errors.
"""

import time
from collections.abc import Callable

__all__ = ["FixedWindowRateLimiter"]

_MAX_BUCKETS = 10_000


class FixedWindowRateLimiter:
    """In-process fixed-window attempt counter."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._buckets: dict[tuple[tuple[str, ...], int], int] = {}
        self._last_swept: int | None = None

    def allow(self, *key_parts: str) -> bool:
        """Record an attempt unless the window for this key is exhausted."""
        now = self._clock()
        window = int(now // self._window_seconds)
        if window != self._last_swept:
            self._sweep(window)
            self._last_swept = window
        bucket = (key_parts, window)
        count = self._buckets.get(bucket, 0)
        if count >= self._max_attempts:
            return False
        self._buckets[bucket] = count + 1
        while len(self._buckets) > _MAX_BUCKETS:
            # Bound memory under key-cycling floods; evicted keys fail
            # open, which only costs an attacker more requests per attempt.
            self._buckets.pop(next(iter(self._buckets)))
        return True

    def _sweep(self, current: int) -> None:
        """Drop windows strictly older than the current one."""
        stale = [bucket for bucket in self._buckets if bucket[1] < current]
        for bucket in stale:
            del self._buckets[bucket]
