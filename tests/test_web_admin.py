"""Web-level admin and profile-edit tests (§4.6, §11)."""

from typing import Any

from .conftest import body_of, csrf_token_from
from .test_web_blog import signup, write_article


async def toggle(app: Any, client: Any, member_id: str, action: str) -> Any:
    page = await client.get("/admin")
    token = csrf_token_from(await body_of(page))
    return await client.post(
        f"/admin/members/{member_id}/{action}", form={"csrftoken": token}
    )


async def test_admin_guard_refuses_non_admins(app: Any) -> None:
    await signup(app, "root")
    user_client = await signup(app, "user")
    refused = await user_client.get("/admin")
    assert refused.status_code == 302
    anonymous = app.test_client()
    assert (await anonymous.get("/admin")).status_code == 302


async def test_dashboard_statistics(app: Any) -> None:
    root_client = await signup(app, "root")
    await signup(app, "user")
    await write_article(
        app, root_client, title="Stat piece", publish=True, cover="c.webp"
    )
    rendered = await body_of(await root_client.get("/admin"))
    assert "2" in rendered  # members total
    assert "1" in rendered  # published


async def test_grant_publisher_makes_articles_public(app: Any) -> None:
    context = app.extensions["neoblogger_context"]
    root_client = await signup(app, "root")
    user_client = await signup(app, "user")
    await write_article(
        app,
        user_client,
        title="Awaiting approval",
        publish=True,
        cover="https://x.io/c.webp",
    )
    stranger = app.test_client()
    assert "Awaiting approval" not in await body_of(await stranger.get("/"))
    target = await context.members.by_display_name("user")
    assert target is not None
    await toggle(app, root_client, target["_id"], "publisher")
    assert "Awaiting approval" in await body_of(await stranger.get("/"))


async def test_revoke_publisher_hides_articles(app: Any) -> None:
    context = app.extensions["neoblogger_context"]
    root_client = await signup(app, "root")
    user_client = await signup(app, "user")
    await write_article(
        app, user_client, title="Revocable", publish=True, cover="https://x.io/c.webp"
    )
    target = await context.members.by_display_name("user")
    assert target is not None
    # user starts as non-publisher; grant then revoke
    await toggle(app, root_client, target["_id"], "publisher")
    await toggle(app, root_client, target["_id"], "publisher")
    stranger = app.test_client()
    assert "Revocable" not in await body_of(await stranger.get("/"))


async def test_disable_prevents_signin_and_hides_content(app: Any) -> None:
    context = app.extensions["neoblogger_context"]
    root_client = await signup(app, "root")
    user_client = await signup(app, "user")
    await write_article(
        app,
        user_client,
        title="Disabled piece",
        publish=True,
        cover="https://x.io/c.webp",
    )
    target = await context.members.by_display_name("user")
    assert target is not None
    await toggle(app, root_client, target["_id"], "publisher")
    await toggle(app, root_client, target["_id"], "disable")
    # The disabled session is destroyed on the spot (§4.3): next request is anonymous.
    assert "Disabled piece" not in await body_of(await user_client.get("/"))
    # Sign-in refused with the contact-administrator notice.
    page = await user_client.get("/signin")
    token = csrf_token_from(await body_of(page))
    response = await user_client.post(
        "/signin",
        form={"csrftoken": token, "email": "user@x.io", "password": "sturdy-password"},
    )
    assert response.status_code == 302
    flashed = await body_of(await user_client.get("/signin"))
    assert "disabled" in flashed.lower()


async def test_admin_cannot_disable_admin(app: Any) -> None:
    context = app.extensions["neoblogger_context"]
    root_client = await signup(app, "root")
    root = await context.members.by_display_name("root")
    assert root is not None
    response = await toggle(app, root_client, root["_id"], "disable")
    assert response.status_code == 302
    still = await context.members.by_display_name("root")
    assert still is not None
    assert still["active"] is True


async def test_promote_missing_member_flashes_error(app: Any) -> None:
    root_client = await signup(app, "root")
    response = await toggle(app, root_client, "0" * 24, "promote")
    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"
    flashed = await body_of(await root_client.get("/admin"))
    assert "No such member." in flashed


async def test_promotion_is_one_way(app: Any) -> None:
    context = app.extensions["neoblogger_context"]
    root_client = await signup(app, "root")
    await signup(app, "user")
    target = await context.members.by_display_name("user")
    assert target is not None
    await toggle(app, root_client, target["_id"], "promote")
    promoted = await context.members.by_display_name("user")
    assert promoted is not None
    assert promoted["administrator"] is True


async def test_review_page_lists_non_publisher_articles(app: Any) -> None:
    root_client = await signup(app, "root")
    user_client = await signup(app, "user")
    await write_article(
        app,
        user_client,
        title="Review candidate",
        publish=True,
        cover="https://x.io/c.webp",
    )
    rendered = await body_of(await root_client.get("/admin/unpublished"))
    assert "Review candidate" in rendered


async def test_reindex_endpoint(app: Any) -> None:
    root_client = await signup(app, "root")
    page = await root_client.get("/admin")
    token = csrf_token_from(await body_of(page))
    response = await root_client.post("/admin/reindex", form={"csrftoken": token})
    assert response.status_code == 302
    flashed = await body_of(await root_client.get("/admin"))
    assert "rebuilt" in flashed


async def test_profile_edit_rotates_credentials(app: Any) -> None:
    client = await signup(app, "root")
    page = await client.get("/profile/edit")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        "/profile/edit",
        form={
            "csrftoken": token,
            "email": "root2@example.com",
            "new_password": "even-sturdier-password",
            "question_code": "first-car",
            "answer": "DeLorean",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/profile"
    # Old credentials fail; new ones work.
    fresh = app.test_client()
    page = await fresh.get("/signin")
    token = csrf_token_from(await body_of(page))
    bad = await fresh.post(
        "/signin",
        form={
            "csrftoken": token,
            "email": "root@example.com",
            "password": "sturdy-password",
        },
    )
    assert bad.status_code == 302
    flashed = await body_of(await fresh.get("/signin"))
    assert "Sign-in failed" in flashed
    good = await fresh.post(
        "/signin",
        form={
            "csrftoken": token,
            "email": "root2@example.com",
            "password": "even-sturdier-password",
        },
    )
    assert good.status_code == 302
    assert good.headers["Location"] == "/profile"
