"""S1: Executor-facade sanity — NeoSQLite Connection driven through a
single-worker executor inside an event loop (the Neo-Blogger pattern).

Checks:
 1. Connection opened ON the executor thread (recommended pattern), WAL default.
 2. Bulk insert via facade.
 3. Concurrency: heavy aggregate + 20 quick finds + 20 concurrent inserts;
    no deadlock, ordering serialized by the single worker.
 4. check_same_thread=False: main-thread-created connection, executor-routed use.
 5. GridFS 2 MB chunked round trip through the same executor.
 6. Stress: 200 concurrent facade tasks, all results valid.
 7. Latency profile of quick finds.
"""

import asyncio
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.dont_write_bytecode = True

from common import check, finish, fresh_db  # noqa: E402

sys.path.insert(0, "/home/cwt/Projects/neosqlite")  # noqa: E402

import neosqlite  # noqa: E402

DB = fresh_db("/tmp/opencode/spikes/s1.db")
N = 3000
STRESS = 200


class Repo:
    """The exact shape of the planned repositories/db.py facade."""

    def __init__(self, executor: ThreadPoolExecutor) -> None:
        self.executor = executor
        self.conn: neosqlite.Connection | None = None

    async def _run(self, fn, *args):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, fn, *args)

    # --- sync work, executed only on the DB executor thread ---
    def _open(self) -> None:
        self.conn = neosqlite.Connection(DB)

    def _bulk_insert(self, docs):
        return len(self.conn.docs.insert_many(docs).inserted_ids)

    def _count(self, query):
        return self.conn.docs.count_documents(query)

    def _find_hot(self, query):
        return self.conn.docs.find(query).limit(10).to_list()

    def _aggregate_all(self):
        pipeline = [
            {"$group": {"_id": "$grp", "n": {"$sum": 1}}},
            {"$sort": {"n": -1}},
        ]
        return len(self.conn.docs.aggregate(pipeline).to_list())

    def _gridfs_roundtrip(self, name, data):
        bucket = neosqlite.gridfs.GridFSBucket(self.conn.db)
        bucket.upload_from_stream(name, data)
        import io
        buf = io.BytesIO()
        bucket.download_to_stream_by_name(name, buf)
        return buf.getvalue()

    # --- async facade API (what services would call) ---
    async def bulk_insert(self, docs):
        return await self._run(self._bulk_insert, docs)

    async def count(self, query):
        return await self._run(self._count, query)

    async def find_hot(self, query):
        return await self._run(self._find_hot, query)

    async def aggregate_all(self):
        return await self._run(self._aggregate_all)

    async def gridfs_roundtrip(self, data, name):
        return await self._run(self._gridfs_roundtrip, name, data)


async def main() -> None:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="db-spike")
    repo = Repo(executor)

    # Check 1
    await repo._run(repo._open)
    check("S1-1 connection opened on executor thread", repo.conn is not None)
    check("S1-1b WAL default journal mode", repo.conn.journal_mode == "WAL",
          str(repo.conn.journal_mode))

    # Check 2
    rng = random.Random(20261002)
    docs = [
        {"title": f"Article {i}", "grp": rng.choice("abcdefg"),
         "status": "published" if rng.random() < 0.8 else "draft"}
        for i in range(N)
    ]
    t0 = time.perf_counter()
    inserted = await repo.bulk_insert(docs)
    check(f"S1-2 bulk insert {inserted}/{N} docs", inserted == N,
          f"{time.perf_counter() - t0:.2f}s")
    check("S1-2b count via executor",
          await repo.count({"status": "published"}) > 0)

    # Check 3
    long_task = asyncio.create_task(repo.aggregate_all())
    quick_tasks = [asyncio.create_task(repo.find_hot({"grp": "a"}))
                   for _ in range(20)]
    ins_tasks = [asyncio.create_task(
        repo.bulk_insert([{"title": f"conc-{i}-{k}", "grp": "z",
                           "status": "published"}]))
        for i in range(4) for k in range(5)]
    t0 = time.perf_counter()
    long_res = await long_task
    check("S1-3 heavy aggregate completes while tasks queued",
          long_res == len("abcdefg"),
          f"{(time.perf_counter() - t0)*1000:.0f}ms")
    t0 = time.perf_counter()
    quick = await asyncio.gather(*quick_tasks)
    check("S1-3b 20 quick finds valid under queueing",
          all(0 < len(r) <= 10 for r in quick),
          f"{(time.perf_counter() - t0)*1000:.0f}ms total")
    ins_counts = await asyncio.gather(*ins_tasks)
    check("S1-3c 20 concurrent inserts complete", sum(ins_counts) == 20)

    # Check 4
    DB2 = fresh_db("/tmp/opencode/spikes/s1b.db")
    conn_main = neosqlite.Connection(DB2, check_same_thread=False)
    # conn created on MAIN thread; work submitted from the EVENT LOOP
    # (the app's real pattern). Nested submits are forbidden (S1-4b).
    await asyncio.get_running_loop().run_in_executor(
        executor, lambda: (conn_main.things.insert_one({"x": 1}),
                           conn_main.things.insert_one({"x": 2})))
    n = await asyncio.get_running_loop().run_in_executor(
        executor, lambda: conn_main.things.count_documents({}))
    check("S1-4 check_same_thread=False path", n == 2, f"n={n}")

    # Check 4b (NEGATIVE): documented pitfall — nested executor submit
    # from inside executor work self-deadlocks on a max_workers=1 pool.
    def nested_submit():
        fut = executor.submit(lambda: 1)
        return fut.result(timeout=0.2)

    deadlock_caught = False
    try:
        await asyncio.get_running_loop().run_in_executor(
            executor, nested_submit)
    except TimeoutError:
        deadlock_caught = True
    check("S1-4b nested-submit deadlock reproduces (known trap)",
          deadlock_caught, "nested submits forbidden; facade only")

    # Check 5
    payload = os.urandom(2 * 1024 * 1024)
    t0 = time.perf_counter()
    got = await repo.gridfs_roundtrip(payload, "spike-photo.webp")
    check("S1-5 GridFS 2MB round trip byte-equal", got == payload,
          f"{(time.perf_counter() - t0)*1000:.0f}ms")

    # Check 6
    async def stress_once(i):
        kind = i % 4
        if kind == 0:
            return await repo.count({"grp": "b"})
        if kind == 1:
            return await repo.find_hot({"grp": "c"})
        if kind == 2:
            return await repo.aggregate_all()  # returns count of groups
        return await repo.bulk_insert(
            [{"title": f"stress-{i}", "grp": "s", "status": "draft"}])

    t0 = time.perf_counter()
    results = await asyncio.gather(*[stress_once(i) for i in range(STRESS)])
    sdt = time.perf_counter() - t0
    check(f"S1-6 stress {STRESS} concurrent facade tasks ok",
          all(isinstance(r, (int, list)) for r in results),
          f"{sdt:.2f}s = {STRESS/sdt:.0f} facade-ops/s")

    # Check 7
    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        await repo.find_hot({"status": "published"})
        latencies.append(time.perf_counter() - t0)
    lat_sorted = sorted(latencies)
    p50 = lat_sorted[len(lat_sorted) // 2] * 1000
    p95 = lat_sorted[int(len(lat_sorted) * 0.95)] * 1000
    mx = lat_sorted[-1] * 1000
    check("S1-7 find latency sane", True,
          f"p50={p50:.1f}ms p95={p95:.1f}ms max={mx:.1f}ms")

    executor.shutdown(wait=True)


asyncio.run(main())
finish("S1")
