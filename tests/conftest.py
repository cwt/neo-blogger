"""Shared web-test fixtures and helpers."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from neoblogger import build_app
from neoblogger.app.config import RuntimeConfig


@pytest.fixture
async def app(tmp_path: Path) -> AsyncIterator[Any]:
    from neoblogger.app import wiring

    wiring._signin_limiter._buckets.clear()
    wiring._recovery_limiter._buckets.clear()
    wiring._signup_limiter._buckets.clear()

    config = RuntimeConfig()
    config.database.path = str(tmp_path / "web.db")
    application = build_app(config)
    yield application
    await application.extensions["neoblogger_context"].database.close()


def csrf_token_from(html: str) -> str:
    import re

    match = re.search(r'name="csrftoken" value="([^"]*)"', html)
    assert match is not None
    return match.group(1)


async def body_of(response: Any) -> str:
    return (await response.get_data()).decode("utf-8")


async def build_app_with(tmp_path: Any) -> Any:
    """Build an app whose database lives under ``tmp_path`` (isolation)."""
    from neoblogger import build_app
    from neoblogger.app.config import RuntimeConfig

    config = RuntimeConfig()
    config.database.path = str(tmp_path / "app.db")
    application = build_app(config)
    return application
