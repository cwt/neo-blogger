"""Regression tests for bugs 006 and 020 (ResponseCache)."""

import time
from pathlib import Path

from neoblogger.app.services.cache import ResponseCache


async def test_memory_fifo_eviction_oldest_first() -> None:
    cache = ResponseCache(enabled=True, timeout_seconds=300, max_entries=3)
    await cache.put("k1", "<p>1</p>", 1)
    await cache.put("k2", "<p>2</p>", 1)
    await cache.put("k3", "<p>3</p>", 1)
    assert cache._oldest_memory_key() == "k1"

    await cache.put("k4", "<p>4</p>", 1)
    assert cache.size == 3
    assert await cache.get("k1", 1) is None
    assert await cache.get("k2", 1) is not None
    assert await cache.get("k4", 1) is not None
    assert cache._oldest_memory_key() == "k2"


async def test_memory_sweep_evicts_expired_prefix() -> None:
    cache = ResponseCache(enabled=True, timeout_seconds=100)
    await cache.put("k1", "<p>1</p>", 1)
    await cache.put("k2", "<p>2</p>", 1)
    await cache.put("k3", "<p>3</p>", 1)

    cache._entries["k1"].stored_at = time.monotonic() - 200

    assert await cache.get("k3", 1) is not None
    assert cache.size == 2
    assert await cache.get("k1", 1) is None
    assert await cache.get("k2", 1) is not None


async def test_memory_sweep_keeps_all_fresh() -> None:
    cache = ResponseCache(enabled=True, timeout_seconds=300)
    await cache.put("k1", "<p>1</p>", 1)
    await cache.put("k2", "<p>2</p>", 1)
    assert await cache.get("k1", 1) is not None
    assert cache.size == 2


async def test_memory_clear_empties() -> None:
    cache = ResponseCache(enabled=True, timeout_seconds=300)
    await cache.put("k1", "<p>1</p>", 1)
    await cache.put("k2", "<p>2</p>", 1)
    assert cache.size == 2
    await cache.clear()
    assert cache.size == 0
    assert await cache.get("k1", 1) is None


async def test_file_get_put_roundtrip(tmp_path: Path) -> None:
    cache = ResponseCache(
        enabled=True,
        timeout_seconds=300,
        storage="file",
        directory=str(tmp_path / "cache"),
    )
    await cache.put("home:1:10", "<html>hi</html>", 7, nonce="n7")
    hit = await cache.get("home:1:10", 7)
    assert hit == ("<html>hi</html>", "n7")
    assert await cache.get("home:1:10", 8) is None


async def test_file_clear_empties(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache = ResponseCache(
        enabled=True,
        timeout_seconds=300,
        storage="file",
        directory=str(cache_dir),
    )
    await cache.put("k1", "<html>a</html>", 1)
    await cache.put("k2", "<html>b</html>", 1)
    assert cache.size == 2
    await cache.clear()
    assert cache.size == 0
    assert list(cache_dir.glob("*.cache")) == []
    assert await cache.get("k1", 1) is None
