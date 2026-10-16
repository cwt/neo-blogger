"""NeoSQLite access layer: executor facade, indexes, backfills (tech-req §5.1).

The engine is synchronous; this module owns the only blocking hop — a
process-wide single-thread executor on which the one connection is opened
and through which all repository work runs. Submits originate from the
event loop only: nested submits from inside executor work deadlock on
``max_workers=1`` (Spike S1-4b).
"""

import asyncio
import contextlib
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


def _tokenizer_library_candidates(
    library: str, *, sqlite_version: tuple[int, int, int] | None = None
) -> list[str]:
    """Return library path candidates ordered by SQLite FTS5 API compatibility.

    FTS5 API v2 (iVersion >= 3, providing xCreateTokenizer_v2) requires
    SQLite >= 3.47.0. Earlier releases (e.g. SQLite 3.45.1 on Ubuntu 24.04 LTS)
    support FTS5 API v1 only, matching the '_legacy' .so build artifacts
    (tech-req §5.8, §12.2).
    """
    if not library:
        return []
    path = Path(library)
    name = path.name
    parent = path.parent
    suffix = "".join(path.suffixes)
    stem = name[: len(name) - len(suffix)] if suffix else name
    if stem.endswith("_legacy"):
        v1_name = name
        v2_name = f"{stem[:-7]}{suffix}"
    else:
        v2_name = name
        v1_name = f"{stem}_legacy{suffix}"
    v2_path = str(parent / v2_name) if str(parent) not in ("", ".") else v2_name
    v1_path = str(parent / v1_name) if str(parent) not in ("", ".") else v1_name

    version = (
        sqlite_version if sqlite_version is not None else sqlite3.sqlite_version_info
    )
    ordered = [v2_path, v1_path] if version >= (3, 47, 0) else [v1_path, v2_path]

    seen: set[str] = set()
    result: list[str] = []
    for cand in ordered:
        if cand not in seen:
            seen.add(cand)
            result.append(cand)
    return result


def ensure_indexes(
    connection: neosqlite.Connection, tokenizer: str | None = None
) -> None:
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
    existing_search_indexes = set(articles.list_search_indexes())
    for field in ("title", "subtitle", "body"):
        if field not in existing_search_indexes:
            articles.create_search_index(field, tokenizer=tokenizer)
    comments = connection.comments
    comments.create_index("created")
    comments.create_index("article_id")
    comments.create_index("author")
    comments.create_index([("article_id", ASCENDING), ("created", DESCENDING)])
    members = connection.members
    members.create_index("display_name", unique=True)
    members.create_index("email", unique=True)
    members.create_index(
        [("administrator", ASCENDING), ("publisher", ASCENDING), ("active", ASCENDING)]
    )
    from neosqlite.gridfs import GridFSBucket

    GridFSBucket(connection)


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


def backfill_sole_admin_publisher(connection: neosqlite.Connection) -> None:
    """Ensure a sole administrator is always a publisher (spec §2, tech-req §3.4)."""
    members = connection.members
    if members.count_documents({"administrator": True}) == 1:
        admin = members.find_one({"administrator": True})
        if admin is not None and not admin.get("publisher", False):
            members.update_one({"_id": admin["_id"]}, {"$set": {"publisher": True}})
            _logger.info(
                "restored publisher status on sole administrator %r",
                admin.get("display_name"),
            )


def backfill_author_snapshots(connection: Any) -> None:
    """Recompute denormalized author visibility snapshots (§13, §19.6).

    Resyncs both articles and comments (bugs/004); only touches distinct
    authors present in content and only out-of-sync rows (bugs/019).
    """
    articles = connection.articles
    comments = connection.comments
    try:
        article_authors = set(articles.distinct("author"))
    except Exception:
        article_authors = set()
    try:
        comment_authors = set(comments.distinct("author"))
    except Exception:
        comment_authors = set()
    authors = article_authors | comment_authors
    members_by_name: dict[str, Any] = {}
    try:
        for member in list(connection.members.find({})):
            members_by_name[str(member.get("display_name", ""))] = member
    except Exception:
        members_by_name = {}
    changed = 0
    # Default missing flags first so the mismatch pass repairs them too.
    with contextlib.suppress(Exception):
        comments.update_many(
            {"author_active": {"$exists": False}}, {"$set": {"author_active": True}}
        )
    for name in authors:
        member = members_by_name.get(name)
        if member is None:
            continue
        active = bool(member.get("active", False))
        publisher = bool(member.get("publisher", False))
        result = articles.update_many(
            {
                "author": name,
                "$or": [
                    {"author_active": {"$ne": active}},
                    {"author_publisher": {"$ne": publisher}},
                    {"author_active": {"$exists": False}},
                    {"author_publisher": {"$exists": False}},
                ],
            },
            {"$set": {"author_active": active, "author_publisher": publisher}},
        )
        changed += result.modified_count
        comment_result = comments.update_many(
            {
                "author": name,
                "$or": [
                    {"author_active": {"$ne": active}},
                    {"author_active": {"$exists": False}},
                ],
            },
            {"$set": {"author_active": active}},
        )
        changed += comment_result.modified_count
    if changed:
        _logger.info("resynced author visibility snapshots on %d rows", changed)


def run_backfills(connection: Any) -> None:
    """Run every idempotent startup backfill (tech-req §5.7)."""
    backfill_articles(connection)
    backfill_first_admin(connection)
    backfill_sole_admin_publisher(connection)
    backfill_author_snapshots(connection)
    ensure_content_version(connection)


class Database:
    """The DB executor facade; every repository call routes through ``run()``."""

    def __init__(self, config: DatabaseConfig) -> None:
        self._config = config
        self._executor: ThreadPoolExecutor | None = None
        self._connection: neosqlite.Connection | None = None
        self._start_lock = asyncio.Lock()
        self._active_tokenizer: str | None = None

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
                ensure_indexes(connection, tokenizer=self._active_tokenizer)
                run_backfills(connection)

            await self.run(initialize)

    async def close(self) -> None:
        """Close the connection and stop the executor (idempotent)."""
        async with self._start_lock:
            self._active_tokenizer = None
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
    def active_tokenizer(self) -> str | None:
        """The active FTS5 tokenizer name, or None if using default (spec §12.2)."""
        return self._active_tokenizer

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
        self._active_tokenizer = None
        if tokenizer and library:
            candidates = _tokenizer_library_candidates(library)
            last_error: Exception | None = None
            for candidate in candidates:
                try:
                    conn = neosqlite.Connection(
                        path, tokenizers=[(tokenizer, candidate)]
                    )
                    self._active_tokenizer = tokenizer
                    if candidate != library:
                        _logger.info(
                            "loaded tokenizer %r from fallback %s (requested %s)",
                            tokenizer,
                            candidate,
                            library,
                        )
                    return conn
                except sqlite3.OperationalError as error:
                    last_error = error
                    continue
            _logger.warning(
                "tokenizer %r (%s) could not be loaded (%s); "
                "continuing with the default tokenizer (spec §12.2)",
                tokenizer,
                library,
                last_error,
            )
        elif tokenizer or library:
            _logger.warning(
                "tokenizer and tokenizer_library must both be set; "
                "ignoring the half-configured tokenizer (spec §12.2)"
            )
        return neosqlite.Connection(path)
