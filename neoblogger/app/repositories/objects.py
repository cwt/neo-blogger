"""Uploaded-image object store (spec §10, tech-req §5.5, Spike S3).

Storage is the engine's GridFS: a registry (``fs_files``) plus chunked
payloads (``fs_chunks``). Registry metadata: owner, original filename,
alt text, upload time, content type (spec §10.2).
"""

import io
from typing import Any

from neosqlite.gridfs import GridFSBucket, NoFile
from neosqlite.objectid import ObjectId

from .db import Database

__all__ = ["ObjectRepository"]

CHUNK_SIZE_BYTES = 256 * 1024

_THEME_OWNER = "theme"
"""System-banner owner excluded from admin galleries (services.theme.THEME_OWNER)."""


class ObjectRepository:
    """GridFS access through the DB executor facade."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._bucket_cached: GridFSBucket | None = None
        self._bucket_conn_id: int | None = None

    def _bucket(self) -> GridFSBucket:
        """The bucket instance on the connection, cached per connection."""
        connection = self._database.connection
        if self._bucket_cached is not None and self._bucket_conn_id == id(connection):
            return self._bucket_cached
        bucket = GridFSBucket(connection)
        self._bucket_cached = bucket
        self._bucket_conn_id = id(connection)
        return bucket

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
        """Download the payload by hex-string id; ``None`` when missing.

        A single download attempt replaces the existence probe: it halves
        the lookups and cannot race a delete between probe and fetch.
        """

        def read() -> bytes | None:
            buffer = io.BytesIO()
            try:
                self._bucket().download_to_stream(object_id, buffer)
            except NoFile:
                return None
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
        self,
        owner: str | None,
        page: int,
        per_page: int,
        exclude_owner: str | None = _THEME_OWNER,
    ) -> tuple[list[dict[str, Any]], int]:
        """Gallery listing, newest first (§10.3)."""

        def read() -> tuple[list[dict[str, Any]], int]:
            bucket = self._bucket()
            connection = self._database.connection
            if owner:
                query: dict[str, Any] = {"metadata.owner": owner}
            elif exclude_owner:
                query = {"metadata.owner": {"$ne": exclude_owner}}
            else:
                query = {}
            count = connection.fs.files.count_documents(query)
            if count == 0:
                return [], 0
            cursor = (
                bucket.find(query)
                .sort("uploadDate", -1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )
            listing = [
                {
                    "id": str(grid_out._id),
                    "filename": str(grid_out.filename),
                    "metadata": dict(grid_out.metadata or {}),
                }
                for grid_out in cursor
            ]
            return listing, count

        return await self._database.run(read)
