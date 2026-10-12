"""Web-level discovery tests: tag pages, search, response cache (§8, §9, §14)."""

from typing import Any

from .conftest import body_of, csrf_token_from
from .test_web_blog import signup, write_article


def cache_enabled_config() -> Any:
    from neoblogger.app.config import CacheConfig, RuntimeConfig

    return RuntimeConfig(
        caching=CacheConfig(
            enabled=True,
            timeout_seconds=300,
            storage="memory",
            directory="cache",
            max_size_mb=100,
        )
    )


async def test_tag_page_lists_and_suggests_related(app: Any) -> None:
    root_client = await signup(app, "root")
    await write_article(
        app,
        root_client,
        title="Tagged one",
        publish=True,
        cover="https://x.io/c.webp",
        tags="python, sqlite",
    )
    await write_article(
        app,
        root_client,
        title="Tagged two",
        publish=True,
        cover="https://x.io/c.webp",
        tags="python, web",
    )
    page = await root_client.get("/tag/python")
    rendered = await body_of(page)
    assert "Tagged one" in rendered
    assert "Tagged two" in rendered
    assert "sqlite" in rendered
    assert page.headers["Cache-Control"] == "no-cache"


async def test_tag_page_admin_sees_drafts(app: Any) -> None:
    root_client = await signup(app, "root")
    await write_article(
        app, root_client, title="Tagged draft", publish=False, tags="python"
    )
    rendered = await body_of(await root_client.get("/tag/python"))
    assert "Tagged draft" in rendered
    stranger = app.test_client()
    assert "Tagged draft" not in await body_of(await stranger.get("/tag/python"))


async def test_cache_key_normalizes_malformed_page(app: Any) -> None:
    from neoblogger import build_app

    config = cache_enabled_config()
    config.database.path = app.extensions["neoblogger_context"].config.database.path
    fresh = build_app(config)
    context = fresh.extensions["neoblogger_context"]
    await context.database.start()
    stranger = fresh.test_client()
    first = await body_of(await stranger.get("/?page=notanumber"))
    second = await body_of(await stranger.get("/?page=1"))
    assert first == second
    assert context.response_cache is not None
    assert context.response_cache.size == 1
    await context.database.close()


async def test_startup_prewarm_needs_no_request(app: Any) -> None:
    from neoblogger import build_app

    config = cache_enabled_config()
    config.database.path = app.extensions["neoblogger_context"].config.database.path
    fresh = build_app(config)
    context = fresh.extensions["neoblogger_context"]
    await context.database.start()
    await fresh.startup()
    assert context.response_cache is not None
    assert context.response_cache.size == 1
    await context.database.close()


async def test_search_pagination_link_encodes_query(app: Any) -> None:
    context = app.extensions["neoblogger_context"]
    context.config.posts.per_page = 1
    root_client = await signup(app, "root")
    for title in ("Sea craft one", "Sea craft two"):
        await write_article(
            app,
            root_client,
            title=title,
            publish=True,
            cover="https://x.io/c.webp",
            tags="python",
        )
    rendered = await body_of(await root_client.get("/search?q=Sea+craft"))
    assert "Sea craft one" in rendered
    assert "q=Sea+craft" in rendered
    assert "q=Sea craft" not in rendered


async def test_search_results_and_no_cache(app: Any) -> None:
    root_client = await signup(app, "root")
    await write_article(
        app,
        root_client,
        title="Searchable article",
        publish=True,
        cover="https://x.io/c.webp",
        tags="python",
    )
    page = await root_client.get("/search?q=Searchable")
    rendered = await body_of(page)
    assert "Searchable article" in rendered
    assert page.headers["Cache-Control"] == "no-cache"
    empty = await body_of(await root_client.get("/search?q=zzzznothing"))
    assert "Nothing found" in empty


async def test_search_falls_back_to_substring_when_fts_fails(
    app: Any, monkeypatch: Any, caplog: Any
) -> None:
    context = app.extensions["neoblogger_context"]
    root_client = await signup(app, "root")
    await write_article(
        app,
        root_client,
        title="Fallback title needle",
        publish=True,
        cover="https://x.io/c.webp",
        tags="python",
    )

    async def broken_search(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("simulated FTS index failure")

    monkeypatch.setattr(context.articles, "search", broken_search)

    with caplog.at_level("WARNING"):
        page = await root_client.get("/search?q=needle")
    rendered = await body_of(page)
    assert "Fallback title needle" in rendered
    assert "FTS search failed for 'needle'; falling back to substring" in caplog.text


async def test_search_rejections_flash_and_redirect(app: Any) -> None:
    client = await signup(app, "root")
    for hostile in ("https://evil.example", "<script>", "/etc/passwd", "SELECT {x}"):
        response = await client.get(f"/search?q={hostile}")
        assert response.status_code == 302
        assert response.headers["Location"] == "/"
        flashed = await body_of(await client.get("/"))
        assert "Please use only text" in flashed, hostile


async def test_response_cache_serves_and_invalidates(app: Any) -> None:
    from neoblogger import build_app

    config = cache_enabled_config()
    config.database.path = app.extensions["neoblogger_context"].config.database.path
    fresh = build_app(config)
    context = fresh.extensions["neoblogger_context"]
    await context.database.start()
    client = fresh.test_client()
    page_up = await client.get("/signup")
    token_up = csrf_token_from(await body_of(page_up))
    await client.post(
        "/signup",
        form={
            "display_name": "root",
            "email": "root@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token_up,
        },
    )
    page = await client.get("/write")
    token = csrf_token_from(await body_of(page))
    await client.post(
        "/write",
        form={
            "csrftoken": token,
            "title": "Cached piece",
            "subtitle": "sub",
            "body": "Body.",
            "cover_url": "https://x.io/c.webp",
            "tags": "python",
            "action": "publish",
        },
    )
    # Sign out so the next requests are anonymous and cacheable.
    rendered_home = await body_of(await client.get("/"))
    assert "Cached piece" in rendered_home
    # Anonymous visitor: first GET warms the cache, second is served from it.
    stranger = fresh.test_client()
    first = await body_of(await stranger.get("/"))
    assert "Cached piece" in first
    second = await body_of(await stranger.get("/"))
    assert second == first
    # Signed-in users are never served from the cache (no-store).
    member_response = await client.get("/")
    assert member_response.headers["Cache-Control"] == "no-store"
    assert "Cached piece" in await body_of(member_response)
    await context.database.close()
