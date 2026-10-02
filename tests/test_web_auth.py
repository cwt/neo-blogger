"""Web-level auth tests: registration, sessions, CSRF (spec §4)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from neoblogger import build_app
from neoblogger.app.config import RuntimeConfig


@pytest.fixture
async def app(tmp_path: Path) -> AsyncIterator[Any]:
    config = RuntimeConfig()
    config.database.path = str(tmp_path / "web.db")
    application = build_app(config)
    yield application
    await application.extensions["neoblogger_context"].database.close()


async def test_signup_creates_session(app: Any) -> None:
    client = app.test_client()
    response = await client.post(
        "/signup",
        form={
            "display_name": "root",
            "email": "root@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
        },
    )
    assert response.status_code == 302
    set_cookie = response.headers.get("Set-Cookie", "")
    assert "neoblogger_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie


def csrf_token_from(html: str) -> str:
    import re

    match = re.search(r'name="csrftoken" value="([^"]*)"', html)
    assert match is not None
    return match.group(1)


async def test_signup_duplicate_email_flashes_error(app: Any) -> None:
    client = app.test_client()
    form = {
        "display_name": "first",
        "email": "same@example.com",
        "password": "sturdy-password",
        "question_code": "first-pet",
        "answer": "Snowball",
    }
    await client.post("/signup", form=form)
    page = await client.get("/signup")
    token = csrf_token_from((await page.get_data()).decode("utf-8"))
    second = await client.post(
        "/signup", form={**form, "display_name": "second", "csrftoken": token}
    )
    assert second.status_code == 302
    assert second.headers["Location"] == "/signup"
    after = await client.get("/signup")
    rendered = (await after.get_data()).decode("utf-8")
    assert "email already registered" in rendered


async def test_signup_invalid_question_refused(app: Any) -> None:
    client = app.test_client()
    page = await client.get("/signup")
    token = csrf_token_from((await page.get_data()).decode("utf-8"))
    response = await client.post(
        "/signup",
        form={
            "display_name": "tricky",
            "email": "tricky@example.com",
            "password": "sturdy-password",
            "question_code": "not-a-question",
            "answer": "Snowball",
            "csrftoken": token,
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/signup"


async def test_csrf_required_for_authenticated_mutations(app: Any) -> None:
    client = app.test_client()
    await client.post(
        "/signup",
        form={
            "display_name": "root",
            "email": "root@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
        },
    )
    # Authenticated but without the per-session token: refused.
    response = await client.post("/signout", form={})
    assert response.status_code == 403


async def test_signout_clears_cookie(app: Any) -> None:
    import re

    client = app.test_client()
    await client.post(
        "/signup",
        form={
            "display_name": "root",
            "email": "root@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
        },
    )
    page = await client.get("/signup")
    match = re.search(
        r'name="csrftoken" value="([^"]+)"', (await page.get_data()).decode("utf-8")
    )
    assert match is not None
    response = await client.post("/signout", form={"csrftoken": match.group(1)})
    assert response.status_code == 302
