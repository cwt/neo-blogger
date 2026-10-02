"""Fixed-window rate limiting (tech-req §4, spec Appendix B D5).

Used on the password-recovery endpoint, keyed by (client IP, normalized
email). Counters live in-process; failures never propagate as fatal errors.
"""

import time
from collections.abc import Callable

__all__ = ["FixedWindowRateLimiter"]


class FixedWindowRateLimiter:
    """In-process fixed-window attempt counter."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._clock = clock
        self._buckets: dict[tuple[tuple[str, ...], int], int] = {}

    def allow(self, *key_parts: str) -> bool:
        """Record an attempt unless the window for this key is exhausted."""
        now = self._clock()
        window = int(now // self._window_seconds)
        bucket = (key_parts, window)
        count = self._buckets.get(bucket, 0)
        if count >= self._max_attempts:
            return False
        self._buckets[bucket] = count + 1
        self._sweep(now)
        return True

    def _sweep(self, now: float) -> None:
        """Drop windows strictly older than the current one."""
        current = int(now // self._window_seconds)
        stale = [bucket for bucket in self._buckets if bucket[1] < current]
        for bucket in stale:
            del self._buckets[bucket]
