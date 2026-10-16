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


async def signup(app: Any, display_name: str) -> Any:
    """Register (auto-signs-in) and return the test client (bugs/024)."""
    client = app.test_client()
    page = await client.get("/signup")
    token = csrf_token_from(await body_of(page))
    form = {
        "display_name": display_name,
        "email": f"{display_name}@x.io",
        "password": "sturdy-password",
        "question_code": "first-pet",
        "answer": "Snowball",
        "csrftoken": token,
    }
    response = await client.post("/signup", form=form)
    assert response.status_code == 302, await body_of(response)
    return client


def tiny_webp_bytes() -> bytes:
    """Minimal valid WebP payload for upload tests (bugs/024)."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 100, 50)).save(buffer, format="WEBP")
    return buffer.getvalue()


def make_test_config(tmp_path: Path, name: str = "test.db") -> Any:
    """Database-backed RuntimeConfig under tmp_path (bugs/024)."""
    from neoblogger.app.config import RuntimeConfig

    config = RuntimeConfig()
    config.database.path = str(tmp_path / name)
    return config
