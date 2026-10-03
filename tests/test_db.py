"""Data-layer tests: executor facade, indexes, backfills (tech-req §5)."""

import logging
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.db import (
    Database,
    DatabaseNotStartedError,
    backfill_articles,
    run_backfills,
)
from neoblogger.app.repositories.documents import document_id


@pytest.fixture
def db_config(tmp_path: Path) -> DatabaseConfig:
    return DatabaseConfig(path=str(tmp_path / "test.db"))


@pytest.fixture
async def database(db_config: DatabaseConfig) -> AsyncIterator[Database]:
    database = Database(db_config)
    await database.start()
    yield database
    await database.close()


def member_document(display_name: str) -> dict[str, object]:
    return {
        "display_name": display_name,
        "email": f"{display_name}@example.com",
        "password_hash": "hash",
        "security_question_code": "first-pet",
        "security_answer_hash": "hash",
        "active": True,
        "administrator": False,
        "publisher": False,
    }


async def test_start_seeds_content_version(database: Database) -> None:
    def read_version() -> int:
        document = database.connection.meta.find_one({"name": "content_version"})
        assert document is not None
        return int(document["value"])

    assert await database.run(read_version) == 0


async def test_start_is_idempotent(database: Database) -> None:
    await database.start()
    await database.start()

    def count_meta() -> int:
        return int(database.connection.meta.count_documents({}))

    assert await database.run(count_meta) == 1


async def test_run_before_start_raises(db_config: DatabaseConfig) -> None:
    database = Database(db_config)

    def probe() -> int:
        return 1

    with pytest.raises(DatabaseNotStartedError):
        await database.run(probe)


async def test_connection_property_before_start_raises(
    db_config: DatabaseConfig,
) -> None:
    database = Database(db_config)
    with pytest.raises(DatabaseNotStartedError):
        _ = database.connection


async def test_unique_display_name_index(database: Database) -> None:
    def insert_member() -> None:
        database.connection.members.insert_one(member_document("alice"))

    await database.run(insert_member)

    def insert_duplicate() -> None:
        database.connection.members.insert_one(member_document("alice"))

    with pytest.raises(sqlite3.IntegrityError):
        await database.run(insert_duplicate)


async def test_backfill_articles_repairs_missing_fields(database: Database) -> None:
    def seed() -> None:
        database.connection.articles.insert_one(
            {
                "title": "Old post",
                "subtitle": "Sub",
                "body": "Body",
                "cover_url": "",
                "author": "alice",
                "created": "2026-01-01T00:00:00",
            }
        )

    await database.run(seed)

    def backfill_and_read() -> dict[str, object]:
        backfill_articles(database.connection)
        return database.connection.articles.find_one({"title": "Old post"})

    repaired = await database.run(backfill_and_read)
    assert repaired["tags"] == []
    assert repaired["status"] == "published"


async def test_backfill_first_admin_promotes_lone_member(
    database: Database,
) -> None:
    def seed() -> None:
        database.connection.members.insert_one(member_document("alice"))

    await database.run(seed)

    def backfill_and_read() -> dict[str, object]:
        run_backfills(database.connection)
        return database.connection.members.find_one({"display_name": "alice"})

    promoted = await database.run(backfill_and_read)
    assert bool(promoted["administrator"]) is True
    assert bool(promoted["publisher"]) is True


async def test_backfill_first_admin_skips_multi_member(
    database: Database,
) -> None:
    def seed() -> None:
        members = database.connection.members
        members.insert_one(member_document("alice"))
        members.insert_one(member_document("bob"))

    await database.run(seed)

    def backfill_and_read() -> list[dict[str, object]]:
        run_backfills(database.connection)
        return list(database.connection.members.find())

    after = await database.run(backfill_and_read)
    assert all(member["administrator"] is False for member in after)


async def test_missing_tokenizer_library_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    database = Database(
        DatabaseConfig(
            path=str(tmp_path / "tokenizer.db"),
            tokenizer="icu",
            tokenizer_library=str(tmp_path / "nope.so"),
        )
    )
    await database.start()

    def probe() -> int:
        return int(database.connection.things.count_documents({}))

    assert await database.run(probe) == 0
    await database.close()
    assert any(
        "could not be loaded" in record.getMessage() for record in caplog.records
    )


async def test_restart_on_populated_database_is_safe(tmp_path: Any) -> None:
    """16: startup must not fail against an already-indexed database."""

    config = DatabaseConfig(path=str(tmp_path / "restart.db"))
    first = Database(config)
    await first.start()

    def seed() -> None:
        first.connection.members.insert_one(member_document("alice"))
        first.connection.articles.insert_one(
            {
                "title": "Restart survivor",
                "subtitle": "S",
                "body": "Body text for FTS.",
                "cover_url": "",
                "author": "alice",
                "created": "2026-01-01T00:00:00",
                "tags": [],
                "status": "published",
                "author_active": True,
                "author_publisher": True,
            }
        )

    await first.run(seed)
    await first.close()

    second = Database(config)
    await second.start()  # would raise IntegrityError before the hardening
    hits = 0

    def probe() -> int:
        return len(
            list(second.connection.articles.find({"$text": {"$search": "survivor"}}))
        )

    hits = await second.run(probe)
    assert hits == 1
    await second.close()


async def test_document_id_normalization() -> None:
    assert document_id({"_id": "abc123"}) == "abc123"
    assert document_id({"_id": 4242}) == "4242"
    with pytest.raises(KeyError):
        document_id({})
