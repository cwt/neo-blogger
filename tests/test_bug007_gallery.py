"""Bugs 007/016/017 regression: theme gallery exclusion, indexes, bucket cache."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.articles import ArticleRepository
from neoblogger.app.repositories.db import Database, ensure_indexes
from neoblogger.app.repositories.objects import ObjectRepository
from neoblogger.app.services.objects import ObjectsService


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(DatabaseConfig(path=str(tmp_path / "bug007.db")))
    await database.start()
    yield database
    await database.close()


@pytest.fixture
def objects(database: Database) -> ObjectRepository:
    return ObjectRepository(database)


async def _upload(objects: ObjectRepository, owner: str, name: str = "img.webp") -> str:
    return await objects.upload(
        name,
        b"x",
        {
            "owner": owner,
            "original_filename": name,
            "alt_text": name,
            "upload_time": "2026-01-01T00:00:00",
            "content_type": "image/webp",
        },
    )


async def test_admin_gallery_excludes_theme(
    objects: ObjectRepository,
) -> None:
    await _upload(objects, "alice", "alice_img.webp")
    await _upload(objects, "theme", "theme_banner.webp")
    rows, total = await objects.list_for(None, 1, 12)
    assert total == 1
    assert all(row["metadata"].get("owner") != "theme" for row in rows)
    assert rows[0]["metadata"]["owner"] == "alice"


async def test_theme_listing_still_works(objects: ObjectRepository) -> None:
    await _upload(objects, "alice", "alice_img.webp")
    theme_id = await _upload(objects, "theme", "theme_banner.webp")
    rows, total = await objects.list_for("theme", 1, 12)
    assert total == 1
    assert rows[0]["id"] == theme_id


async def test_delete_refuses_theme(
    database: Database, objects: ObjectRepository
) -> None:
    articles = ArticleRepository(database)

    async def run_image(work: Any) -> Any:
        return work()

    service = ObjectsService(objects, articles, run_image, 1024 * 1024)
    theme_id = await _upload(objects, "theme", "theme_banner.webp")
    admin: Any = {"display_name": "admin", "administrator": True}
    ok, using = await service.delete(admin, theme_id)
    assert ok is False
    assert using == []
    assert await objects.metadata(theme_id) is not None
    alice_id = await _upload(objects, "alice", "alice_img.webp")
    alice: Any = {"display_name": "alice", "administrator": False}
    ok2, _ = await service.delete(alice, alice_id)
    assert ok2 is True
    assert await objects.metadata(alice_id) is None


async def test_ensure_indexes_idempotent_with_new_indexes(
    database: Database,
) -> None:
    def ensure_twice() -> dict[str, Any]:
        ensure_indexes(database.connection)
        ensure_indexes(database.connection)
        return {
            "articles": database.connection.articles.index_information(),
            "comments": database.connection.comments.index_information(),
        }

    info = await database.run(ensure_twice)
    assert (
        "idx_articles_status_author_active_author_publisher_created" in info["articles"]
    )
    assert "idx_articles_author_publisher_created" in info["articles"]
    assert "idx_comments_article_id_author_active_created" in info["comments"]

    def fs_indexed() -> bool:
        rows = database.connection.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_fs_files_metadata_owner'"
        ).fetchall()
        return len(rows) == 1

    assert await database.run(fs_indexed) is True


async def test_bucket_reused(database: Database, objects: ObjectRepository) -> None:
    def same_run() -> bool:
        return objects._bucket() is objects._bucket()

    assert await database.run(same_run) is True

    def fetch_id() -> int:
        return id(objects._bucket())

    first_id = await database.run(fetch_id)
    second_id = await database.run(fetch_id)
    assert first_id == second_id
