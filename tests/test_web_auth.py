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
    page = await client.get("/signup")
    token = csrf_token_from((await page.get_data()).decode("utf-8"))
    response = await client.post(
        "/signup",
        form={
            "display_name": "root",
            "email": "root@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token,
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
    page0 = await client.get("/signup")
    token0 = csrf_token_from((await page0.get_data()).decode("utf-8"))
    await client.post("/signup", form={**form, "csrftoken": token0})
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


async def test_csrf_required_for_anonymous_mutations(app: Any) -> None:
    client = app.test_client()
    # Missing CSRF token: refused
    resp1 = await client.post(
        "/signup",
        form={
            "display_name": "anon",
            "email": "anon@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
        },
    )
    assert resp1.status_code == 403

    # Invalid CSRF token: refused
    resp2 = await client.post(
        "/signup",
        form={
            "display_name": "anon",
            "email": "anon@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": "invalid-token",
        },
    )
    assert resp2.status_code == 403

    # Valid X-CSRFToken header: accepted
    page = await client.get("/signup")
    token = csrf_token_from((await page.get_data()).decode("utf-8"))
    resp3 = await client.post(
        "/signup",
        form={
            "display_name": "anon",
            "email": "anon@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
        },
        headers={"X-CSRFToken": token},
    )
    assert resp3.status_code == 302


async def test_csrf_required_for_authenticated_mutations(app: Any) -> None:
    client = app.test_client()
    page = await client.get("/signup")
    token = csrf_token_from((await page.get_data()).decode("utf-8"))
    await client.post(
        "/signup",
        form={
            "display_name": "root",
            "email": "root@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token,
        },
    )
    # Authenticated but without the per-session token: refused.
    response = await client.post("/signout", form={})
    assert response.status_code == 403


async def test_signout_clears_cookie(app: Any) -> None:
    import re

    client = app.test_client()
    page = await client.get("/signup")
    token = csrf_token_from((await page.get_data()).decode("utf-8"))
    await client.post(
        "/signup",
        form={
            "display_name": "root",
            "email": "root@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token,
        },
    )
    page = await client.get("/signup")
    match = re.search(
        r'name="csrftoken" value="([^"]+)"', (await page.get_data()).decode("utf-8")
    )
    assert match is not None
    response = await client.post("/signout", form={"csrftoken": match.group(1)})
    assert response.status_code == 302


async def test_recovery_rate_limit_uses_forwarded_client(
    app: Any, monkeypatch: Any
) -> None:
    from neoblogger.app.security.proxy import ProxyTrust

    context = app.extensions["neoblogger_context"]
    monkeypatch.setattr(context, "proxy_trust", ProxyTrust(("<local>",)))
    client = app.test_client()
    first_hop = {"X-Forwarded-For": "203.0.113.7"}
    page = await client.get("/recover")
    token = csrf_token_from((await page.get_data()).decode("utf-8"))
    for _ in range(5):
        response = await client.post(
            "/recover",
            form={"email": "ghost@x.io", "csrftoken": token},
            headers=first_hop,
        )
        assert response.status_code == 302
    limited = await client.post(
        "/recover",
        form={"email": "ghost@x.io", "csrftoken": token},
        headers=first_hop,
    )
    assert limited.status_code == 302
    flashed = (await (await client.get("/recover")).get_data()).decode("utf-8")
    assert "Too many attempts" in flashed
    # A different forwarded client still has its own budget.
    fresh = await client.post(
        "/recover",
        form={"email": "ghost@x.io", "csrftoken": token},
        headers={"X-Forwarded-For": "198.51.100.9"},
    )
    assert fresh.status_code == 302
    flashed = (await (await client.get("/recover")).get_data()).decode("utf-8")
    assert "Too many attempts" not in flashed


async def test_signin_rate_limit_blocks_after_attempts(app: Any) -> None:
    client = app.test_client()
    page = await client.get("/signin")
    token = csrf_token_from((await page.get_data()).decode("utf-8"))
    for _ in range(5):
        response = await client.post(
            "/signin",
            form={
                "email": "victim@example.com",
                "password": "wrong-password",
                "csrftoken": token,
            },
        )
        assert response.status_code == 302
    limited = await client.post(
        "/signin",
        form={
            "email": "victim@example.com",
            "password": "wrong-password",
            "csrftoken": token,
        },
    )
    assert limited.status_code == 302
    flashed = (await (await client.get("/signin")).get_data()).decode("utf-8")
    assert "Too many attempts" in flashed


async def test_password_recovery_invalidates_existing_session(app: Any) -> None:
    client = app.test_client()
    page_up = await client.get("/signup")
    token_up = csrf_token_from((await page_up.get_data()).decode("utf-8"))
    await client.post(
        "/signup",
        form={
            "display_name": "alice",
            "email": "alice@example.com",
            "password": "original-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token_up,
        },
    )
    # Alice is signed in; profile succeeds
    profile_resp = await client.get("/profile")
    assert profile_resp.status_code == 200

    # Password recovery happens (e.g. account compromised/reset)
    recover_client = app.test_client()
    page_rec = await recover_client.get("/recover")
    token_rec = csrf_token_from((await page_rec.get_data()).decode("utf-8"))
    recover_page = await recover_client.post(
        "/recover",
        form={
            "email": "alice@example.com",
            "answer": "Snowball",
            "new_password": "brand-new-password",
            "csrftoken": token_rec,
        },
    )
    assert recover_page.status_code == 302
    assert recover_page.headers["Location"] == "/signin"

    # Alice's old session cookie is now rejected on next request
    stale_profile = await client.get("/profile")
    assert stale_profile.status_code == 302
    assert stale_profile.headers["Location"] == "/signin"


async def test_profile_edit_invalidates_stale_sessions(app: Any) -> None:
    client_a = app.test_client()
    page_up = await client_a.get("/signup")
    token_up = csrf_token_from((await page_up.get_data()).decode("utf-8"))
    await client_a.post(
        "/signup",
        form={
            "display_name": "bob",
            "email": "bob@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token_up,
        },
    )
    stale_cookie = ""
    for cookie in client_a.cookie_jar:
        if cookie.name == "neoblogger_session":
            stale_cookie = cookie.value
    assert stale_cookie != ""

    # Bob rotates credentials from client A
    edit_page = await client_a.get("/profile/edit")
    token = csrf_token_from((await edit_page.get_data()).decode("utf-8"))
    update_resp = await client_a.post(
        "/profile/edit",
        form={
            "csrftoken": token,
            "email": "bob_new@example.com",
            "new_password": "newer-password",
            "question_code": "first-pet",
            "answer": "Snowball",
        },
    )
    assert update_resp.status_code == 302
    assert update_resp.headers["Location"] == "/profile"

    # Client A has fresh session cookie, so profile works
    resp_a = await client_a.get("/profile")
    assert resp_a.status_code == 200

    # Client B with stale session cookie is now refused
    client_b = app.test_client()
    resp_b = await client_b.get(
        "/profile", headers={"Cookie": f"neoblogger_session={stale_cookie}"}
    )
    assert resp_b.status_code == 302
    assert resp_b.headers["Location"] == "/signin"


async def test_signin_disabled_account_shows_administrator_notice(
    app: Any,
) -> None:
    context = app.extensions["neoblogger_context"]
    # Register member
    client = app.test_client()
    page_up = await client.get("/signup")
    token_up = csrf_token_from((await page_up.get_data()).decode("utf-8"))
    await client.post(
        "/signup",
        form={
            "display_name": "disabled_user",
            "email": "disabled@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token_up,
        },
    )
    # Disable the member
    member = await context.members.by_email("disabled@example.com")
    assert member is not None
    await context.members.set_active(member["_id"], False)

    # Attempt to sign in
    signin_client = app.test_client()
    page_in = await signin_client.get("/signin")
    token_in = csrf_token_from((await page_in.get_data()).decode("utf-8"))
    resp = await signin_client.post(
        "/signin",
        form={
            "email": "disabled@example.com",
            "password": "sturdy-password",
            "csrftoken": token_in,
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/signin"
    flashed = (await (await signin_client.get("/signin")).get_data()).decode("utf-8")
    assert "This account is disabled. Please contact an administrator." in flashed


async def test_recovery_disabled_account_shows_administrator_notice(
    app: Any,
) -> None:
    context = app.extensions["neoblogger_context"]
    # Register member
    client = app.test_client()
    page_up = await client.get("/signup")
    token_up = csrf_token_from((await page_up.get_data()).decode("utf-8"))
    await client.post(
        "/signup",
        form={
            "display_name": "rec_disabled_user",
            "email": "rec_disabled@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token_up,
        },
    )
    # Disable the member
    member = await context.members.by_email("rec_disabled@example.com")
    assert member is not None
    await context.members.set_active(member["_id"], False)

    # Attempt to recover password
    recover_client = app.test_client()
    page_rec = await recover_client.get("/recover")
    token_rec = csrf_token_from((await page_rec.get_data()).decode("utf-8"))
    resp = await recover_client.post(
        "/recover",
        form={
            "email": "rec_disabled@example.com",
            "answer": "Snowball",
            "new_password": "brand-new-password",
            "csrftoken": token_rec,
        },
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/recover"
    flashed = (await (await recover_client.get("/recover")).get_data()).decode("utf-8")
    assert "This account is disabled. Please contact an administrator." in flashed
