"""Tests for the maintenance CLIs: reindex and admin repair (tech-req §5.7)."""

from pathlib import Path

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
        assert await admin_repair_run("user", cfg) is True
        repaired = await context.members.by_id(second)
        assert repaired is not None
        assert repaired["administrator"] is True
        assert repaired["publisher"] is True
        assert await admin_repair_run("ghost", cfg) is False
    finally:
        await context.close()
