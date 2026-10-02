"""Web-level blog tests: visibility, drafts, comments (spec §5, §6, §13)."""

import re
from typing import Any

from .conftest import body_of, csrf_token_from

SIGNUP = {
    "email": "",
    "password": "sturdy-password",
    "question_code": "first-pet",
    "answer": "Snowball",
}


async def signup(app: Any, display_name: str) -> Any:
    """Register (auto-signs-in) and return the test client."""
    client = app.test_client()
    form = {**SIGNUP, "display_name": display_name, "email": f"{display_name}@x.io"}
    response = await client.post("/signup", form=form)
    assert response.status_code == 302, await body_of(response)
    return client


async def write_article(
    app: Any,
    client: Any,
    *,
    title: str,
    publish: bool,
    cover: str = "",
    tags: str = "python",
) -> str:
    """Create an article through the editor; returns its hex id."""
    page = await client.get("/write")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        "/write",
        form={
            "csrftoken": token,
            "title": title,
            "subtitle": f"{title} subtitle",
            "body": f"Body text of {title}.",
            "cover_url": cover,
            "tags": tags,
            "action": "publish" if publish else "draft",
        },
    )
    assert response.status_code == 302, await body_of(response)
    location = response.headers["Location"]
    assert location == ("/" if publish else "/profile"), location
    context = app.extensions["neoblogger_context"]

    def find_id() -> str:
        document = context.database.connection.articles.find_one({"title": title})
        assert document is not None
        return str(document["_id"])

    return await context.database.run(find_id)


async def comment_id_from(app: Any, client: Any, article_id: str) -> str:
    """Add a comment through the web form; returns its hex id."""
    page = await client.get(f"/{article_id}")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        f"/articles/{article_id}/comments",
        form={"csrftoken": token, "text": "A comment."},
    )
    assert response.status_code == 302, await body_of(response)
    match = re.search(
        r"/comments/([0-9a-f]{24})/delete",
        await body_of(await client.get(f"/{article_id}")),
    )
    assert match is not None
    return match.group(1)


async def test_feed_shows_only_active_publisher_articles(app: Any) -> None:
    root_client = await signup(app, "root")
    await write_article(
        app,
        root_client,
        title="Public piece",
        publish=True,
        cover="https://x.io/c.webp",
    )
    user_client = await signup(app, "user")
    await write_article(
        app,
        user_client,
        title="Unapproved piece",
        publish=True,
        cover="https://x.io/c.webp",
    )
    second = await body_of(await (await signup(app, "second")).get("/"))
    assert "Public piece" in second
    assert "Unapproved piece" not in second


async def test_non_publisher_article_page_access(app: Any) -> None:
    root_client = await signup(app, "root")
    user_client = await signup(app, "user")
    article_id = await write_article(
        app,
        user_client,
        title="Pending piece",
        publish=True,
        cover="https://x.io/c.webp",
    )
    stranger = app.test_client()
    refused = await stranger.get(f"/{article_id}")
    assert refused.status_code == 302
    assert refused.headers["Location"] == "/"
    author_page = await user_client.get(f"/{article_id}")
    assert author_page.status_code == 200
    assert "Pending piece" in await body_of(author_page)
    admin_page = await root_client.get(f"/{article_id}")
    assert admin_page.status_code == 200
    assert "not visible to regular users" in await body_of(admin_page)


async def test_drafts_surface_only_on_own_profile(app: Any) -> None:
    user_client = await signup(app, "user")
    draft_id = await write_article(
        app, user_client, title="Secret draft", publish=False
    )
    second = await body_of(await (await signup(app, "second")).get("/"))
    assert "Secret draft" not in second
    profile = await body_of(await user_client.get("/profile"))
    assert "Secret draft" in profile
    assert "Draft" in profile
    detail = await user_client.get(f"/{draft_id}")
    assert detail.status_code == 200


async def test_publish_requires_cover(app: Any) -> None:
    user_client = await signup(app, "user")
    page = await user_client.get("/write")
    token = csrf_token_from(await body_of(page))
    response = await user_client.post(
        "/write",
        form={
            "csrftoken": token,
            "title": "No cover",
            "subtitle": "sub",
            "body": "Body.",
            "cover_url": "",
            "tags": "",
            "action": "publish",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/write"
    flashed = await body_of(await user_client.get("/write"))
    assert "cover image is required" in flashed


async def test_write_requires_sign_in(app: Any) -> None:
    client = app.test_client()
    response = await client.get("/write")
    assert response.status_code == 302
    assert response.headers["Location"] == "/signin"


async def test_comment_add_and_author_delete(app: Any) -> None:
    user_client = await signup(app, "user")
    article_id = await write_article(
        app, user_client, title="Discussable", publish=True, cover="https://x.io/c.webp"
    )
    comment_id = await comment_id_from(app, user_client, article_id)
    assert len(comment_id) == 24
    page = await user_client.get(f"/{article_id}")
    token = csrf_token_from(await body_of(page))
    removed = await user_client.post(
        f"/comments/{comment_id}/delete", form={"csrftoken": token}
    )
    assert removed.status_code == 302
    after = await body_of(await user_client.get(f"/{article_id}"))
    assert "A comment." not in after


async def test_admin_can_delete_others_comment(app: Any) -> None:
    root_client = await signup(app, "root")
    user_client = await signup(app, "user")
    article_id = await write_article(
        app, user_client, title="Commentable", publish=True, cover="https://x.io/c.webp"
    )
    comment_id = await comment_id_from(app, user_client, article_id)
    admin_page = await root_client.get(f"/{article_id}")
    admin_token = csrf_token_from(await body_of(admin_page))
    removed = await root_client.post(
        f"/comments/{comment_id}/delete", form={"csrftoken": admin_token}
    )
    assert removed.status_code == 302
    after = await body_of(await user_client.get(f"/{article_id}"))
    assert "A comment." not in after


async def test_delete_article_cascades_comments(app: Any) -> None:
    context = app.extensions["neoblogger_context"]
    await signup(app, "root")
    user_client = await signup(app, "user")
    article_id = await write_article(
        app, user_client, title="Doomed", publish=True, cover="https://x.io/c.webp"
    )
    await comment_id_from(app, user_client, article_id)
    page = await user_client.get(f"/{article_id}")
    token = csrf_token_from(await body_of(page))
    version_before = await context.meta.content_version()
    removed = await user_client.post(
        f"/articles/{article_id}/delete", form={"csrftoken": token}
    )
    assert removed.status_code == 302
    assert await context.articles.by_id(article_id) is None
    assert await context.comments.count_by_author("user") == 0
    assert await context.meta.content_version() == version_before + 1
