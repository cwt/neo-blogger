"""SEO surface tests: sitemap, robots, canonical, metadata (spec §16)."""

from typing import Any

from neoblogger.app.blueprints.seo import canonical_url_for

from .conftest import body_of, csrf_token_from, signup
from .test_web_blog import write_article


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


def test_configured_base_url_trailing_slash_normalized() -> None:
    from neoblogger.app.config import ApplicationConfig, RuntimeConfig

    config = RuntimeConfig(application=ApplicationConfig(base_url="https://x.io"))
    assert canonical_url_for(config.application.base_url, "http://x/", "/") == (
        "https://x.io/"
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
    import re

    response = await app.test_client().get("/")
    csp = response.headers.get("Content-Security-Policy", "")
    assert "script-src 'self' 'nonce-" in csp
    match = re.search(r"'nonce-([a-f0-9]+)'", csp)
    assert match is not None
    nonce = match.group(1)

    rendered = await body_of(response)
    assert '<link rel="canonical" href=' in rendered
    assert '<meta name="description"' in rendered
    assert '<meta name="author"' in rendered
    assert 'rel="icon"' in rendered
    assert f'<script type="application/ld+json" nonce="{nonce}">' in rendered
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
    # External covers keep their original URL (bugs/005); local covers use .jpg.
    assert "https://x.io/c.webp" in rendered
    # Per-article description/author override the site-wide metadata (§16).
    assert '<meta name="description" content="Body text of Meta rich' in rendered
    assert '<meta name="author" content="root">' in rendered
    assert '<meta property="og:title" content="Meta rich">' in rendered
    assert '<meta property="og:image" content="http' in rendered


async def test_article_social_and_structured_metadata(app: Any) -> None:
    root_client = await signup(app, "root")
    article_id = await write_article(
        app, root_client, title="Social rich", publish=True, cover="https://x.io/c.webp"
    )
    rendered = await body_of(await root_client.get(f"/{article_id}"))
    assert '<meta property="og:url" content="http' in rendered
    assert '<meta property="og:site_name"' in rendered
    assert '<meta name="twitter:card" content="summary_large_image">' in rendered
    assert '<meta name="twitter:title" content="Social rich">' in rendered
    assert '<meta property="og:image:alt" content="Social rich">' in rendered
    assert '"mainEntityOfPage"' in rendered
    assert '"speakable"' in rendered
    assert "<time datetime=" in rendered


async def test_global_head_hygiene(app: Any) -> None:
    rendered = await body_of(await app.test_client().get("/"))
    assert '<meta name="theme-color"' in rendered
    assert 'href="#content"' in rendered
    assert 'id="content"' in rendered
    assert '<a href="/feed.xml">Feed</a>' in rendered


async def test_meta_description_never_empty(app: Any) -> None:
    import re

    for path in ("/", "/search?q=x", "/signup"):
        rendered = await body_of(await app.test_client().get(path))
        match = re.search(r'<meta name="description" content="([^"]*)">', rendered)
        assert match is not None, path
        assert match.group(1).strip() != "", path


def test_mobile_nav_and_code_contrast_css() -> None:
    from pathlib import Path

    css = Path("neoblogger/app/web/static/custom.css").read_text()
    assert ".site-header .nav-links li { white-space: nowrap; padding: 0; }" in css
    assert "div.highlight pre { background-color: #f8f8f8;" in css


async def test_thin_pages_opt_out_of_indexing(app: Any) -> None:
    client = app.test_client()
    for path in ("/search?q=x", "/signup", "/signin", "/recover"):
        rendered = await body_of(await client.get(path))
        assert '<meta name="robots" content="noindex, follow">' in rendered
    home = await body_of(await client.get("/"))
    assert "noindex" not in home


async def test_atom_feed_lists_public_articles(app: Any) -> None:
    root_client = await signup(app, "root")
    await write_article(
        app, root_client, title="Feed piece", publish=True, cover="https://x.io/c.webp"
    )
    await write_article(app, root_client, title="Feed draft", publish=False)
    response = await app.test_client().get("/feed.xml")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/atom+xml")
    document = await body_of(response)
    assert "<feed" in document
    assert "Feed piece" in document
    assert "Feed draft" not in document
    assert "<updated>" in document


async def test_llms_txt_lists_site_and_articles(app: Any) -> None:
    root_client = await signup(app, "root")
    await write_article(
        app, root_client, title="LLM piece", publish=True, cover="https://x.io/c.webp"
    )
    response = await app.test_client().get("/llms.txt")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/plain")
    document = await body_of(response)
    assert document.startswith("# ")
    assert "LLM piece" in document
    assert "/feed.xml" in document
    assert "/sitemap.xml" in document


async def test_readable_dates_rendered(app: Any) -> None:
    root_client = await signup(app, "root")
    article_id = await write_article(
        app, root_client, title="Dated piece", publish=True, cover="https://x.io/c.webp"
    )
    rendered = await body_of(await root_client.get(f"/{article_id}"))
    assert "on" in rendered
    import re

    match = re.search(
        r"<time datetime=\"([^\"]+)\">([A-Z][a-z]+ \d{2}, \d{4})", rendered
    )
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
    page_up = await user_client.get("/signup")
    token_up = csrf_token_from(await body_of(page_up))
    await user_client.post(
        "/signup",
        form={
            "display_name": "doomed",
            "email": "doomed@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
            "csrftoken": token_up,
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
