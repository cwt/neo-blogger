"""Bugs 021/022 regression: dead code removed."""

import pathlib


def test_dead_repository_methods_removed() -> None:
    articles = pathlib.Path("neoblogger/app/repositories/articles.py").read_text()
    assert "covers_in_use_any" not in articles
    assert "def covers_in_use(" not in articles
    assert "covers_using_image" in articles
    members = pathlib.Path("neoblogger/app/repositories/members.py").read_text()
    assert "def create(" not in members
    assert "exists_any" not in members
    assert "create_first_or_member" in members


def test_dead_symbols_removed() -> None:
    auth = pathlib.Path("neoblogger/app/services/auth.py").read_text()
    assert "AuthError" not in auth
    assert "def resolve(" not in auth
    objects = pathlib.Path("neoblogger/app/services/objects.py").read_text()
    assert "_LEGACY_EXTENSIONS" not in objects
    blog = pathlib.Path("neoblogger/app/blueprints/blog.py").read_text()
    assert "_page_parameters" not in blog
    theme = pathlib.Path("neoblogger/cli/theme.py").read_text()
    assert "\nAPI_ENDPOINT" not in theme
    assert "\nMODEL" not in theme
    app_js = pathlib.Path("neoblogger/app/web/static/app.js").read_text()
    assert "else if (bodyField)" not in app_js
    assert not pathlib.Path("poetry.lock").exists()
    assert "poetry.lock" not in pathlib.Path("pyproject.toml").read_text()


def test_config_method_removed() -> None:
    config = pathlib.Path("neoblogger/app/config.py").read_text()
    assert "resolve_base_url" not in config
