"""Consolidated visibility rules (spec §13) and their coherence.

Public feeds (anonymous and signed-in alike, per Appendix B D2) show
published articles by active publisher members; administrators see
everything. A non-publisher's published article is viewable only by its
author and administrators; a disabled member's content is hidden from
everyone except administrators. Drafts surface only on their author's
profile.
"""

from typing import Any

from ..repositories.articles import ArticleRepository
from ..repositories.comments import CommentRepository
from ..repositories.documents import ArticleDocument, MemberDocument

__all__ = ["PUBLIC_FEED_FILTER", "ArticleVisibility"]

PUBLIC_FEED_FILTER: dict[str, Any] = {
    "status": "published",
    "author_active": True,
    "author_publisher": True,
}

_ADMIN_FEED_FILTER: dict[str, Any] = {"status": "published"}


def feed_filter(viewer: MemberDocument | None) -> dict[str, Any]:
    """The feed/search visibility filter for a viewer (spec §13, D2, D3).

    Administrators keep broader visibility over the public feed/search but
    drafts stay out of public search ordering (D3): they surface on the
    dedicated review page (§11.3).
    """
    if viewer is not None and viewer["administrator"]:
        return dict(_ADMIN_FEED_FILTER)
    return dict(PUBLIC_FEED_FILTER)


def tag_filter(viewer: MemberDocument | None, tag: str) -> dict[str, Any]:
    """Tag-page filter; administrators also see drafts here (§13)."""
    base = feed_filter(viewer)
    if viewer is not None and viewer["administrator"]:
        base.pop("status")
    return {"$and": [base, {"tags": tag}]}


class ArticleVisibility:
    """Per-article view authorization and snapshot coherence (spec §13)."""

    def __init__(
        self,
        articles: ArticleRepository,
        comments: CommentRepository,
    ) -> None:
        self._articles = articles
        self._comments = comments

    def can_view(self, viewer: MemberDocument | None, article: ArticleDocument) -> bool:
        """Whether ``viewer`` may open ``article``'s page (§13)."""
        if article.get("status") != "published":
            if viewer is None:
                return False
            return bool(
                viewer["administrator"] or viewer["display_name"] == article["author"]
            )
        if viewer is not None and viewer["administrator"]:
            return True
        author_is_active_publisher = (
            article["author_active"] and article["author_publisher"]
        )
        if author_is_active_publisher:
            return True
        return viewer is not None and viewer["display_name"] == article["author"]

    def can_edit(self, viewer: MemberDocument | None, article: ArticleDocument) -> bool:
        """Only the author or an administrator may edit (spec §5.3)."""
        if viewer is None:
            return False
        if viewer["administrator"]:
            return True
        return viewer["display_name"] == article["author"]

    def can_delete(
        self, viewer: MemberDocument | None, article: ArticleDocument
    ) -> bool:
        """Admins or authors delete published articles.
        Draft deletion is author-only (§5.4).
        """
        if viewer is None:
            return False
        if article["status"] != "published":
            return viewer["display_name"] == article["author"]
        if viewer["administrator"]:
            return True
        return viewer["display_name"] == article["author"]

    async def articles_by_author(self, author: str) -> list[ArticleDocument]:
        """The author's own articles, for profile statistics (§4.5)."""
        return await self._articles.for_author(author)

    async def count_by_author(self, author: str) -> dict[str, int]:
        """The author's published/draft totals, counted in the engine (§14)."""
        return await self._articles.count_by_author(author)

    async def delete_comments_for(self, article_id: str) -> None:
        """Cascade comment deletion with its article (spec §5.4)."""
        await self._comments.delete_for_article(article_id)

    async def resync_author_articles(self, member: MemberDocument) -> None:
        """Keep snapshots coherent after a role or state change (§11.2)."""
        await self._articles.update_many_snapshots(
            member["display_name"],
            author_active=member["active"],
            author_publisher=member["publisher"],
        )
        await self._comments.resync_author_active(
            member["display_name"], member["active"]
        )
