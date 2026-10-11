"""Named metadata values and the cache-version counter (tech-req §5.2)."""

from .db import Database

__all__ = ["MetaRepository"]


class MetaRepository:
    """Reads and bumps ``meta`` documents; single-threaded executor makes
    read-modify-write cycles atomic."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def content_version(self) -> int:
        """The current global content version (spec §14); 0 when absent."""

        def read() -> int:
            document = self._database.connection.meta.find_one(
                {"name": "content_version"}
            )
            if document is None:
                return 0
            return int(document["value"])

        return await self._database.run(read)

    async def bump_content_version(self) -> int:
        """Advance the version and return it; callers invalidate on this.

        Self-healing: a missing counter row is inserted rather than
        updated in place, so a wiped ``meta`` collection recovers instead
        of drifting.
        """

        def bump() -> int:
            meta = self._database.connection.meta
            document = meta.find_one({"name": "content_version"})
            if document is None:
                meta.insert_one({"name": "content_version", "value": 1})
                return 1
            updated = int(document["value"]) + 1
            meta.update_one({"name": "content_version"}, {"$set": {"value": updated}})
            return updated

        return await self._database.run(bump)
