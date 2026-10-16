"""Bugs 004/019 regression: backfill resyncs comments + distinct authors."""

from pathlib import Path

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.db import Database, backfill_author_snapshots


async def test_backfill_resyncs_comments_and_legacy(tmp_path: Path) -> None:
    db = Database(DatabaseConfig(path=str(tmp_path / "b4.db")))
    await db.start()
    try:

        def seed() -> None:
            conn = db.connection
            conn.members.insert_one(
                {
                    "display_name": "alice",
                    "email": "a@x.io",
                    "active": False,
                    "publisher": False,
                    "administrator": False,
                }
            )
            conn.members.insert_one(
                {
                    "display_name": "ghost",
                    "email": "g@x.io",
                    "active": True,
                    "publisher": True,
                    "administrator": False,
                }
            )
            conn.articles.insert_one(
                {
                    "author": "alice",
                    "title": "T",
                    "status": "published",
                    "author_active": True,
                    "author_publisher": True,
                }
            )
            conn.comments.insert_one(
                {
                    "author": "alice",
                    "article_id": "a1",
                    "text": "hi",
                    "author_active": True,
                }
            )
            # Legacy comment without flag.
            conn.comments.insert_one(
                {"author": "alice", "article_id": "a1", "text": "old"}
            )

        await db.run(seed)

        def run_backfill() -> None:
            backfill_author_snapshots(db.connection)

        await db.run(run_backfill)

        def check() -> None:
            conn = db.connection
            article = conn.articles.find_one({"author": "alice"})
            assert article is not None
            assert not article["author_active"]
            assert not article["author_publisher"]
            for comment in conn.comments.find({"author": "alice"}):
                assert not comment["author_active"]

        await db.run(check)
    finally:
        await db.close()
