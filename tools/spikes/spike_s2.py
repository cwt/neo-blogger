"""S2: Aggregation capabilities required by technical-requirements §5.3.

Checks:
 1. Feed page + total count in ONE round trip ($facet streaming + $count,
   with $skip/$limit inside the facet label for pagination).
 2. Article + its comments joined in one $lookup pipeline.
 3. Related tags ($match -> $unwind -> $group -> $sort -> $limit 10),
   verified against a Python-computed co-occurrence ground truth.
 4. Dashboard stats in a single $facet ($group members/content counts).
 5. Standalone $count stage.
 6. Pagination by ISO-string sort ($sort desc + $skip) vs Python ground truth.
"""

import os
import random
import sys
import time

sys.dont_write_bytecode = True

from common import check, finish, fresh_db  # noqa: E402

sys.path.insert(0, "/home/cwt/Projects/neosqlite")  # noqa: E402

import neosqlite  # noqa: E402

rng = random.Random(20261002)
ARTICLES_DB = fresh_db("/tmp/opencode/spikes/s2.db")
TAGS = ["python", "sqlite", "nosql", "asyncio", "sql", "web"]


def _base_pipeline_facet(query, page, per_page):
    return [
        {"$match": query},
        {"$sort": {"created": -1}},
        {"$facet": {
            "docs": [
                {"$skip": (page - 1) * per_page},
                {"$limit": per_page},
            ],
            "total": [{"$count": "n"}],
        }},
    ]


def _key_neg(kv):
    return (-kv[1], kv[0])


def main() -> None:
    conn = neosqlite.Connection(ARTICLES_DB)
    articles = conn.articles
    comments = conn.comments

    # --- seed ---
    now_rows = []
    for i in range(40):
        tags = rng.sample(TAGS, rng.randint(1, 4))
        article = {
            "title": f"Article {i} — {rng.choice(TAGS)} deep dive",
            "subtitle": f"subtitle {i}",
            "body": "lorem ipsum " * 50,
            "author": f"member{rng.randint(0, 7)}",
            "created": f"2026-09-{(i % 28) + 1:02d}T{rng.randint(0, 23):02d}:00:00",
            "tags": tags,
            "status": "published" if rng.random() < 0.8 else "draft",
            "checker": "published-marker",
        }
        articles.insert_one(article)
        now_rows.append(article)
    ground_pub = [a for a in now_rows if a["status"] == "published"]
    for i in range(120):
        art = rng.choice(now_rows)
        aid = articles.find_one({"title": art["title"]})["_id"]
        # data-model policy (spike finding): linkage ids stored as hex str,
        # never as ObjectId instances — equality + $lookup both work then.
        comments.insert_one({
            "text": f"nice {i}", "author": f"member{rng.randint(0, 7)}",
            "article_id": str(aid),
        })

    published_ids = {d["_id"] for d in
                     articles.find({"status": "published"}).to_list()}

    # Check 1: feed + count one round trip
    t0 = time.perf_counter()
    facet = list(articles.aggregate(
        _base_pipeline_facet({"status": "published"}, 1, 10)).to_list())[0]
    dt1 = (time.perf_counter() - t0) * 1000
    ids = {str(r["_id"]) for r in facet["docs"]}
    total = facet["total"][0]["n"] if facet["total"] else 0
    check("S2-1 feed page+total single round trip",
          len(facet["docs"]) == 10 and total == len(ground_pub)
          and ids <= {str(d["_id"]) for d in ground_pub},
          f"{dt1:.1f}ms docs={len(facet['docs'])} total={total}")
    id_shapes = {type(r["_id"]).__name__ for r in facet["docs"]}
    check("S2-1c facet _ids are hex strings (typing note)",
          id_shapes <= {"str"}, str(id_shapes))

    # pagination consistency: page 2 vs python ground truth
    pg2 = list(articles.aggregate(
        _base_pipeline_facet({"status": "published"}, 2, 10)).to_list())[0]
    py_sorted = sorted(ground_pub, key=lambda a: a["created"], reverse=True)
    expect2 = {a["title"] for a in py_sorted[10:20]}
    got2 = {r["title"] for r in pg2["docs"]}
    check("S2-1b page 2 matches ground truth", expect2 == got2,
          f"count-match={len(expect2 & got2)}")

    # Check 2: article + comments in one $lookup
    sample_pub = next(iter(published_ids))
    t0 = time.perf_counter()
    joined = list(articles.aggregate([
        {"$match": {"_id": sample_pub}},
        {"$lookup": {
            "from": "comments",
            "localField": "_id",
            "foreignField": "article_id",
            "as": "comments",
        }},
        {"$project": {"title": 1, "created": 1,
                      "n_comments": {"$size": "$comments"}}},
    ]).to_list())[0]
    n_direct = comments.count_documents({"article_id": str(sample_pub)})
    check("S2-2 article + comments one $lookup",
          joined["n_comments"] == n_direct,
          f"{(time.perf_counter() - t0)*1000:.1f}ms "
          f"n={joined['n_comments']}")

    # Check 3: related tags vs ground truth
    current = "python"
    t0 = time.perf_counter()
    rel = list(articles.aggregate([
        {"$match": {"status": "published", "tags": current}},
        {"$unwind": "$tags"},
        {"$match": {"tags": {"$ne": current}}},
        {"$group": {"_id": "$tags", "n": {"$sum": 1}}},
        {"$sort": {"n": -1, "_id": 1}},
        {"$limit": 10},
    ]).to_list())
    engine_map = {r["_id"]: r["n"] for r in rel}
    py_map: dict[str, int] = {}
    for a in ground_pub:
        if current in a["tags"]:
            for t in set(a["tags"]) - {current}:
                py_map[t] = py_map.get(t, 0) + 1
    detail = (f"{(time.perf_counter() - t0)*1000:.1f}ms "
              + str(sorted(engine_map.items(), key=_key_neg)))
    check("S2-3 related tags correct vs ground truth",
          engine_map == py_map, detail)

    # Check 4: dashboard in one $facet
    t0 = time.perf_counter()
    dash = list(articles.aggregate([
        {"$facet": {
            "published": [{"$match": {"status": "published"}},
                          {"$count": "n"}],
            "drafts": [{"$match": {"status": "draft"}}, {"$count": "n"}],
        }},
    ]).to_list())[0]
    pub_n = dash["published"][0]["n"] if dash["published"] else 0
    draft_n = dash["drafts"][0]["n"] if dash["drafts"] else 0
    check("S2-4 dashboard counts in one pipeline",
          pub_n == len(ground_pub)
          and draft_n == len(now_rows) - len(ground_pub),
          f"{(time.perf_counter() - t0)*1000:.1f}ms "
          f"pub={pub_n} draft={draft_n}")

    # Check 5: standalone $count
    c = list(articles.aggregate([
        {"$match": {"status": "published"}},
        {"$count": "n"},
    ]).to_list())[0]["n"]
    check("S2-5 $count stage", c == len(ground_pub), f"n={c}")

    # Check 6: $skip/$limit with descending ISO string sort (python truth)
    page = list(articles.aggregate(
        _base_pipeline_facet({"status": "published"}, 2, 10)
    ).to_list())[0]["docs"]
    ok_order = all(page[i]["created"] >= page[i + 1]["created"]
                   for i in range(len(page) - 1))
    check("S2-6 ISO-string sort pagination order", ok_order and len(page) == 10)

    conn.close()


main()
finish("S2")
