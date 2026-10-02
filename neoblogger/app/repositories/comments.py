"""Comment collection access (spec §12.1, tech-req §5.2/§5.3)."""

from typing import Any, cast

from neosqlite import DESCENDING

from .db import Database
from .documents import CommentDocument

__all__ = ["CommentRepository"]


def _normalize(document: dict[str, Any]) -> CommentDocument:
    return cast(CommentDocument, dict(document))


class CommentRepository:
    """All comment reads and writes go through the DB executor facade."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(
        self, text: str, author: str, article_id: str, created: str
    ) -> str:
        """Insert a comment; linkage is a hex string (S2 ID policy)."""

        def insert() -> str:
            result = self._database.connection.comments.insert_one(
                {
                    "text": text,
                    "author": author,
                    "article_id": article_id,
                    "created": created,
                }
            )
            return str(result.inserted_id)

        return await self._database.run(insert)

    async def delete(self, comment_id: str) -> None:
        """Delete one comment (§7); the article id is not needed (D6)."""

        def remove() -> None:
            self._database.connection.comments.delete_one({"_id": comment_id})

        await self._database.run(remove)

    async def delete_for_article(self, article_id: str) -> None:
        """Cascade delete on article removal (spec §5.4)."""

        def remove() -> None:
            self._database.connection.comments.delete_many({"article_id": article_id})

        await self._database.run(remove)

    async def by_id(self, comment_id: str) -> CommentDocument | None:
        def find() -> CommentDocument | None:
            document = self._database.connection.comments.find_one({"_id": comment_id})
            return _normalize(document) if document is not None else None

        return await self._database.run(find)

    async def for_article(
        self, article_id: str, query_filter: dict[str, Any]
    ) -> list[CommentDocument]:
        """Visible comments for an article, newest first (§7).

        ``query_filter`` carries the active-member visibility policy from
        the service layer; the repository is mechanism-only.
        """
        combined = {"$and": [{"article_id": article_id}, query_filter]}

        def read() -> list[CommentDocument]:
            cursor = self._database.connection.comments.find(combined)
            documents = list(cursor.sort([("created", DESCENDING)]))
            return [_normalize(document) for document in documents]

        return await self._database.run(read)

    async def count_by_author(self, author: str) -> int:
        def count() -> int:
            return int(
                self._database.connection.comments.count_documents({"author": author})
            )

        return await self._database.run(count)
