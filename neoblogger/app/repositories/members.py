"""Member collection access (spec §12.1, tech-req §5.2).

Authorization flags and ``active`` are normalized to ``bool`` at the read
boundary; ``_id`` is normalized to its hex string (§5.1 policies).
"""

import sqlite3
from typing import Any, Literal, cast

from neosqlite import DESCENDING

from .db import Database
from .documents import MemberDocument, normalized_document

__all__ = ["MemberAlreadyExistsError", "MemberRepository"]

_MEMBER_BOOLEANS = ("active", "administrator", "publisher")


class MemberAlreadyExistsError(Exception):
    """Raised when a unique constraint on display name or email trips."""


def _normalize(document: dict[str, Any]) -> MemberDocument:
    normalized = normalized_document(document, _MEMBER_BOOLEANS)
    normalized["session_version"] = int(normalized.get("session_version", 1))
    return cast(MemberDocument, normalized)


class MemberRepository:
    """All member reads and writes go through the DB executor facade."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_first_or_member(
        self,
        display_name: str,
        email: str,
        password_hash: str,
        security_question_code: str,
        security_answer_hash: str,
    ) -> tuple[str, bool]:
        """Insert a member, promoting the first one (spec §2).

        The uniqueness and first-member checks run inside the same
        executor work unit as the insert, so the cycle is atomic.
        """

        def insert() -> tuple[str, bool]:
            members = self._database.connection.members
            if members.find_one({"email": email}) is not None:
                raise MemberAlreadyExistsError("email already registered")
            if members.find_one({"display_name": display_name}) is not None:
                raise MemberAlreadyExistsError("display name already registered")
            promoted = int(members.count_documents({})) == 0
            result = members.insert_one(
                {
                    "display_name": display_name,
                    "email": email,
                    "password_hash": password_hash,
                    "security_question_code": security_question_code,
                    "security_answer_hash": security_answer_hash,
                    "active": True,
                    "administrator": promoted,
                    "publisher": promoted,
                    "session_version": 1,
                }
            )
            hex_id = str(result.inserted_id)
            if promoted:
                earliest = list(members.find({}).sort([("_id", 1)]).limit(1))
                if earliest and str(earliest[0]["_id"]) != hex_id:
                    members.update_one(
                        {"_id": hex_id},
                        {"$set": {"administrator": False, "publisher": False}},
                    )
                    promoted = False
            return hex_id, promoted

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

    async def dashboard(self) -> dict[str, int]:
        """Member statistics in one round trip (spec §11.1)."""

        def read() -> dict[str, int]:
            pipeline = [
                {
                    "$facet": {
                        "total": [{"$count": "n"}],
                        "active": [{"$match": {"active": True}}, {"$count": "n"}],
                        "admins": [
                            {"$match": {"administrator": True}},
                            {"$count": "n"},
                        ],
                        "publishers": [
                            {"$match": {"publisher": True}},
                            {"$count": "n"},
                        ],
                    }
                }
            ]
            facet = next(
                iter(self._database.connection.members.aggregate(pipeline).to_list())
            )
            return {
                name: int(facet[name][0]["n"]) if facet[name] else 0
                for name in ("total", "active", "admins", "publishers")
            }

        return await self._database.run(read)

    async def all(self) -> list[MemberDocument]:
        """Every member, newest first (admin panel §11.2).

        ObjectIds are time-ordered, so ``_id`` descending is a stable
        newest-first order; ``$natural`` storage order is not.
        """

        def read() -> list[MemberDocument]:
            cursor = self._database.connection.members.find({})
            documents = list(cursor.sort([("_id", DESCENDING)]))
            return [_normalize(document) for document in documents]

        return await self._database.run(read)

    async def set_flag(
        self,
        member_id: str,
        field: Literal["active", "administrator", "publisher"],
        value: bool,
    ) -> None:
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

    async def promote_admin(self, member_id: str) -> None:
        """Promote to administrator and publisher in a single update."""

        def update() -> None:
            self._database.connection.members.update_one(
                {"_id": member_id},
                {"$set": {"administrator": True, "publisher": True}},
            )

        await self._database.run(update)

    async def update_credentials(
        self,
        member_id: str,
        *,
        email: str,
        password_hash: str,
        security_question_code: str,
        security_answer_hash: str,
    ) -> int:
        """Rotate credentials; display name is immutable (spec §4.6, D1).

        The email-uniqueness check runs inside the same executor work unit
        as the write, so concurrent rotations cannot both win (the service
        pre-check is only an early, non-authoritative gate). Returns the
        new session_version integer.
        """

        def update() -> int:
            members = self._database.connection.members
            existing = members.find_one({"email": email})
            if existing is not None and str(existing["_id"]) != member_id:
                raise MemberAlreadyExistsError("email already registered")
            target = members.find_one({"_id": member_id})
            current_version = int(target.get("session_version", 1)) if target else 1
            new_version = current_version + 1
            members.update_one(
                {"_id": member_id},
                {
                    "$set": {
                        "email": email,
                        "password_hash": password_hash,
                        "security_question_code": security_question_code,
                        "security_answer_hash": security_answer_hash,
                        "session_version": new_version,
                    }
                },
            )
            return new_version

        return await self._database.run(update)
