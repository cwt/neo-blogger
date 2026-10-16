"""Bugs 023/024 regression: shared helpers, deduped fixtures."""

import pathlib


def test_shared_helpers_exist() -> None:
    assert pathlib.Path("neoblogger/app/services/timestamps.py").exists()
    assert pathlib.Path("neoblogger/app/text/pipeline.py").exists()
    assert pathlib.Path("neoblogger/app/blueprints/paging.py").exists()
    articles = pathlib.Path("neoblogger/app/services/articles.py").read_text()
    assert "now_iso" in articles
    blog = pathlib.Path("neoblogger/app/blueprints/blog.py").read_text()
    assert "render_rich_text" in blog
    assert "parse_page_number" in blog
    repo = pathlib.Path("neoblogger/app/repositories/articles.py").read_text()
    assert "_status_facet_pipeline" in repo
    assert "_counts_from_facet" in repo
    images = pathlib.Path("neoblogger/app/blueprints/images.py").read_text()
    assert "_set_image_headers" in images
    theme = pathlib.Path("neoblogger/app/services/theme.py").read_text()
    assert "list_theme_banners" in theme
    seo = pathlib.Path("neoblogger/app/blueprints/seo.py").read_text()
    assert "request_base" in seo


def test_auth_fixture_uses_shared_conftest() -> None:
    auth_test = pathlib.Path("tests/test_web_auth.py").read_text()
    assert "async def app(" not in auth_test
    assert "def csrf_token_from" not in auth_test
    assert "from .conftest import" in auth_test
    conftest = pathlib.Path("tests/conftest.py").read_text()
    assert "async def signup" in conftest
    assert "def tiny_webp_bytes" in conftest
