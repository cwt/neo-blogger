"""Tests for the maintenance CLIs: reindex and admin repair (tech-req §5.7)."""

from pathlib import Path

import pytest

from neoblogger.app.config import load_config
from neoblogger.app.context import AppContext
from neoblogger.cli.admin_repair import run as admin_repair_run
from neoblogger.cli.reindex import run as reindex_run


def _make_config(tmp_path: Path) -> str:
    db_file = tmp_path / "maint_test.db"
    cfg_file = tmp_path / "maint_test.toml"
    cfg_file.write_text(
        f"""[application]
secret_key = "test-secret-key-sufficiently-long-for-testing"

[database]
path = "{db_file}"
"""
    )
    return str(cfg_file)


async def test_admin_repair_honors_config_path(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        first, _ = await context.accounts.register(
            "root", "root@x.io", "pw", "first-pet", "City"
        )
        second, _ = await context.accounts.register(
            "user", "user@x.io", "pw", "first-pet", "Town"
        )
        # Two members: no lone-member promotion; strip admin to simulate.
        await context.members.set_administrator(first, False)
        # user creates an article before repair (not publisher yet)
        article_id = await context.articles.create(
            "User Story",
            "sub",
            "body",
            "",
            "user",
            "2026-10-12T00:00:00",
            ["test"],
            "published",
            author_active=True,
            author_publisher=False,
        )
        article_before = await context.articles.by_id(article_id)
        assert article_before is not None
        assert article_before["author_publisher"] is False

        version_before = await context.meta.content_version()
        assert await admin_repair_run("user", cfg) is True
        repaired = await context.members.by_id(second)
        assert repaired is not None
        assert repaired["administrator"] is True
        assert repaired["publisher"] is True

        # Snapshots resynced and content version bumped
        article_after = await context.articles.by_id(article_id)
        assert article_after is not None
        assert article_after["author_publisher"] is True
        assert await context.meta.content_version() == version_before + 1

        assert await admin_repair_run("ghost", cfg) is False
    finally:
        await context.close()


async def test_reindex_honors_config_path(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        await context.articles.create(
            "Indexed",
            "sub",
            "searchable body",
            "",
            "alice",
            "2026-01-01T00:00:00",
            [],
            "published",
        )
    finally:
        await context.close()
    await reindex_run(cfg)
    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        docs, total = await context.articles.search(
            {"status": "published"}, "searchable", 1, 10
        )
        assert total == 1
        assert docs[0]["title"] == "Indexed"
    finally:
        await context.close()


def test_theme_manifest_covers_every_banner() -> None:
    from neoblogger.cli.theme import BANNERS, RATIO, prompt_for

    assert set(BANNERS) == {
        "home",
        "article",
        "tag",
        "search",
        "auth",
        "profile",
        "write",
        "upload",
        "admin",
        "error",
    }
    assert RATIO == "21:9"
    for name in BANNERS:
        prompt = prompt_for(name)
        assert len(prompt) > len(name)
        assert "no text" in prompt


def test_theme_dotenv_parsing(tmp_path: Path) -> None:
    from neoblogger.cli.theme import read_dotenv, resolve_key

    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "# comment\n"
        "\n"
        "AGNES_API_KEY=from-file\n"
        "OTHER = 'quoted value'\n"
        'QUOTED="double"\n'
        "EMPTY=\n"
        "NOEQUALS\n",
        encoding="utf-8",
    )
    parsed = read_dotenv(str(dotenv))
    assert parsed["AGNES_API_KEY"] == "from-file"
    assert parsed["OTHER"] == "quoted value"
    assert parsed["QUOTED"] == "double"
    assert parsed["EMPTY"] == ""
    assert "NOEQUALS" not in parsed
    assert read_dotenv(str(tmp_path / "missing.env")) == {}
    assert resolve_key({"AGNES_API_KEY": "from-env"}, str(dotenv)) == "from-env"
    assert resolve_key({}, str(dotenv)) == "from-file"
    assert resolve_key({}, str(tmp_path / "missing.env")) == ""


async def test_theme_generate_refuses_without_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neoblogger.cli.theme import run as theme_run

    monkeypatch.delenv("AGNES_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert await theme_run(_make_config(tmp_path), force=False) == 2


async def _seed_theme_banner(cfg: str, name: str) -> None:
    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        await context.objects.upload(
            f"theme_{name}.webp",
            b"fake-banner-bytes",
            {
                "owner": "theme",
                "original_filename": f"theme_{name}.webp",
                "alt_text": name,
                "upload_time": "2026-10-12T00:00:00",
                "content_type": "image/webp",
                "theme_banner": name,
            },
        )
    finally:
        await context.close()


async def test_theme_generate_refuses_complete_set_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neoblogger.cli.theme import BANNERS
    from neoblogger.cli.theme import run as theme_run

    cfg = _make_config(tmp_path)
    for name in BANNERS:
        await _seed_theme_banner(cfg, name)
    monkeypatch.setenv("AGNES_API_KEY", "fake-key-never-dialed")
    assert await theme_run(cfg, force=False) == 1


async def test_theme_clear_removes_all(tmp_path: Path) -> None:
    from neoblogger.cli import theme as theme_module

    cfg = _make_config(tmp_path)
    await _seed_theme_banner(cfg, "home")
    await _seed_theme_banner(cfg, "error")
    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        assert await theme_module._clear_theme(context) == 2
        rows, _total = await context.objects.list_for("theme", 1, 50)
        assert rows == []
    finally:
        await context.close()
