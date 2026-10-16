"""Deploy-time theme banners: path mapping, fallback, rendering (§10)."""

from typing import Any

from neoblogger.app.services.theme import banner_for_path

from .conftest import body_of, signup
from .test_web_blog import write_article


def test_banner_for_path_mapping() -> None:
    assert banner_for_path("/") == "home"
    assert banner_for_path("/tag/python") == "tag"
    assert banner_for_path("/search") == "search"
    assert banner_for_path("/signup") == "auth"
    assert banner_for_path("/signin") == "auth"
    assert banner_for_path("/recover") == "auth"
    assert banner_for_path("/profile") == "profile"
    assert banner_for_path("/profile/edit") == "profile"
    assert banner_for_path("/write") == "write"
    assert banner_for_path("/write/6acc24741a94046102289b88") == "write"
    assert banner_for_path("/upload") == "upload"
    assert banner_for_path("/admin") == "admin"
    assert banner_for_path("/admin/unpublished") == "admin"
    assert banner_for_path("/6acc24741a94046102289b88") == "article"
    assert banner_for_path("/no-such-page") == "error"


async def test_no_theme_renders_themeless_default(app: Any) -> None:
    rendered = await body_of(await app.test_client().get("/"))
    assert "theme-banner" not in rendered
    assert "generated with Agnes AI" not in rendered


async def _seed_banner(app: Any, name: str) -> None:
    from .conftest import seed_theme_banner

    context = app.extensions["neoblogger_context"]
    await context.database.start()
    await seed_theme_banner(context.objects, name)


async def test_seeded_theme_renders_banner_and_credit(app: Any) -> None:
    await _seed_banner(app, "home")
    rendered = await body_of(await app.test_client().get("/"))
    assert 'class="theme-banner"' in rendered
    assert ".webp" in rendered
    assert "generated with Agnes AI" in rendered


async def test_article_cover_wins_over_banner(app: Any) -> None:
    context = app.extensions["neoblogger_context"]
    await context.database.start()
    theme_id = await context.objects.upload(
        "theme_article.webp",
        b"fake-banner-bytes",
        {
            "owner": "theme",
            "original_filename": "theme_article.webp",
            "alt_text": "article",
            "upload_time": "2026-10-12T00:00:00",
            "content_type": "image/webp",
            "theme_banner": "article",
        },
    )
    client = await signup(app, "user")
    covered_id = await write_article(
        app, client, title="Covered", publish=True, cover="https://x.io/c.webp"
    )
    covered = await body_of(await client.get(f"/{covered_id}"))
    assert f"/images/{theme_id}.webp" not in covered
    assert "https://x.io/c.webp" in covered
    assert "<figcaption" in covered
    assert covered.count("<h1>") == 1
    draft_id = await write_article(app, client, title="Bare", publish=False)
    bare = await body_of(await client.get(f"/{draft_id}"))
    assert f"/images/{theme_id}.webp" in bare
    assert bare.count("<h1>") == 1
