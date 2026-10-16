"""Repository tests: articles, comments, objects (tech-req §5)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.articles import ArticleRepository
from neoblogger.app.repositories.comments import CommentRepository
from neoblogger.app.repositories.db import Database
from neoblogger.app.repositories.objects import ObjectRepository


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(DatabaseConfig(path=str(tmp_path / "repo2.db")))
    await database.start()
    yield database
    await database.close()


@pytest.fixture
def articles(database: Database) -> ArticleRepository:
    return ArticleRepository(database)


@pytest.fixture
def comments(database: Database) -> CommentRepository:
    return CommentRepository(database)


@pytest.fixture
def objects(database: Database) -> ObjectRepository:
    return ObjectRepository(database)


def article(
    title: str, author: str, created: str, status: str, tags: list[str]
) -> dict[str, object]:
    return {
        "title": title,
        "subtitle": f"{title} subtitle",
        "body": f"body of {title}",
        "cover_url": "",
        "author": author,
        "created": created,
        "tags": tags,
        "status": status,
    }


async def test_article_crud(articles: ArticleRepository) -> None:
    article_id = await articles.create(
        title="Alpha",
        subtitle="Alpha subtitle",
        body="alpha body",
        cover_url="",
        author="alice",
        created="2026-01-01T00:00:00",
        tags=["python"],
        status="published",
    )
    fetched = await articles.by_id(article_id)
    assert fetched is not None
    assert fetched["title"] == "Alpha"
    assert fetched["status"] == "published"
    await articles.update(
        article_id,
        title="Alpha v2",
        subtitle="sub",
        body="body",
        cover_url="https://x.io/c.webp",
        tags=["python", "web"],
        status="draft",
    )
    updated = await articles.by_id(article_id)
    assert updated is not None
    assert updated["title"] == "Alpha v2"
    assert updated["cover_url"] == "https://x.io/c.webp"
    assert updated["status"] == "draft"
    await articles.delete(article_id)
    assert await articles.by_id(article_id) is None


async def test_feed_page_single_round_trip(articles: ArticleRepository) -> None:
    for index in range(15):
        await articles.create(
            title=f"T{index:02d}",
            subtitle=f"sub {index}",
            body="body",
            cover_url="",
            author="alice",
            created=f"2026-01-{index + 1:02d}T00:00:00",
            tags=["python"],
            status="published",
        )
    docs, total = await articles.feed_page({"status": "published"}, 1, 10)
    assert total == 15
    assert len(docs) == 10
    assert docs[0]["created"] == "2026-01-15T00:00:00"
    docs2, _ = await articles.feed_page({"status": "published"}, 2, 10)
    assert len(docs2) == 5


async def test_search_relevance_ranking(articles: ArticleRepository) -> None:
    await articles.create(
        title="rare",
        subtitle="sub",
        body="zebra",
        cover_url="",
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
    )
    await articles.create(
        title="common",
        subtitle="sub",
        body="zebra zebra zebra",
        cover_url="",
        author="a",
        created="2026-01-02T00:00:00",
        tags=[],
        status="published",
    )
    docs, total = await articles.search({"status": "published"}, "zebra", 1, 10)
    assert total == 2
    assert docs[0]["title"] == "common"


async def test_search_respects_visibility_filter(
    articles: ArticleRepository,
) -> None:
    await articles.create(
        title="public",
        subtitle="s",
        body="zebra public",
        cover_url="",
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
    )
    await articles.create(
        title="hidden",
        subtitle="s",
        body="zebra hidden",
        cover_url="",
        author="a",
        created="2026-01-02T00:00:00",
        tags=[],
        status="draft",
    )
    docs, total = await articles.search({"status": "published"}, "zebra", 1, 10)
    assert total == 1
    assert docs[0]["title"] == "public"


async def test_search_paginates_with_skip_limit(
    articles: ArticleRepository,
) -> None:
    for idx in range(5):
        await articles.create(
            title=f"candidate {idx}",
            subtitle="s",
            body="target",
            cover_url="",
            author="a",
            created=f"2026-01-0{idx + 1}T00:00:00",
            tags=[],
            status="published",
        )
    docs, total = await articles.search({"status": "published"}, "target", 1, 10)
    assert total == 5
    assert len(docs) == 5
    page1, _ = await articles.search({"status": "published"}, "target", 1, 2)
    assert len(page1) == 2
    page2, _ = await articles.search({"status": "published"}, "target", 2, 2)
    assert len(page2) == 2


async def test_update_preserves_snapshots_when_omitted(
    articles: ArticleRepository,
) -> None:
    article_id = await articles.create(
        title="Snap",
        subtitle="s",
        body="body",
        cover_url="",
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
        author_active=True,
        author_publisher=True,
    )
    await articles.update(
        article_id,
        title="Snap v2",
        subtitle="s",
        body="body",
        cover_url="",
        tags=[],
        status="published",
    )
    fetched = await articles.by_id(article_id)
    assert fetched is not None
    assert fetched["author_active"] is True
    assert fetched["author_publisher"] is True


async def test_update_refreshes_snapshots_when_given(
    articles: ArticleRepository,
) -> None:
    article_id = await articles.create(
        title="Snap",
        subtitle="s",
        body="body",
        cover_url="",
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
        author_active=False,
        author_publisher=False,
    )
    await articles.update(
        article_id,
        title="Snap v2",
        subtitle="s",
        body="body",
        cover_url="",
        tags=[],
        status="published",
        author_active=True,
        author_publisher=True,
    )
    fetched = await articles.by_id(article_id)
    assert fetched is not None
    assert fetched["author_active"] is True
    assert fetched["author_publisher"] is True


async def test_search_excludes_non_matching_documents(
    articles: ArticleRepository,
) -> None:
    await articles.create(
        title="match",
        subtitle="s",
        body="body about cats",
        cover_url="",
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
    )
    await articles.create(
        title="other",
        subtitle="s",
        body="body about dogs",
        cover_url="",
        author="a",
        created="2026-01-02T00:00:00",
        tags=[],
        status="published",
    )
    docs, total = await articles.search({"status": "published"}, "cats", 1, 10)
    assert total == 1
    assert [document["title"] for document in docs] == ["match"]


async def test_substring_search_fallback(articles: ArticleRepository) -> None:
    await articles.create(
        title="Haystack",
        subtitle="s",
        body="needle IN the stack",
        cover_url="",
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
    )
    docs, total = await articles.substring_search(
        {"status": "published"}, "needle in", 1, 10
    )
    assert total == 1
    assert docs[0]["title"] == "Haystack"
    docs, total = await articles.substring_search({"status": "published"}, "(x", 1, 10)
    assert total == 0


async def test_related_tags_pipeline(articles: ArticleRepository) -> None:
    seeds = [
        (["python", "sqlite"], "2026-01-01T00:00:00"),
        (["python", "sqlite", "web"], "2026-01-02T00:00:00"),
        (["python", "web"], "2026-01-03T00:00:00"),
    ]
    for tags, created in seeds:
        await articles.create(
            title=" ".join(tags),
            subtitle="s",
            body="b",
            cover_url="",
            author="a",
            created=created,
            tags=tags,
            status="published",
        )
    related = await articles.related_tags("python", {"status": "published"})
    counts = dict(related)
    assert counts["sqlite"] == 2
    assert counts["web"] == 2
    assert "python" not in counts


async def test_covers_in_use_guard(articles: ArticleRepository) -> None:
    cover = "https://x.io/cover.webp"
    object_id = "0123456789abcdef01234567"
    variants = [f"/images/{object_id}.webp", cover]
    await articles.create(
        title="A",
        subtitle="s",
        body="b",
        cover_url=cover,
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
    )
    await articles.create(
        title="B",
        subtitle="s",
        body="b",
        cover_url="",
        author="a",
        created="2026-01-02T00:00:00",
        tags=[],
        status="published",
    )
    users = await articles.covers_using_image(object_id, variants)
    assert len(users) == 1
    assert users[0]["title"] == "A"


async def test_count_by_status(articles: ArticleRepository) -> None:
    await articles.create(
        title="P",
        subtitle="s",
        body="b",
        cover_url="",
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
    )
    await articles.create(
        title="D",
        subtitle="s",
        body="b",
        cover_url="",
        author="a",
        created="2026-01-02T00:00:00",
        tags=[],
        status="draft",
    )
    counts = await articles.count_by_status()
    assert counts == {"published": 1, "draft": 1}


async def test_comment_lifecycle_and_cascade(
    articles: ArticleRepository, comments: CommentRepository
) -> None:
    article_id = await articles.create(
        title="With comments",
        subtitle="s",
        body="b",
        cover_url="",
        author="a",
        created="2026-01-01T00:00:00",
        tags=[],
        status="published",
    )
    comment_id = await comments.create("nice", "bob", article_id, "2026-01-02T00:00:00")
    listed = await comments.for_article(article_id, {})
    assert [comment["_id"] for comment in listed] == [comment_id]
    assert await comments.count_by_author("bob") == 1
    await comments.delete(comment_id)
    assert await comments.by_id(comment_id) is None
    await comments.create("one", "bob", article_id, "2026-01-03T00:00:00")
    await comments.create("two", "carol", article_id, "2026-01-04T00:00:00")
    await comments.delete_for_article(article_id)
    assert await comments.for_article(article_id, {}) == []


async def test_object_roundtrip_and_alt_text(
    objects: ObjectRepository,
) -> None:
    payload = b"\x00\x01image-bytes"
    object_id = await objects.upload(
        "alice_photo_a1b2.webp",
        payload,
        {
            "owner": "alice",
            "original_filename": "photo.png",
            "alt_text": "photo.png",
            "upload_time": "2026-01-01T00:00:00",
            "content_type": "image/webp",
        },
    )
    assert len(object_id) == 24
    data = await objects.data(object_id)
    assert data == payload
    registry = await objects.metadata(object_id)
    assert registry is not None
    assert registry["filename"] == "alice_photo_a1b2.webp"
    assert registry["metadata"]["owner"] == "alice"
    assert await objects.metadata("ffffffffffffffffffffffff") is None
    assert await objects.data("ffffffffffffffffffffffff") is None
    await objects.update_alt_text(object_id, "a better alt")
    updated = await objects.metadata(object_id)
    assert updated is not None
    assert updated["metadata"]["alt_text"] == "a better alt"
    assert updated["metadata"]["owner"] == "alice"
    await objects.delete(object_id)
    assert await objects.data(object_id) is None


async def test_object_gallery_listing(objects: ObjectRepository) -> None:
    for index in range(14):
        await objects.upload(
            f"alice_img{index:02d}_aa.webp",
            b"x",
            {
                "owner": "alice",
                "original_filename": f"img{index}.png",
                "alt_text": f"img{index}",
                "upload_time": f"2026-01-01T00:{index:02d}:00",
                "content_type": "image/webp",
            },
        )
    rows, total = await objects.list_for("alice", 1, 12)
    assert total == 14
    assert len(rows) == 12
    rows2, _ = await objects.list_for("bob", 1, 12)
    assert rows2 == []
    rows3, total3 = await objects.list_for(None, 2, 12)
    assert total3 == 14
    assert len(rows3) == 2
