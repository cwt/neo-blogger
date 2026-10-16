"""Optional response cache for anonymous pages (spec §14, tech-req §11).

A pure mechanism: keys and versions are supplied by the caller, keeping
``meta.content_version`` the single source of truth — the caller reads it
per request (a ~0.1 ms indexed read, per S1) instead of synchronizing a
second counter. Failures are logged and never fatal. In-process memory
storage; the file-backed mode arrives with deployment.
"""

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ResponseCache"]

_logger = logging.getLogger(__name__)


def _mtime_sort_key(item: tuple[Path, os.stat_result]) -> float:
    return item[1].st_mtime


@dataclass(slots=True)
class _Entry:
    html: str
    version: int
    stored_at: float
    nonce: str = ""
    size_bytes: int = 0


class ResponseCache:
    """Version-checked TTL page cache; every failure degrades to a miss.

    Supports in-process memory and file-backed storage (spec §14).
    """

    def __init__(
        self,
        *,
        enabled: bool,
        timeout_seconds: int,
        max_size_mb: int = 100,
        storage: str = "memory",
        directory: str = "cache",
        max_entries: int | None = None,
    ) -> None:
        self._enabled = enabled
        self._timeout = timeout_seconds
        self._max_bytes = max(1, max_size_mb) * 1024 * 1024
        self._storage = storage
        self._directory = Path(directory)
        self._max_entries = max_entries
        self._entries: dict[str, _Entry] = {}
        self._total_bytes: int = 0
        if self._enabled and self._storage == "file":
            try:
                self._directory.mkdir(parents=True, exist_ok=True)
            except Exception as error:
                _logger.warning("cache directory initialization failed: %s", error)

    def active(self) -> bool:
        """Whether caching is configured on (spec §14)."""
        return self._enabled

    @property
    def size(self) -> int:
        """Current entry count; observability for tests and ops."""
        if not self._enabled:
            return 0
        if self._storage == "file":
            try:
                if not self._directory.exists():
                    return 0
                return len(list(self._directory.glob("*.cache")))
            except Exception as error:
                _logger.warning("cache size check failed: %s", error)
                return 0
        return len(self._entries)

    def _cache_file_for(self, key: str) -> Path:
        hashed = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._directory / f"{hashed}.cache"

    async def get(self, key: str, version: int) -> tuple[str, str] | None:
        """The cached (HTML, nonce) for ``key`` when fresh and version-matching."""
        if not self._enabled:
            return None
        try:
            if self._storage == "file":
                return await asyncio.to_thread(self._get_file, key, version)

            self._sweep_expired_memory()
            entry = self._entries.get(key)
            if entry is None or entry.version != version:
                return None
            if time.monotonic() - entry.stored_at > self._timeout:
                self._evict_memory_key(key)
                return None
            return entry.html, entry.nonce
        except Exception as error:
            _logger.warning("cache read failed: %s", error)
            return None

    def _get_file(self, key: str, version: int) -> tuple[str, str] | None:
        """Sync file-backed read; runs in a worker thread (bug 006)."""
        file_path = self._cache_file_for(key)
        if not file_path.exists():
            return None
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if int(data.get("version", -1)) != version:
            return None
        if time.time() - file_path.stat().st_mtime > self._timeout:
            file_path.unlink(missing_ok=True)
            return None
        return str(data.get("html", "")), str(data.get("nonce", ""))

    async def put(self, key: str, html: str, version: int, nonce: str = "") -> None:
        """Store rendered HTML under ``key``; oldest entries evicted."""
        if not self._enabled:
            return
        try:
            if self._storage == "file":
                await asyncio.to_thread(self._put_file, key, html, version, nonce)
                return

            self._sweep_expired_memory()
            size = len(html.encode("utf-8")) + len(nonce.encode("utf-8"))
            if key in self._entries:
                self._evict_memory_key(key)
            self._entries[key] = _Entry(
                html=html,
                version=version,
                stored_at=time.monotonic(),
                nonce=nonce,
                size_bytes=size,
            )
            self._total_bytes += size
            while self._entries and (
                (self._max_bytes > 0 and self._total_bytes > self._max_bytes)
                or (
                    self._max_entries is not None
                    and len(self._entries) > self._max_entries
                )
            ):
                oldest = self._oldest_memory_key()
                if not oldest:
                    break
                self._evict_memory_key(oldest)
        except Exception as error:  # — cache never fatal (§14)
            _logger.warning("cache write failed: %s", error)

    def _put_file(self, key: str, html: str, version: int, nonce: str) -> None:
        """Sync file-backed write; runs in a worker thread (bug 006)."""
        self._directory.mkdir(parents=True, exist_ok=True)
        self._sweep_expired_files()
        file_path = self._cache_file_for(key)
        data = {
            "key": key,
            "html": html,
            "version": version,
            "stored_at": time.time(),
            "nonce": nonce,
        }
        payload = json.dumps(data)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._directory,
            delete=False,
        ) as tmp:
            tmp.write(payload)
            tmp_name = Path(tmp.name)
        tmp_name.replace(file_path)
        self._enforce_file_cap()

    async def clear(self) -> None:
        """Drop all entries (startup clears the cache, spec §14)."""
        try:
            if self._storage == "file":
                await asyncio.to_thread(self._clear_files)
                return
            self._entries.clear()
            self._total_bytes = 0
        except Exception as error:
            _logger.warning("cache clear failed: %s", error)

    def _clear_files(self) -> None:
        """Sync file-backed clear; runs in a worker thread (bug 006)."""
        if self._directory.exists():
            for cache_file in self._directory.glob("*.cache"):
                cache_file.unlink(missing_ok=True)

    def _evict_memory_key(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total_bytes = max(0, self._total_bytes - entry.size_bytes)

    def _sweep_expired_memory(self) -> None:
        # Insertion order is expiry order: put() pops existing keys before
        # re-inserting and stamps monotonic() time, so scanning from the
        # front and stopping at the first fresh entry is sufficient.
        # (File-backed entries instead use wall-clock mtimes, which must
        # survive restarts — hence the deliberate two-clock split.)
        now = time.monotonic()
        expired: list[str] = []
        for key, entry in self._entries.items():
            if now - entry.stored_at > self._timeout:
                expired.append(key)
            else:
                break
        for key in expired:
            self._evict_memory_key(key)

    def _oldest_memory_key(self) -> str:
        return next(iter(self._entries), "")

    def _sweep_expired_files(self) -> None:
        now = time.time()
        if not self._directory.exists():
            return
        for cache_file in self._directory.glob("*.cache"):
            try:
                if now - cache_file.stat().st_mtime > self._timeout:
                    cache_file.unlink(missing_ok=True)
            except OSError:
                continue

    def _enforce_file_cap(self) -> None:
        if not self._directory.exists():
            return
        files: list[tuple[Path, os.stat_result]] = []
        total_size = 0
        for cache_file in self._directory.glob("*.cache"):
            try:
                stat = cache_file.stat()
                files.append((cache_file, stat))
                total_size += stat.st_size
            except OSError:
                continue
        if total_size <= self._max_bytes:
            return
        files.sort(key=_mtime_sort_key)
        for cache_file, stat in files:
            if total_size <= self._max_bytes:
                break
            try:
                cache_file.unlink(missing_ok=True)
                total_size -= stat.st_size
            except OSError:
                continue
