"""Unit tests for ResponseCache (spec §14, tech-req §11)."""

import time
from pathlib import Path

from neoblogger.app.services.cache import ResponseCache


async def test_cache_disabled_noop() -> None:
    cache = ResponseCache(enabled=False, timeout_seconds=300)
    assert not cache.active()
    assert cache.size == 0
    await cache.put("k", "<p>1</p>", 1)
    assert await cache.get("k", 1) is None
    assert cache.size == 0


async def test_memory_cache_hit_and_version_mismatch() -> None:
    cache = ResponseCache(enabled=True, timeout_seconds=300)
    assert cache.active()
    await cache.put("home:1:10", "<p>content</p>", 1, nonce="n1")
    assert cache.size == 1

    hit = await cache.get("home:1:10", 1)
    assert hit == ("<p>content</p>", "n1")

    # Version mismatch returns None
    assert await cache.get("home:1:10", 2) is None


async def test_memory_cache_sweeps_expired() -> None:
    cache = ResponseCache(enabled=True, timeout_seconds=1)
    await cache.put("k1", "<p>old</p>", 1)
    assert cache.size == 1

    # Manually backdate stored_at to simulate expiry
    cache._entries["k1"].stored_at = time.monotonic() - 10

    # Getting an expired entry drops it and returns None
    assert await cache.get("k1", 1) is None
    assert cache.size == 0


async def test_memory_cache_byte_cap_eviction() -> None:
    # 1 MB cap, but test with small max_bytes via internal override
    cache = ResponseCache(enabled=True, timeout_seconds=300)
    cache._max_bytes = 100

    payload_60 = "a" * 60
    await cache.put("k1", payload_60, 1)
    assert cache.size == 1

    payload_70 = "b" * 70
    await cache.put("k2", payload_70, 1)
    # k1 should be evicted because 60 + 70 > 100
    assert cache.size == 1
    assert await cache.get("k1", 1) is None
    assert await cache.get("k2", 1) is not None


async def test_file_cache_operations(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache_store"
    cache = ResponseCache(
        enabled=True,
        timeout_seconds=300,
        storage="file",
        directory=str(cache_dir),
    )
    assert cache.active()
    assert cache.size == 0

    await cache.put("home:1:10", "<html>hello</html>", 1, nonce="nonce-123")
    assert cache.size == 1
    assert any(cache_dir.glob("*.cache"))

    hit = await cache.get("home:1:10", 1)
    assert hit == ("<html>hello</html>", "nonce-123")

    # Version mismatch
    assert await cache.get("home:1:10", 2) is None

    # Clear drops files
    await cache.clear()
    assert cache.size == 0
    assert await cache.get("home:1:10", 1) is None


async def test_file_cache_expired_sweep(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache_store"
    cache = ResponseCache(
        enabled=True,
        timeout_seconds=1,
        storage="file",
        directory=str(cache_dir),
    )
    await cache.put("k1", "<html>test</html>", 1)
    assert cache.size == 1

    # Get cache file and set mtime to past
    cache_files = list(cache_dir.glob("*.cache"))
    assert len(cache_files) == 1
    old_time = time.time() - 100
    import os

    os.utime(cache_files[0], (old_time, old_time))

    # Getting expired file removes it
    assert await cache.get("k1", 1) is None
    assert cache.size == 0


async def test_file_cache_byte_cap_eviction(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache_store"
    cache = ResponseCache(
        enabled=True,
        timeout_seconds=300,
        storage="file",
        directory=str(cache_dir),
    )
    cache._max_bytes = 350

    await cache.put("k1", "x" * 60, 1)
    time.sleep(0.01)
    await cache.put("k2", "y" * 60, 1)
    time.sleep(0.01)
    await cache.put("k3", "z" * 60, 1)

    # Oldest files evicted to stay under 120 bytes
    assert await cache.get("k1", 1) is None
    assert await cache.get("k3", 1) is not None
