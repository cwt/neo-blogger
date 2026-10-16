"""Regression tests for bugs 010 (UI/SEO) and 011 (Containerfile)."""

from pathlib import Path
from typing import Any

from .conftest import body_of
from .test_web_blog import signup, write_article

REPO = Path(__file__).resolve().parent.parent


def read_repo(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def test_article_template_has_keywords_and_tag_meta() -> None:
    template = read_repo("neoblogger/app/web/templates/article.html")
    assert '<meta name="keywords"' in template
    assert "article:tag" in template


def test_admin_template_has_unpublished_link_and_total() -> None:
    template = read_repo("neoblogger/app/web/templates/admin.html")
    assert 'href="/admin/unpublished"' in template
    assert "total articles" in template


def test_admin_template_hides_disable_on_admin_rows() -> None:
    template = read_repo("neoblogger/app/web/templates/admin.html")
    assert "not member.administrator" in template
    assert 'action="/admin/members/{{ member._id }}/disable"' in template


def test_upload_template_has_copy_url_buttons() -> None:
    template = read_repo("neoblogger/app/web/templates/upload.html")
    assert "data-copy-url" in template


def test_base_template_has_shared_dialog() -> None:
    template = read_repo("neoblogger/app/web/templates/base.html")
    assert "<dialog" in template
    assert "confirm-dialog" in template


def test_app_js_binds_dialog_copy_and_comment_toolbar() -> None:
    script = read_repo("neoblogger/app/web/static/app.js")
    assert "confirm-dialog" in script
    assert "data-copy-url" in script
    assert "comment-text" in script
    assert "EasyMDE" in script
    assert 'form[action*="/delete"]' in script
    assert ".flash-success" in script


def test_containerfile_uses_lockfile_and_ships_licenses() -> None:
    containerfile = read_repo("Containerfile")
    assert "uv.lock" in containerfile
    assert "uv export" in containerfile or "uv sync --frozen" in containerfile
    assert "--frozen" in containerfile
    assert "--no-deps" in containerfile
    assert "LICENSE" in containerfile
    assert "THIRD-PARTY-LICENSES.md" in containerfile


def test_pyproject_license_files_includes_bundle() -> None:
    pyproject = read_repo("pyproject.toml")
    assert "THIRD-PARTY-LICENSES.md" in pyproject
    assert '"LICENSE"' in pyproject or "'LICENSE'" in pyproject


async def test_live_admin_dashboard_has_total_and_unpublished(app: Any) -> None:
    from .test_web_blog import write_article as write

    root_client = await signup(app, "root")
    await write(
        app, root_client, title="Live stat", publish=True, cover="https://x.io/c.webp"
    )
    rendered = await body_of(await root_client.get("/admin"))
    assert 'href="/admin/unpublished"' in rendered
    assert "total articles" in rendered


async def test_live_article_page_has_keywords_meta(app: Any) -> None:
    root_client = await signup(app, "root")
    article_id = await write_article(
        app,
        root_client,
        title="Tagged",
        publish=True,
        cover="https://x.io/c.webp",
        tags="python",
    )
    rendered = await body_of(await root_client.get(f"/{article_id}"))
    assert '<meta name="keywords"' in rendered
    assert 'property="article:tag"' in rendered


async def test_live_upload_gallery_has_copy_button(app: Any) -> None:
    from .test_web_images import tiny_png_bytes, upload_image

    root_client = await signup(app, "root")
    await upload_image(app, root_client, "copy.png", tiny_png_bytes())
    rendered = await body_of(await root_client.get("/upload"))
    assert "data-copy-url" in rendered
