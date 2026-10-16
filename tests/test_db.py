"""Data-layer tests: executor facade, indexes, backfills (tech-req §5)."""

import logging
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import neosqlite
import pytest

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.articles import ArticleRepository
from neoblogger.app.repositories.db import (
    Database,
    DatabaseNotStartedError,
    _tokenizer_library_candidates,
    backfill_articles,
    ensure_indexes,
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


async def test_concurrent_start_opens_one_connection(
    db_config: DatabaseConfig,
) -> None:
    import asyncio

    database = Database(db_config)
    await asyncio.gather(*[database.start() for _ in range(10)])

    def read_connection() -> object:
        return database.connection

    assert await database.run(read_connection) is database.connection
    await database.close()


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

    def backfill_and_read() -> dict[str, Any]:
        from typing import cast

        backfill_articles(database.connection)
        document = database.connection.articles.find_one({"title": "Old post"})
        assert isinstance(document, dict)
        return cast(dict[str, Any], document)

    repaired = await database.run(backfill_and_read)
    assert repaired["tags"] == []
    assert repaired["status"] == "published"


async def test_backfill_first_admin_promotes_lone_member(
    database: Database,
) -> None:
    def seed() -> None:
        database.connection.members.insert_one(member_document("alice"))

    await database.run(seed)

    def backfill_and_read() -> dict[str, Any]:
        from typing import cast

        run_backfills(database.connection)
        document = database.connection.members.find_one({"display_name": "alice"})
        assert isinstance(document, dict)
        return cast(dict[str, Any], document)

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


async def test_backfill_sole_admin_publisher_restores_publisher(
    database: Database,
) -> None:
    def seed() -> None:
        members = database.connection.members
        doc_alice = member_document("alice")
        doc_alice["administrator"] = True
        doc_alice["publisher"] = False
        doc_bob = member_document("bob")
        members.insert_one(doc_alice)
        members.insert_one(doc_bob)

    await database.run(seed)

    def backfill_and_read() -> dict[str, Any]:
        from typing import cast

        run_backfills(database.connection)
        document = database.connection.members.find_one({"display_name": "alice"})
        assert isinstance(document, dict)
        return cast(dict[str, Any], document)

    repaired = await database.run(backfill_and_read)
    assert bool(repaired["administrator"]) is True
    assert bool(repaired["publisher"]) is True


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


async def test_half_configured_tokenizer_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    database = Database(DatabaseConfig(path=str(tmp_path / "half.db"), tokenizer="icu"))
    await database.start()
    await database.close()
    assert any("half-configured" in record.getMessage() for record in caplog.records)


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


async def test_email_unique_index_rejects_duplicates(database: Database) -> None:
    def seed() -> None:
        doc1 = member_document("alice")
        doc2 = member_document("bob")
        doc2["email"] = doc1["email"]
        database.connection.members.insert_one(doc1)
        database.connection.members.insert_one(doc2)

    with pytest.raises(sqlite3.IntegrityError):
        await database.run(seed)


def test_tokenizer_library_candidates_ordering() -> None:
    """Verify v2 vs v1 legacy library ordering matches SQLite version."""
    v2_ordered = _tokenizer_library_candidates(
        "/usr/local/lib/libfts5_icu_th.so", sqlite_version=(3, 47, 0)
    )
    assert v2_ordered == [
        "/usr/local/lib/libfts5_icu_th.so",
        "/usr/local/lib/libfts5_icu_th_legacy.so",
    ]

    v1_ordered = _tokenizer_library_candidates(
        "/usr/local/lib/libfts5_icu_th.so", sqlite_version=(3, 45, 1)
    )
    assert v1_ordered == [
        "/usr/local/lib/libfts5_icu_th_legacy.so",
        "/usr/local/lib/libfts5_icu_th.so",
    ]

    from_legacy = _tokenizer_library_candidates(
        "/usr/local/lib/libfts5_icu_th_legacy.so", sqlite_version=(3, 47, 0)
    )
    assert from_legacy == [
        "/usr/local/lib/libfts5_icu_th.so",
        "/usr/local/lib/libfts5_icu_th_legacy.so",
    ]

    assert _tokenizer_library_candidates("") == []


async def test_tokenizer_fallback_library_loading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe fallback to legacy build when primary library fails."""
    original_init = neosqlite.Connection.__init__
    attempts: list[str] = []

    def fake_init(self: neosqlite.Connection, *args: Any, **kwargs: Any) -> None:
        tokenizers = kwargs.get("tokenizers")
        if tokenizers:
            _name, path = tokenizers[0]
            attempts.append(path)
            if "legacy" not in path:
                raise sqlite3.OperationalError("FTS5 v2 API not available")
            kwargs.pop("tokenizers", None)
            original_init(self, *args, **kwargs)
            return
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(neosqlite.Connection, "__init__", fake_init)

    db = Database(
        DatabaseConfig(
            path=str(tmp_path / "fallback.db"),
            tokenizer="ascii",
            tokenizer_library="/usr/local/lib/libfts5_icu_ascii.so",
        )
    )
    await db.start()
    assert db.active_tokenizer == "ascii"
    assert len(attempts) >= 2
    assert any("legacy" in a for a in attempts)
    await db.close()


def test_ensure_indexes_applies_tokenizer() -> None:
    """Direct ensure_indexes call must pass tokenizer through to DDL."""
    conn = neosqlite.Connection(":memory:")
    ensure_indexes(conn, tokenizer="ascii")
    sql = (
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='articles_title_fts'"
    )
    row = conn.db.execute(sql).fetchone()
    assert row is not None and "TOKENIZE=ascii" in str(row[0])
    conn.close()


async def test_fts_ddl_gated_on_tokenizer_load(tmp_path: Path) -> None:
    """Index DDL must gate on successful tokenizer load; rebuild uses active."""
    # 1. Missing library: active_tokenizer stays None, DDL uses default tokenizer
    db_failed = Database(
        DatabaseConfig(
            path=str(tmp_path / "unloaded.db"),
            tokenizer="icu_th",
            tokenizer_library=str(tmp_path / "missing.so"),
        )
    )
    await db_failed.start()
    assert db_failed.active_tokenizer is None

    def read_ddl_failed() -> str:
        sql = (
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='articles_title_fts'"
        )
        row = db_failed.connection.db.execute(sql).fetchone()
        return str(row[0]) if row else ""

    ddl_unloaded = await db_failed.run(read_ddl_failed)
    assert "TOKENIZE=icu_th" not in ddl_unloaded
    assert "USING FTS5(title, )" in ddl_unloaded
    await db_failed.close()

    # 2. Rebuilding search indexes with active_tokenizer uses configured tokenizer
    db_custom = Database(DatabaseConfig(path=str(tmp_path / "custom.db")))
    await db_custom.start()
    # Emulate active tokenizer (e.g. built-in "ascii")
    db_custom._active_tokenizer = "ascii"
    repo = ArticleRepository(db_custom)
    await repo.rebuild_search_indexes()

    def read_ddl_rebuilt() -> str:
        sql = (
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='articles_title_fts'"
        )
        row = db_custom.connection.db.execute(sql).fetchone()
        return str(row[0]) if row else ""

    ddl_rebuilt = await db_custom.run(read_ddl_rebuilt)
    assert "TOKENIZE=ascii" in ddl_rebuilt
    await db_custom.close()
