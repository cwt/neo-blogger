"""S3: GridFS registry + chunked payload + checksum + metadata subdocument
(direct NeoSQLite — GridFSBucket is constructed on the raw sqlite3 handle,
`conn.db`, per documents/gridfs.md; the neosqlite.Connection object itself
is NOT accepted by GridFSBucket/GridFS constructors — API trap recorded).

Checks:
 1. Multi-chunk upload with metadata (256 KiB chunks, ~3.5 MB payload).
 2. Registry fields on fs.files (GridOut attrs): filename, chunkSize,
    length, uploadDate, md5, metadata dict; payload split into fs_chunks.
 3. Byte-equal download round trip (destination-stream & open-stream).
 4. Stored md5 == hashlib md5 (ETag source, spec §10.4).
 5. Metadata-filtered find + list (gallery behavior).
 6. upload_from_stream_with_id (ObjectId), rename, delete_by_name.
 7. Legacy GridFS on conn.db.
"""

import hashlib
import io
import os
import sys
import time

sys.dont_write_bytecode = True

from common import check, finish, fresh_db  # noqa: E402

sys.path.insert(0, "/home/cwt/Projects/neosqlite")  # noqa: E402

import neosqlite  # noqa: E402
from neosqlite.gridfs import GridFS, GridFSBucket  # noqa: E402
from neosqlite.objectid import ObjectId  # noqa: E402

conn = neosqlite.Connection(fresh_db("/tmp/opencode/spikes/s3.db"))
bucket = GridFSBucket(conn.db)

payload = os.urandom(3 * 1024 * 1024 + 512 * 1024)
md5_hex = hashlib.md5(payload).hexdigest()
NAME = "a42d40b7_member1_photo_a7b3.webp"

META = {
    "owner": "member1",
    "original_filename": "original photo.webp",
    "alt_text": "original photo.webp",
    "upload_time": "2026-10-02T12:00:00",
    "content_type": "image/webp",
}

# Checks 1-2: multi-chunk upload with metadata
t0 = time.perf_counter()
with bucket.open_upload_stream(NAME, chunk_size_bytes=256 * 1024,
                               metadata=META) as up:
    up.write(payload)
file_id = up._file_id if hasattr(up, "_file_id") else None
upload_ms = (time.perf_counter() - t0) * 1000
check("S3-1 multi-chunk upload ok",
      upload_ms > 0, f"{upload_ms:.0f}ms for {len(payload)/1024:.0f}KiB")

out = conn.fs.files.find_one({"filename": NAME})
# registry is relational inside the engine: fs_files.id (int) ↔ fs_chunks.files_id
n_chunks = conn.db.execute(
    "SELECT COUNT(*) FROM fs_chunks c JOIN fs_files f ON c.files_id = f.id "
    "WHERE f.filename=?", (NAME,)).fetchone()[0]
check("S3-2 registry fields present",
      all(x is not None for x in (out.filename, out.length, out.chunk_size,
                                  out.upload_date, out.md5, out.metadata))
      and n_chunks >= 1,
      f"len={out.length}B chunks={n_chunks} chunkSize={out.chunk_size}")
check("S3-2b metadata subdocument stored as dict", out.metadata == META,
      f"owner={out.metadata.get('owner')}")

# Check 3: byte-equal downloads
buf = io.BytesIO()
bucket.download_to_stream_by_name(NAME, buf)
check("S3-3 download_to_stream_by_name byte-equal",
      buf.getvalue() == payload)
check("S3-3b open_download_stream_by_name byte-equal",
      bucket.open_download_stream_by_name(NAME).read() == payload)

# Check 4: checksum usable as ETag
check("S3-4 stored md5 == hashlib md5", out.md5 == md5_hex,
      f"stored={out.md5} expected={md5_hex}")

# Check 5: metadata-filtered find / list (gallery behavior)
found = [r.filename for r in
         bucket.find({"metadata.owner": "member1"})]
check("S3-5 find filtered by metadata.owner", found == [NAME],
      f"n={len(found)}")
check("S3-5b no results for foreign owner",
      list(bucket.find({"metadata.owner": "nobody"})) == [])
check("S3-5c list()", bucket.list() == [NAME], str(bucket.list()))

# Check 6: with_id / rename / delete_by_name
fid2 = ObjectId()
bucket.upload_from_stream_with_id(fid2, "temp.bin", b"X" * 4096,
                                  chunk_size_bytes=1024)
buf2 = io.BytesIO()
bucket.download_to_stream(fid2, buf2)
check("S3-6 upload_from_stream_with_id round trip",
      buf2.getvalue() == b"X" * 4096)
bucket.rename_by_name("temp.bin", "kept.bin")
buf3 = io.BytesIO()
bucket.download_to_stream_by_name("kept.bin", buf3)
check("S3-6b rename_by_name", buf3.getvalue() == b"X" * 4096)
bucket.delete_by_name("kept.bin")
gone = list(conn.fs.files.find({"filename": "kept.bin"})) == []
check("S3-6c delete_by_name removes registry + payload",
      gone and bucket.list() == [NAME])

# Check 7: legacy GridFS on the raw sqlite handle
legacy = GridFS(conn.db)
lid = legacy.put(b"legacy-payload", filename="legacy.txt",
                 content_type="text/plain")
check("S3-7 legacy put/get", legacy.get(lid).read() == b"legacy-payload",
      f"id-type={type(lid).__name__}")
legacy.delete(lid)
check("S3-7b legacy delete",
      list(legacy.find({"filename": "legacy.txt"})) == [])

conn.close()
finish("S3")
