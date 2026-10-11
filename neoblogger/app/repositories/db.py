"""NeoSQLite access layer: executor facade, indexes, backfills (tech-req §5.1).

The engine is synchronous; this module owns the only blocking hop — a
process-wide single-thread executor on which the one connection is opened
and through which all repository work runs. Submits originate from the
event loop only: nested submits from inside executor work deadlock on
``max_workers=1`` (Spike S1-4b).
"""

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

import neosqlite
from neosqlite import ASCENDING, DESCENDING

from ..config import DatabaseConfig

T = TypeVar("T")

_logger = logging.getLogger(__name__)


class DatabaseNotStartedError(RuntimeError):
    """Raised when repository work runs before ``start()`` or after ``close()``."""


def _fts_table_exists(connection: Any, collection: str, field: str) -> bool:
    """Whether the engine already built ``<collection>_<field>_fts`` (S8).

    Creating is idempotent on fresh databases (S4), but re-populating on a
    restart against an existing indexed database trips the engine's
    populate INSERT with duplicate rowids; skip in that case.
    """
    table = f"{collection}_{field}_fts"
    row = connection.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def ensure_indexes(connection: neosqlite.Connection) -> None:
    """Create all documented indexes idempotently (spec §12.2, tech-req §5.4)."""
    articles = connection.articles
    articles.create_index("created", datetime_field=True)
    articles.create_index("author")
    articles.create_index("tags")
    articles.create_index("cover_url")
    articles.create_index("status")
    articles.create_index([("status", ASCENDING), ("created", DESCENDING)])
    articles.create_index(
        [("author", ASCENDING), ("status", ASCENDING), ("created", DESCENDING)]
    )
    for field in ("title", "subtitle", "body"):
        if not _fts_table_exists(connection, "articles", field):
            articles.create_search_index(field)
    comments = connection.comments
    comments.create_index("created")
    comments.create_index("article_id")
    comments.create_index("author")
    comments.create_index([("article_id", ASCENDING), ("created", DESCENDING)])
    members = connection.members
    members.create_index("display_name", unique=True)
    members.create_index("email")
    members.create_index(
        [("administrator", ASCENDING), ("publisher", ASCENDING), ("active", ASCENDING)]
    )


def ensure_content_version(connection: neosqlite.Connection) -> None:
    """Seed the response-cache version counter if absent (spec §14)."""
    meta = connection.meta
    if meta.count_documents({"name": "content_version"}) == 0:
        meta.insert_one({"name": "content_version", "value": 0})


def backfill_articles(connection: neosqlite.Connection) -> None:
    """Repair legacy articles missing tags or status (spec §19.6)."""
    articles = connection.articles
    tags_result = articles.update_many(
        {"tags": {"$exists": False}}, {"$set": {"tags": []}}
    )
    status_result = articles.update_many(
        {"status": {"$exists": False}}, {"$set": {"status": "published"}}
    )
    if tags_result.modified_count or status_result.modified_count:
        _logger.info(
            "backfilled articles: %d tags, %d status fields added",
            tags_result.modified_count,
            status_result.modified_count,
        )


def backfill_first_admin(connection: neosqlite.Connection) -> None:
    """Promote a lone member to administrator and publisher (spec §2, §19.6).

    Unambiguous legacy repair only: exactly one member exists and no
    administrator. Multi-member no-admin databases need the explicit CLI
    admin-repair script instead of a silent guess.
    """
    members = connection.members
    if members.count_documents({}) != 1:
        return
    if members.count_documents({"administrator": True}) != 0:
        return
    members.update_one({}, {"$set": {"administrator": True, "publisher": True}})
    _logger.info("promoted the only member to administrator and publisher")


def backfill_author_snapshots(connection: Any) -> None:
    """Recompute denormalized author visibility snapshots (§13, §19.6).

    Unconditional per-member update: ``modified_count`` only advances when
    a value actually differs, so the pass is idempotent and cheap.
    """
    articles = connection.articles
    changed = 0
    for member in list(connection.members.find({})):
        snapshots = {
            "author_active": bool(member.get("active", False)),
            "author_publisher": bool(member.get("publisher", False)),
        }
        result = articles.update_many(
            {"author": member["display_name"]}, {"$set": snapshots}
        )
        changed += result.modified_count
    if changed:
        _logger.info("resynced author visibility snapshots on %d articles", changed)


def run_backfills(connection: Any) -> None:
    """Run every idempotent startup backfill (tech-req §5.7)."""
    backfill_articles(connection)
    backfill_first_admin(connection)
    backfill_author_snapshots(connection)
    ensure_content_version(connection)


class Database:
    """The DB executor facade; every repository call routes through ``run()``."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._executor: ThreadPoolExecutor | None = None
        self._connection: neosqlite.Connection | None = None
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        """Open the connection on the executor thread; initialize idempotently.

        Serialized by a lock: concurrent first requests otherwise open
        parallel connections and leak all but the last.
        """
        async with self._start_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="neoblogger-db"
                )
            if self._connection is not None:
                return
            connection = await self.run(self._open_connection)
            self._connection = connection

            def initialize() -> None:
                ensure_indexes(connection)
                run_backfills(connection)

            await self.run(initialize)

    async def close(self) -> None:
        """Close the connection and stop the executor (idempotent)."""
        async with self._start_lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                await self.run(connection.close)
            executor = self._executor
            self._executor = None
        if executor is not None:
            # Shutdown blocks until queued work drains; keep it off the
            # event loop so closing never stalls request handling.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, executor.shutdown)

    async def run(self, work: Callable[[], T]) -> T:
        """Submit sync DB work to the executor; call from the event loop only."""
        executor = self._executor
        if executor is None:
            raise DatabaseNotStartedError("database not started: call start() first")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, work)

    @property
    def connection(self) -> Any:
        """The opened engine connection, for use inside ``run()`` work only."""
        if self._connection is None:
            raise DatabaseNotStartedError("database not started: call start() first")
        return self._connection

    def _open_connection(self) -> neosqlite.Connection:
        """Open the engine connection; runs on the executor thread (§5.1)."""
        path = self._config.path
        parent = Path(path).parent
        if str(parent) not in (".", ""):
            parent.mkdir(parents=True, exist_ok=True)
        tokenizer = self._config.tokenizer
        library = self._config.tokenizer_library
        if tokenizer and library:
            try:
                return neosqlite.Connection(path, tokenizers=[(tokenizer, library)])
            except sqlite3.OperationalError as error:
                _logger.warning(
                    "tokenizer %r (%s) could not be loaded (%s); "
                    "continuing with the default tokenizer (spec §12.2)",
                    tokenizer,
                    library,
                    error,
                )
        elif tokenizer or library:
            _logger.warning(
                "tokenizer and tokenizer_library must both be set; "
                "ignoring the half-configured tokenizer (spec §12.2)"
            )
        return neosqlite.Connection(path)
