"""SEO surface tests: sitemap, robots, canonical, metadata (spec §16)."""

from typing import Any

from neoblogger.app.blueprints.seo import canonical_url_for

from .conftest import body_of
from .test_web_blog import signup, write_article


def test_canonical_url_for_normalizes_base() -> None:
    assert (
        canonical_url_for("https://x.com/", "http://localhost/", "/piece")
        == "https://x.com/piece"
    )
    assert (
        canonical_url_for("https://x.com", "http://localhost/", "/piece")
        == "https://x.com/piece"
    )
    assert (
        canonical_url_for("", "http://localhost/", "/piece") == "http://localhost/piece"
    )


async def test_sitemap_lists_public_articles_only(app: Any) -> None:
    root_client = await signup(app, "root")
    await write_article(
        app,
        root_client,
        title="Listed piece",
        publish=True,
        cover="https://x.io/c.webp",
    )
    user_client = await signup(app, "user")
    await write_article(
        app,
        user_client,
        title="Unlisted piece",
        publish=True,
        cover="https://x.io/c.webp",
    )
    await write_article(app, root_client, title="Draft piece", publish=False)
    stranger = app.test_client()
    response = await stranger.get("/sitemap.xml")
    assert response.status_code == 200
    document = await body_of(response)
    assert "Listed piece" not in document  # sitemap lists locs, not titles
    assert document.count("<loc>") == 2  # home + the one public article
    assert "<lastmod>" in document
    assert response.headers["Content-Type"].startswith("application/xml")


async def test_sitemap_paginates_beyond_page_size(app: Any, monkeypatch: Any) -> None:
    import neoblogger.app.blueprints.seo as seo_module

    monkeypatch.setattr(seo_module, "_SITEMAP_PAGE_SIZE", 2)
    root_client = await signup(app, "root")
    for index in range(3):
        await write_article(
            app,
            root_client,
            title=f"Paged piece {index}",
            publish=True,
            cover="https://x.io/c.webp",
        )
    document = await body_of(await app.test_client().get("/sitemap.xml"))
    assert document.count("<loc>") == 4  # home + all three articles


async def test_sitemap_escapes_configured_base(app: Any, monkeypatch: Any) -> None:
    context = app.extensions["neoblogger_context"]
    monkeypatch.setattr(context.config.application, "base_url", "https://exa&mple.com/")
    document = await body_of(await app.test_client().get("/sitemap.xml"))
    assert "exa&mple.com" not in document
    assert "exa&amp;mple.com" in document


async def test_robots_advertises_sitemap(app: Any) -> None:
    response = await app.test_client().get("/robots.txt")
    document = await body_of(response)
    assert "Sitemap: " in document
    assert document.endswith("sitemap.xml\n")
    assert "User-agent" in document


async def test_canonical_honors_trusted_proxy(app: Any, monkeypatch: Any) -> None:
    from neoblogger.app.security.proxy import ProxyTrust

    context = app.extensions["neoblogger_context"]
    monkeypatch.setattr(context, "proxy_trust", ProxyTrust(("<local>",)))
    rendered = await body_of(
        await app.test_client().get(
            "/",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "example.com",
            },
        )
    )
    assert 'href="https://example.com/"' in rendered


async def test_canonical_ignores_untrusted_forwarded_headers(app: Any) -> None:
    rendered = await body_of(
        await app.test_client().get(
            "/",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "example.com",
            },
        )
    )
    assert "example.com" not in rendered


async def test_canonical_and_site_metadata(app: Any) -> None:
    rendered = await body_of(await app.test_client().get("/"))
    assert '<link rel="canonical" href=' in rendered
    assert '<meta name="description"' in rendered
    assert "application/ld+json" in rendered
    assert '"WebSite"' in rendered


async def test_article_metadata_and_jsonld(app: Any) -> None:
    root_client = await signup(app, "root")
    article_id = await write_article(
        app, root_client, title="Meta rich", publish=True, cover="https://x.io/c.webp"
    )
    rendered = await body_of(await root_client.get(f"/{article_id}"))
    assert '"Article"' in rendered
    assert '"Meta rich"' in rendered
    assert '"keywords"' in rendered
    assert '"datePublished"' in rendered
    # og image uses the legacy variant for link-preview scrapers (§16)
    assert ".jpg" in rendered or ".png" in rendered


async def test_readable_dates_rendered(app: Any) -> None:
    root_client = await signup(app, "root")
    article_id = await write_article(
        app, root_client, title="Dated piece", publish=True, cover="https://x.io/c.webp"
    )
    rendered = await body_of(await root_client.get(f"/{article_id}"))
    assert "on" in rendered
    import re

    match = re.search(r"on ([A-Z][a-z]+ \d{2}, \d{4})", rendered)
    assert match is not None


async def test_stale_session_keeps_response_cache(app: Any) -> None:
    from neoblogger import build_app
    from neoblogger.app.config import CacheConfig, RuntimeConfig

    config = RuntimeConfig(
        caching=CacheConfig(enabled=True, timeout_seconds=300, storage="memory")
    )
    config.database.path = app.extensions["neoblogger_context"].config.database.path
    fresh = build_app(config)
    context = fresh.extensions["neoblogger_context"]
    await context.database.start()
    stranger = fresh.test_client()
    await stranger.get("/")
    assert context.response_cache is not None
    assert context.response_cache.size == 1
    user_client = fresh.test_client()
    await user_client.post(
        "/signup",
        form={
            "display_name": "doomed",
            "email": "doomed@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
        },
    )
    member = await context.members.by_display_name("doomed")
    assert member is not None
    await context.members.set_active(member["_id"], False)
    # A disabled account's leftover cookie is cleared, but the shared
    # anonymous cache must survive the request.
    await user_client.get("/")
    assert context.response_cache.size == 1
    await context.database.close()


async def test_signout_clears_response_cache(app: Any) -> None:
    from neoblogger import build_app
    from neoblogger.app.config import CacheConfig, RuntimeConfig

    config = RuntimeConfig(
        caching=CacheConfig(enabled=True, timeout_seconds=300, storage="memory")
    )
    config.database.path = app.extensions["neoblogger_context"].config.database.path
    fresh = build_app(config)
    context = fresh.extensions["neoblogger_context"]
    await context.database.start()
    client = fresh.test_client()
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
    page = await client.get("/write")
    from .conftest import csrf_token_from

    token = csrf_token_from(await body_of(page))
    await client.post(
        "/write",
        form={
            "csrftoken": token,
            "title": "Cache clear piece",
            "subtitle": "sub",
            "body": "Body.",
            "cover_url": "https://x.io/c.webp",
            "tags": "python",
            "action": "publish",
        },
    )
    await client.get("/")
    await client.post("/signout", form={"csrftoken": token})
    # Sign-out cleared the response cache (spec §4.3).
    assert context.response_cache is not None
    assert context.response_cache.size == 0
    await context.database.close()
