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
from .documents import ArticleDocument, CommentDocument, normalized_document

__all__ = ["ArticleRepository"]


_ARTICLE_BOOLEANS = ("author_active", "author_publisher")


def _normalize(document: dict[str, Any]) -> ArticleDocument:
    return cast(ArticleDocument, normalized_document(document, _ARTICLE_BOOLEANS))


_MAX_SEARCH_CANDIDATES = 500


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
        author_active: bool | None = None,
        author_publisher: bool | None = None,
    ) -> None:
        """Author-controlled fields only; author and created are immutable.

        Snapshot flags refresh only when explicitly given, so edits can
        resync visibility state without unrelated writes touching it.
        """

        def update_document() -> None:
            fields: dict[str, object] = {
                "title": title,
                "subtitle": subtitle,
                "body": body,
                "cover_url": cover_url,
                "tags": tags,
                "status": status,
            }
            if author_active is not None:
                fields["author_active"] = author_active
            if author_publisher is not None:
                fields["author_publisher"] = author_publisher
            self._database.connection.articles.update_one(
                {"_id": article_id},
                {"$set": fields},
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

    async def page_data(
        self, article_id: str, viewer_is_admin: bool
    ) -> tuple[ArticleDocument | None, list[CommentDocument]]:
        """Article plus visible comments in one executor hop (bugs/015)."""

        def read() -> tuple[ArticleDocument | None, list[CommentDocument]]:
            connection = self._database.connection
            document = connection.articles.find_one({"_id": article_id})
            article = _normalize(document) if document is not None else None
            if article is None:
                return None, []
            if viewer_is_admin:
                comment_filter: dict[str, object] = {"article_id": article_id}
            else:
                comment_filter = {
                    "article_id": article_id,
                    "author_active": True,
                }
            cursor = connection.comments.find(comment_filter)
            try:
                rows = list(cursor.sort([("created", DESCENDING)]))
            except Exception:
                rows = list(cursor)
            comments = [
                cast(CommentDocument, normalized_document(row, ("author_active",)))
                for row in rows
            ]
            return article, comments

        return await self._database.run(read)

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
                            {"$project": {"body": 0}},
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
            cursor = self._database.connection.articles.find(
                {"author": author}, {"body": 0}
            )
            documents = list(cursor.sort([("created", DESCENDING)]))
            return [_normalize(document) for document in documents]

        return await self._database.run(read)

    async def author_profile_posts(
        self, author: str, limit: int = 5
    ) -> tuple[list[ArticleDocument], list[ArticleDocument]]:
        """Drafts plus recent published posts without bodies (bugs/013)."""

        def read() -> tuple[list[ArticleDocument], list[ArticleDocument]]:
            pipeline = [
                {"$match": {"author": author}},
                {"$sort": {"created": -1}},
                {
                    "$facet": {
                        "drafts": [
                            {"$match": {"status": "draft"}},
                            {"$project": {"body": 0}},
                        ],
                        "published": [
                            {"$match": {"status": "published"}},
                            {"$limit": limit},
                            {"$project": {"body": 0}},
                        ],
                    }
                },
            ]
            facet = next(
                iter(self._database.connection.articles.aggregate(pipeline).to_list())
            )
            drafts = [_normalize(d) for d in facet.get("drafts", [])]
            published = [_normalize(d) for d in facet.get("published", [])]
            return drafts, published

        return await self._database.run(read)

    async def sitemap_entries(self, page: int, per_page: int) -> list[dict[str, Any]]:
        """Only _id and created for sitemap (bugs/013)."""

        def read() -> list[dict[str, Any]]:
            pipeline = [
                {
                    "$match": {
                        "status": "published",
                        "author_active": True,
                        "author_publisher": True,
                    }
                },
                {"$sort": {"created": -1}},
                {"$skip": (page - 1) * per_page},
                {"$limit": per_page},
                {"$project": {"created": 1}},
            ]
            return list(
                self._database.connection.articles.aggregate(pipeline).to_list()
            )

        return await self._database.run(read)

    async def search(
        self, query_filter: dict[str, Any], term: str, page: int, per_page: int
    ) -> tuple[list[ArticleDocument], int]:
        """FTS relevance search: engine visibility filter, then ``bm25`` rank
        order, paginated (spec §9)."""

        def read() -> tuple[list[ArticleDocument], int]:
            connection = self._database.connection
            query = dict(query_filter)
            if "$text" not in query:
                query["$text"] = {"$search": term}
            start = (page - 1) * per_page
            try:
                total = connection.articles.count_documents(query)
            except Exception:
                total = 0
            cursor = (
                connection.articles.find(query, {"body": 0})
                .sort([("score", {"$meta": "textScore"})])
                .skip(start)
                .limit(per_page)
            )
            window = list(cursor)
            if total == 0 and window:
                total = start + len(window)
            return [_normalize(document) for document in window], total

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

    async def covers_using_image(
        self, object_id: str, variants: list[str]
    ) -> list[ArticleDocument]:
        """Articles referencing this image object via relative variants or
        absolute URLs.
        """

        def read() -> list[ArticleDocument]:
            pattern = f"/images/{re.escape(object_id)}\\."
            cursor = self._database.connection.articles.find(
                {
                    "$or": [
                        {"cover_url": {"$in": variants}},
                        {"cover_url": {"$regex": pattern}},
                    ]
                }
            )
            return [_normalize(document) for document in cursor]

        return await self._database.run(read)

    async def rebuild_search_indexes(self) -> None:
        """Drop and recreate the three per-field FTS indexes (spec §11.4).

        Required after tokenizer changes, because existing entries must be
        regenerated under the new segmentation rules.
        """

        def rebuild() -> None:
            articles = self._database.connection.articles
            tokenizer = self._database.active_tokenizer
            for field in ("title", "subtitle", "body"):
                articles.drop_search_index(field)
                articles.create_search_index(field, tokenizer=tokenizer)

        await self._database.run(rebuild)

    async def unpublished_review(self) -> list[ArticleDocument]:
        """All articles by non-publisher members, newest first (§11.3)."""

        def read() -> list[ArticleDocument]:
            cursor = self._database.connection.articles.find(
                {"author_publisher": False}, {"body": 0}
            )
            documents = list(cursor.sort([("created", DESCENDING)]))
            return [_normalize(document) for document in documents]

        return await self._database.run(read)

    async def count_by_status(self) -> dict[str, int]:
        """Published and draft totals in one pipeline (dashboard, S2-4)."""

        def read() -> dict[str, int]:
            pipeline = _status_facet_pipeline()
            facet = next(
                iter(self._database.connection.articles.aggregate(pipeline).to_list())
            )
            return _counts_from_facet(facet)

        return await self._database.run(read)

    async def count_by_author(self, author: str) -> dict[str, int]:
        """An author's published and draft totals in one pipeline (§4.5)."""

        def read() -> dict[str, int]:
            pipeline = _status_facet_pipeline({"author": author})
            facet = next(
                iter(self._database.connection.articles.aggregate(pipeline).to_list())
            )
            return _counts_from_facet(facet)

        return await self._database.run(read)


def _status_facet_pipeline(
    extra_match: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Shared published/draft $facet pipeline (bugs/023)."""
    stages: list[dict[str, Any]] = []
    if extra_match is not None:
        stages.append({"$match": extra_match})
    stages.append(
        {
            "$facet": {
                "published": [{"$match": {"status": "published"}}, {"$count": "n"}],
                "draft": [{"$match": {"status": "draft"}}, {"$count": "n"}],
            }
        }
    )
    return stages


def _counts_from_facet(facet: dict[str, Any]) -> dict[str, int]:
    return {
        "published": int(facet["published"][0]["n"]) if facet["published"] else 0,
        "draft": int(facet["draft"][0]["n"]) if facet["draft"] else 0,
    }


def _escape_regex(term: str) -> str:
    """Escape a user term for literal regex matching."""
    return re.escape(term)
