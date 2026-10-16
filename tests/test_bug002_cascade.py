"""Bug 002 regression: re-drafted delete cascades; drafts reject comments."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.articles import ArticleRepository
from neoblogger.app.repositories.comments import CommentRepository
from neoblogger.app.repositories.db import Database
from neoblogger.app.repositories.documents import ArticleDocument, MemberDocument
from neoblogger.app.repositories.members import MemberRepository
from neoblogger.app.repositories.meta import MetaRepository
from neoblogger.app.services.articles import ArticleService
from neoblogger.app.services.comments import CommentService
from neoblogger.app.services.visibility import ArticleVisibility


@pytest.fixture
async def wired(tmp_path: Path) -> AsyncIterator[dict[str, Any]]:
    db = Database(DatabaseConfig(path=str(tmp_path / "b2.db")))
    await db.start()
    try:
        articles = ArticleRepository(db)
        comments = CommentRepository(db)
        members = MemberRepository(db)
        meta = MetaRepository(db)
        visibility = ArticleVisibility(articles, comments)
        article_service = ArticleService(articles, members, meta, visibility)
        comment_service = CommentService(comments, articles, meta)
        yield {
            "articles": articles,
            "comments": comments,
            "members": members,
            "article_service": article_service,
            "comment_service": comment_service,
            "visibility": visibility,
        }
    finally:
        await db.close()


def _member(active: bool = True) -> MemberDocument:
    return cast(
        MemberDocument,
        {
            "_id": "m1",
            "display_name": "alice",
            "email": "a@x.io",
            "active": active,
            "administrator": False,
            "publisher": True,
        },
    )


def _article(status: str) -> ArticleDocument:
    return cast(ArticleDocument, {"_id": "a1", "status": status})


async def test_delete_draft_cascades_comments(
    wired: dict[str, Any],
) -> None:
    service = cast(ArticleService, wired["article_service"])
    articles = cast(ArticleRepository, wired["articles"])
    comments = cast(CommentRepository, wired["comments"])
    article_id = await articles.create(
        "T", "s", "b", "", "alice", "2026-01-01T00:00:00", [], "published"
    )
    article = await articles.by_id(article_id)
    assert article is not None
    await comments.create("hello", "bob", article_id, "2026-01-01T00:00:01")
    redrafted = dict(article)
    redrafted["status"] = "draft"
    await service.delete(cast(ArticleDocument, redrafted))
    assert await articles.by_id(article_id) is None
    assert await comments.for_article(article_id, {}) == []


async def test_draft_rejects_comments(wired: dict[str, Any]) -> None:
    service = cast(CommentService, wired["comment_service"])
    with pytest.raises(ValueError, match="drafts cannot"):
        await service.add(_member(), _article("draft"), "hi", "2026-01-01T00:00:00")
    with pytest.raises(ValueError, match="comment text is required"):
        await service.add(
            _member(), _article("published"), "   ", "2026-01-01T00:00:00"
        )
