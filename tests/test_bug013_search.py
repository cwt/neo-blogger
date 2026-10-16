"""Bugs 013/014/015 regression: projections, search pagination, TaskGroup."""

from pathlib import Path

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.articles import ArticleRepository
from neoblogger.app.repositories.db import Database


async def _seed(tmp_path: Path) -> Database:
    db = Database(DatabaseConfig(path=str(tmp_path / "b13.db")))
    await db.start()

    def seed() -> None:
        conn = db.connection
        for idx in range(3):
            conn.articles.insert_one(
                {
                    "title": f"T{idx}",
                    "subtitle": "s",
                    "body": "x" * 5000,
                    "cover_url": "",
                    "author": "alice",
                    "created": f"2026-01-0{idx + 1}T00:00:00",
                    "tags": [],
                    "status": "published",
                    "author_active": True,
                    "author_publisher": True,
                }
            )

    await db.run(seed)
    return db


async def test_feed_page_omits_body(tmp_path: Path) -> None:
    db = await _seed(tmp_path)
    try:
        articles = ArticleRepository(db)
        rows, total = await articles.feed_page({"status": "published"}, 1, 10)
        assert total == 3
        assert len(rows) == 3
        for row in rows:
            assert "body" not in row
    finally:
        await db.close()


async def test_search_paginates_without_materializing(tmp_path: Path) -> None:
    db = await _seed(tmp_path)
    try:
        articles = ArticleRepository(db)
        rows, total = await articles.search({"status": "published"}, "T", 1, 2)
        assert len(rows) <= 2
        for row in rows:
            assert "body" not in row
        assert total >= len(rows)
    finally:
        await db.close()


async def test_profile_posts_single_facet(tmp_path: Path) -> None:
    db = await _seed(tmp_path)
    try:
        articles = ArticleRepository(db)
        drafts, published = await articles.author_profile_posts("alice", 2)
        assert len(published) == 2
        for row in drafts + published:
            assert "body" not in row
    finally:
        await db.close()


async def test_sitemap_entries_minimal(tmp_path: Path) -> None:
    db = await _seed(tmp_path)
    try:
        articles = ArticleRepository(db)
        rows = await articles.sitemap_entries(1, 10)
        assert len(rows) == 3
        for row in rows:
            assert "body" not in row
            assert "_id" in row
            assert "created" in row
    finally:
        await db.close()


def test_taskgroup_used_in_hot_routes() -> None:
    import pathlib

    for name in ["admin.py", "discovery.py", "profile.py", "accounts.py"]:
        found = False
        for path in pathlib.Path("neoblogger").rglob(name):
            if "TaskGroup" in path.read_text():
                found = True
        assert found, name
    blog = pathlib.Path("neoblogger/app/blueprints/blog.py").read_text()
    assert "page_data" in blog
