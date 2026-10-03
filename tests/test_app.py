"""Smoke tests for the application factory."""

from typing import Any

from .conftest import build_app_with


async def test_healthz_ok(tmp_path: Any) -> None:
    application = await build_app_with(tmp_path)
    client = application.test_client()
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = await response.get_data()
    assert body == b'{"status":"ok"}\n'
