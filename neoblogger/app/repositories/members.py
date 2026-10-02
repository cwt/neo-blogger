"""Member collection access (spec §12.1, tech-req §5.2).

Authorization flags and ``active`` are normalized to ``bool`` at the read
boundary; ``_id`` is normalized to its hex string (§5.1 policies).
"""

import sqlite3
from typing import Any, cast

from .db import Database
from .documents import MemberDocument, normalized_document

__all__ = ["MemberAlreadyExistsError", "MemberRepository"]

_MEMBER_BOOLEANS = ("active", "administrator", "publisher")


class MemberAlreadyExistsError(Exception):
    """Raised when a unique constraint on display name or email trips."""


def _normalize(document: dict[str, Any]) -> MemberDocument:
    normalized = normalized_document(document, _MEMBER_BOOLEANS)
    return cast(MemberDocument, normalized)


class MemberRepository:
    """All member reads and writes go through the DB executor facade."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(
        self,
        display_name: str,
        email: str,
        password_hash: str,
        security_question_code: str,
        security_answer_hash: str,
        *,
        administrator: bool = False,
        publisher: bool = False,
    ) -> str:
        """Insert a member; hex-string ``_id`` is returned (spec §4.1)."""

        def insert() -> str:
            result = self._database.connection.members.insert_one(
                {
                    "display_name": display_name,
                    "email": email,
                    "password_hash": password_hash,
                    "security_question_code": security_question_code,
                    "security_answer_hash": security_answer_hash,
                    "active": True,
                    "administrator": administrator,
                    "publisher": publisher,
                }
            )
            return str(result.inserted_id)

        try:
            return await self._database.run(insert)
        except sqlite3.IntegrityError as error:
            raise MemberAlreadyExistsError(str(error)) from error

    async def by_id(self, member_id: str) -> MemberDocument | None:
        def find() -> MemberDocument | None:
            document = self._database.connection.members.find_one({"_id": member_id})
            return _normalize(document) if document is not None else None

        return await self._database.run(find)

    async def by_display_name(self, display_name: str) -> MemberDocument | None:
        def find() -> MemberDocument | None:
            document = self._database.connection.members.find_one(
                {"display_name": display_name}
            )
            return _normalize(document) if document is not None else None

        return await self._database.run(find)

    async def by_email(self, email: str) -> MemberDocument | None:
        def find() -> MemberDocument | None:
            document = self._database.connection.members.find_one({"email": email})
            return _normalize(document) if document is not None else None

        return await self._database.run(find)

    async def exists_any(self) -> bool:
        def count() -> bool:
            return int(self._database.connection.members.count_documents({})) > 0

        return await self._database.run(count)

    async def all(self) -> list[MemberDocument]:
        """Every member, newest first (admin panel §11.2)."""

        def read() -> list[MemberDocument]:
            cursor = self._database.connection.members.find({})
            documents = list(cursor.sort([("$natural", -1)]))
            return [_normalize(document) for document in documents]

        return await self._database.run(read)

    async def set_flag(self, member_id: str, field: str, value: bool) -> None:
        """Toggle one of ``active``/``administrator``/``publisher`` (§11.2)."""
        if field not in _MEMBER_BOOLEANS:
            raise ValueError(f"not a member flag: {field}")

        def update() -> None:
            self._database.connection.members.update_one(
                {"_id": member_id}, {"$set": {field: value}}
            )

        await self._database.run(update)

    async def set_active(self, member_id: str, active: bool) -> None:
        await self.set_flag(member_id, "active", active)

    async def set_administrator(self, member_id: str, administrator: bool) -> None:
        await self.set_flag(member_id, "administrator", administrator)

    async def set_publisher(self, member_id: str, publisher: bool) -> None:
        await self.set_flag(member_id, "publisher", publisher)

    async def update_credentials(
        self,
        member_id: str,
        *,
        email: str,
        password_hash: str,
        security_question_code: str,
        security_answer_hash: str,
    ) -> None:
        """Rotate credentials; display name is immutable (spec §4.6, D1)."""

        def update() -> None:
            self._database.connection.members.update_one(
                {"_id": member_id},
                {
                    "$set": {
                        "email": email,
                        "password_hash": password_hash,
                        "security_question_code": security_question_code,
                        "security_answer_hash": security_answer_hash,
                    }
                },
            )

        await self._database.run(update)
