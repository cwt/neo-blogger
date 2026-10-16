"""Bug 001 regression: Argon2 hashing off the event loop."""

import asyncio
import threading

from neoblogger.app.security.hashing import (
    async_hash_secret,
    async_verify_secret,
    hash_secret,
    verify_secret,
)


async def test_async_hash_verify_roundtrip() -> None:
    hashed = await async_hash_secret("correct horse")
    assert hashed != "correct horse"
    assert await async_verify_secret(hashed, "correct horse") is True
    assert await async_verify_secret(hashed, "wrong") is False


async def test_async_hash_runs_off_event_loop() -> None:
    loop_thread = threading.get_ident()
    seen: list[int] = []

    def _blocking_probe(secret: str) -> str:
        seen.append(threading.get_ident())
        return hash_secret(secret)

    hashed = await asyncio.to_thread(_blocking_probe, "probe")
    assert seen and seen[0] != loop_thread
    assert verify_secret(hashed, "probe") is True


async def test_async_wrappers_match_sync() -> None:
    hashed = hash_secret("pw123")
    assert await async_verify_secret(hashed, "pw123") is True
    hashed_async = await async_hash_secret("pw123")
    assert verify_secret(hashed_async, "pw123") is True
