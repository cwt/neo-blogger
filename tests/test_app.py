"""Smoke tests for the application factory."""

from neoblogger import build_app
from neoblogger.app.config import RuntimeConfig


async def test_healthz_ok() -> None:
    client = build_app(RuntimeConfig()).test_client()
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = await response.get_data()
    assert body == b'{"status":"ok"}\n'
