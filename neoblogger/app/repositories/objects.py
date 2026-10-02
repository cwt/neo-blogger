"""Uploaded-image object store (spec §10, tech-req §5.5, Spike S3).

Storage is the engine's GridFS: a registry (``fs_files``) plus chunked
payloads (``fs_chunks``). The bucket is constructed on the raw sqlite
handle — the ``Connection`` object itself is not accepted (S3 API trap).
Registry metadata: owner, original filename, alt text, upload time,
content type (spec §10.2).
"""

import io
import json
from typing import Any

from neosqlite.gridfs import GridFSBucket
from neosqlite.objectid import ObjectId

from .db import Database

__all__ = ["ObjectRepository"]

CHUNK_SIZE_BYTES = 256 * 1024


class ObjectRepository:
    """GridFS access through the DB executor facade."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def _bucket(self) -> GridFSBucket:
        """The bucket on the raw sqlite handle (S3 API trap, §5.5)."""
        return GridFSBucket(self._database.connection.db)

    async def upload(
        self,
        filename: str,
        payload: bytes,
        metadata: dict[str, str],
    ) -> str:
        """Upload with registry metadata; hex-string id is returned."""

        def insert() -> str:
            object_id = ObjectId()
            self._bucket().upload_from_stream_with_id(
                object_id,
                filename,
                payload,
                chunk_size_bytes=CHUNK_SIZE_BYTES,
                metadata=metadata,
            )
            return str(object_id)

        return await self._database.run(insert)

    async def data(self, object_id: str) -> bytes | None:
        """Download the payload by hex-string id; ``None`` when missing."""

        def read() -> bytes | None:
            document = self._database.connection.fs.files.find_one({"_id": object_id})
            if document is None:
                return None
            buffer = io.BytesIO()
            self._bucket().download_to_stream(object_id, buffer)
            return buffer.getvalue()

        return await self._database.run(read)

    async def metadata(self, object_id: str) -> dict[str, Any] | None:
        """Registry metadata plus length and checksum (ETag source, §10.4)."""

        def read() -> dict[str, Any] | None:
            document = self._database.connection.fs.files.find_one({"_id": object_id})
            if document is None:
                return None
            return {
                "filename": str(document.filename),
                "length": int(document.length),
                "md5": str(document.md5),
                "metadata": dict(document.metadata),
            }

        return await self._database.run(read)

    async def update_alt_text(self, object_id: str, alt_text: str) -> None:
        """Update only the alt-text metadata field (spec §10.3)."""

        def update() -> None:
            self._database.connection.fs.files.update_one(
                {"_id": object_id}, {"$set": {"metadata.alt_text": alt_text}}
            )

        await self._database.run(update)

    async def delete(self, object_id: str) -> None:
        """Remove registry entry and payload (§10.5)."""

        def remove() -> None:
            self._bucket().delete(object_id)

        await self._database.run(remove)

    async def list_for(
        self, owner: str | None, page: int, per_page: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Gallery listing, newest first (§10.3).

        The ``fs_files`` registry is relational (no ``data`` column), so
        aggregation and count are engine-unsupported there; listing and
        counting run as raw SQL with ``json_extract`` over the metadata
        JSON text (verified probe, 2026-10-02).
        """

        def read() -> tuple[list[dict[str, Any]], int]:
            connection = self._database.connection
            present = connection.db.execute(
                "SELECT COUNT(*) FROM sqlite_master"
                " WHERE type='table' AND name='fs_files'"
            ).fetchone()[0]
            if not present:
                return [], 0
            where = "WHERE json_extract(metadata, '$.owner') = ?" if owner else ""
            parameters: list[object] = [owner] if owner else []
            count = int(
                connection.db.execute(
                    f"SELECT COUNT(*) FROM fs_files {where}", parameters
                ).fetchone()[0]
            )
            rows = connection.db.execute(
                "SELECT _id, filename, metadata FROM fs_files "
                f"{where} ORDER BY uploadDate DESC LIMIT ? OFFSET ?",
                [*parameters, per_page, (page - 1) * per_page],
            ).fetchall()
            listing = [
                {
                    "id": str(row[0]),
                    "filename": str(row[1]),
                    "metadata": dict(json.loads(str(row[2]))),
                }
                for row in rows
            ]
            return listing, count

        return await self._database.run(read)
