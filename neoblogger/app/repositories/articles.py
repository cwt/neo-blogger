"""Article collection access: CRUD, feed pipeline, search, related tags
(spec §12.1, tech-req §5.3).

Feed/listing read paths run in one round trip via ``$facet`` pipelines;
search ranks by FTS5 ``bm25`` relevance over the three per-field indexes
(spec §9); a case-insensitive substring path covers FTS unavailability.
"""

import re
from typing import Any, cast

from neosqlite import DESCENDING

from .db import Database
from .documents import ArticleDocument, document_id

__all__ = ["ArticleRepository", "rank_by_relevance"]


def rank_by_relevance(connection: Any, hex_ids: list[str], term: str) -> list[str]:
    """Order hex ids by summed FTS5 ``bm25`` relevance (lower is better).

    Each per-field index contributes its own ``bm25`` score; documents are
    grouped and ranked best-first. Runs on the raw sqlite handle (same
    sanctioned pattern as the GridFS buckets, §5.5).
    """
    placeholders = ", ".join("?" for _ in hex_ids)
    sql = (
        "SELECT a._id FROM articles a JOIN ("
        " SELECT rowid AS rid, bm25(articles_title_fts) AS s"
        " FROM articles_title_fts WHERE title MATCH ?"
        " UNION ALL"
        " SELECT rowid, bm25(articles_subtitle_fts)"
        " FROM articles_subtitle_fts WHERE subtitle MATCH ?"
        " UNION ALL"
        " SELECT rowid, bm25(articles_body_fts)"
        " FROM articles_body_fts WHERE body MATCH ?"
        f") f ON f.rid = a.id WHERE a._id IN ({placeholders})"
        " GROUP BY a._id ORDER BY SUM(f.s) ASC"
    )
    rows = connection.db.execute(sql, (term, term, term, *hex_ids)).fetchall()
    return [str(row[0]) for row in rows]


def _normalize(document: dict[str, Any]) -> ArticleDocument:
    return cast(ArticleDocument, dict(document))


class ArticleRepository:
    """All article reads and writes go through the DB executor facade."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(
        self,
        title: str,
        subtitle: str,
        body: str,
        cover_url: str,
        author: str,
        created: str,
        tags: list[str],
        status: str,
        *,
        author_active: bool = False,
        author_publisher: bool = False,
    ) -> str:
        def insert() -> str:
            result = self._database.connection.articles.insert_one(
                {
                    "title": title,
                    "subtitle": subtitle,
                    "body": body,
                    "cover_url": cover_url,
                    "author": author,
                    "created": created,
                    "tags": tags,
                    "status": status,
                    "author_active": author_active,
                    "author_publisher": author_publisher,
                }
            )
            return str(result.inserted_id)

        return await self._database.run(insert)

    async def delete_many(self, query_filter: dict[str, Any]) -> None:
        def remove() -> None:
            self._database.connection.articles.delete_many(query_filter)

        await self._database.run(remove)

    async def update_many_snapshots(
        self, author: str, *, author_active: bool, author_publisher: bool
    ) -> None:
        """Resync denormalized author snapshots after role changes (§11.2)."""

        def update_document() -> None:
            self._database.connection.articles.update_many(
                {"author": author},
                {
                    "$set": {
                        "author_active": author_active,
                        "author_publisher": author_publisher,
                    }
                },
            )

        await self._database.run(update_document)

    async def update(
        self,
        article_id: str,
        *,
        title: str,
        subtitle: str,
        body: str,
        cover_url: str,
        tags: list[str],
        status: str,
    ) -> None:
        """Author-controlled fields only; author and created are immutable."""

        def update_document() -> None:
            self._database.connection.articles.update_one(
                {"_id": article_id},
                {
                    "$set": {
                        "title": title,
                        "subtitle": subtitle,
                        "body": body,
                        "cover_url": cover_url,
                        "tags": tags,
                        "status": status,
                    }
                },
            )

        await self._database.run(update_document)

    async def delete(self, article_id: str) -> None:
        def remove() -> None:
            self._database.connection.articles.delete_one({"_id": article_id})

        await self._database.run(remove)

    async def by_id(self, article_id: str) -> ArticleDocument | None:
        def find() -> ArticleDocument | None:
            document = self._database.connection.articles.find_one({"_id": article_id})
            return _normalize(document) if document is not None else None

        return await self._database.run(find)

    async def feed_page(
        self, query_filter: dict[str, Any], page: int, per_page: int
    ) -> tuple[list[ArticleDocument], int]:
        """One round trip: page documents plus total (S2-1 pattern, §14)."""

        def read() -> tuple[list[ArticleDocument], int]:
            pipeline = [
                {"$match": query_filter},
                {"$sort": {"created": -1}},
                {
                    "$facet": {
                        "docs": [
                            {"$skip": (page - 1) * per_page},
                            {"$limit": per_page},
                        ],
                        "total": [{"$count": "n"}],
                    }
                },
            ]
            facet = next(
                iter(self._database.connection.articles.aggregate(pipeline).to_list())
            )
            total = int(facet["total"][0]["n"]) if facet["total"] else 0
            return [_normalize(document) for document in facet["docs"]], total

        return await self._database.run(read)

    async def for_author(self, author: str) -> list[ArticleDocument]:
        """The author's own articles (drafts and published), newest first."""

        def read() -> list[ArticleDocument]:
            cursor = self._database.connection.articles.find({"author": author})
            documents = list(cursor.sort([("created", DESCENDING)]))
            return [_normalize(document) for document in documents]

        return await self._database.run(read)

    async def search(
        self, query_filter: dict[str, Any], term: str, page: int, per_page: int
    ) -> tuple[list[ArticleDocument], int]:
        """FTS relevance search: engine visibility filter, then ``bm25`` rank
        order, paginated (spec §9)."""

        def read() -> tuple[list[ArticleDocument], int]:
            connection = self._database.connection
            cursor = connection.articles.find(query_filter)
            documents = list(cursor.sort([("created", DESCENDING)]))
            if not documents:
                return [], 0
            ordered_ids = rank_by_relevance(
                connection, [document_id(document) for document in documents], term
            )
            position = {hex_id: index for index, hex_id in enumerate(ordered_ids)}

            def rank_key(document: dict[str, Any]) -> int:
                return position.get(document_id(document), len(ordered_ids))

            ordered = sorted(documents, key=rank_key)
            start = (page - 1) * per_page
            window = ordered[start : start + per_page]
            return [_normalize(document) for document in window], len(ordered)

        return await self._database.run(read)

    async def substring_search(
        self, query_filter: dict[str, Any], term: str, page: int, per_page: int
    ) -> tuple[list[ArticleDocument], int]:
        """Case-insensitive substring fallback (spec §9); no FTS involvement."""
        escaped = _escape_regex(term)
        pattern = {"$regex": escaped, "$options": "i"}
        combined = {
            "$and": [
                query_filter,
                {"$or": [{"title": pattern}, {"subtitle": pattern}, {"body": pattern}]},
            ]
        }
        return await self.feed_page(combined, page, per_page)

    async def related_tags(
        self, tag: str, query_filter: dict[str, Any], limit: int = 10
    ) -> list[tuple[str, int]]:
        """Co-occurring tags ranked by frequency, single pipeline (spec §8, S2-3)."""

        def read() -> list[tuple[str, int]]:
            pipeline = [
                {"$match": {"$and": [query_filter, {"tags": tag}]}},
                {"$unwind": "$tags"},
                {"$match": {"tags": {"$ne": tag}}},
                {"$group": {"_id": "$tags", "n": {"$sum": 1}}},
                {"$sort": {"n": -1, "_id": 1}},
                {"$limit": limit},
            ]
            rows = list(
                self._database.connection.articles.aggregate(pipeline).to_list()
            )
            return [(str(row["_id"]), int(row["n"])) for row in rows]

        return await self._database.run(read)

    async def covers_in_use(self, cover_url: str) -> list[ArticleDocument]:
        """Articles currently using the cover (deletion guard, spec §10.5)."""

        def read() -> list[ArticleDocument]:
            cursor = self._database.connection.articles.find({"cover_url": cover_url})
            return [_normalize(document) for document in cursor]

        return await self._database.run(read)

    async def count_by_status(self) -> dict[str, int]:
        """Published and draft totals in one pipeline (dashboard, S2-4)."""

        def read() -> dict[str, int]:
            pipeline = [
                {
                    "$facet": {
                        "published": [
                            {"$match": {"status": "published"}},
                            {"$count": "n"},
                        ],
                        "draft": [{"$match": {"status": "draft"}}, {"$count": "n"}],
                    }
                }
            ]
            facet = next(
                iter(self._database.connection.articles.aggregate(pipeline).to_list())
            )
            return {
                "published": int(facet["published"][0]["n"])
                if facet["published"]
                else 0,
                "draft": int(facet["draft"][0]["n"]) if facet["draft"] else 0,
            }

        return await self._database.run(read)


def _escape_regex(term: str) -> str:
    """Escape a user term for literal regex matching."""
    return re.escape(term)
