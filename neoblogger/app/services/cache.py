"""Optional response cache for anonymous pages (spec §14, tech-req §11).

A pure mechanism: keys and versions are supplied by the caller, keeping
``meta.content_version`` the single source of truth — the caller reads it
per request (a ~0.1 ms indexed read, per S1) instead of synchronizing a
second counter. Failures are logged and never fatal. In-process memory
storage; the file-backed mode arrives with deployment.
"""

import logging
import time
from dataclasses import dataclass

__all__ = ["ResponseCache"]

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _Entry:
    html: str
    version: int
    stored_at: float


class ResponseCache:
    """Version-checked TTL page cache; every failure degrades to a miss."""

    def __init__(
        self, *, enabled: bool, timeout_seconds: int, max_entries: int
    ) -> None:
        self._enabled = enabled
        self._timeout = timeout_seconds
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}

    def active(self) -> bool:
        """Whether caching is configured on (spec §14)."""
        return self._enabled

    @property
    def size(self) -> int:
        """Current entry count; observability for tests and ops."""
        return len(self._entries)

    async def get(self, key: str, version: int) -> str | None:
        """The cached HTML for ``key`` when fresh and version-matching."""
        if not self._enabled:
            return None
        try:
            entry = self._entries.get(key)
            if entry is None or entry.version != version:
                return None
            if time.monotonic() - entry.stored_at > self._timeout:
                return None
            return entry.html
        except Exception as error:
            _logger.warning("cache read failed: %s", error)
            return None

    async def put(self, key: str, html: str, version: int) -> None:
        """Store rendered HTML under ``key``; oldest entries evicted."""
        if not self._enabled:
            return
        try:
            self._entries[key] = _Entry(
                html=html, version=version, stored_at=time.monotonic()
            )
            while len(self._entries) > self._max_entries:
                oldest = self._oldest_key()
                if not oldest:
                    break
                del self._entries[oldest]
        except Exception as error:  # — cache never fatal (§14)
            _logger.warning("cache write failed: %s", error)

    def clear(self) -> None:
        """Drop all entries (startup clears the cache, spec §14)."""
        self._entries.clear()

    def _oldest_key(self) -> str:
        """The key of the earliest-stored entry (oldest-eviction, §14)."""
        oldest_key = ""
        oldest_time = float("inf")
        for key, entry in self._entries.items():
            if entry.stored_at < oldest_time:
                oldest_key, oldest_time = key, entry.stored_at
        return oldest_key
