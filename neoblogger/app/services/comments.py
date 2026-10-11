"""Comment workflows (spec §7).

Comments carry an ``author_active`` snapshot so visible-comment filtering
runs on indexed fields; deletion is author-or-administrator and needs no
parent article id (Appendix B D6).
"""

from ..repositories.articles import ArticleRepository
from ..repositories.comments import CommentRepository
from ..repositories.documents import ArticleDocument, CommentDocument, MemberDocument
from ..repositories.meta import MetaRepository

__all__ = ["CommentService"]


class CommentService:
    """Adding, listing, and deleting comments."""

    def __init__(
        self,
        comments: CommentRepository,
        articles: ArticleRepository,
        meta: MetaRepository,
    ) -> None:
        self._comments = comments
        self._articles = articles
        self._meta = meta

    async def add(
        self,
        viewer: MemberDocument,
        article: ArticleDocument,
        text: str,
        created: str,
    ) -> str:
        """Attach a comment to an article (spec §7)."""
        if not viewer["active"]:
            raise ValueError("disabled members cannot comment")
        comment_id = await self._comments.create(
            text,
            viewer["display_name"],
            article["_id"],
            created,
            author_active=True,
        )
        await self._meta.bump_content_version()
        return comment_id

    async def delete(self, viewer: MemberDocument, comment: CommentDocument) -> bool:
        """Author-or-administrator delete (spec §7, D6); version bump."""
        authorized = viewer["administrator"] or (
            viewer["display_name"] == comment["author"]
        )
        if not authorized:
            return False
        await self._comments.delete(comment["_id"])
        await self._meta.bump_content_version()
        return True

    async def list(
        self, article: ArticleDocument, viewer: MemberDocument | None = None
    ) -> list[CommentDocument]:
        """Comments visible to ``viewer`` (spec §7, §13).

        Administrators see everything, including comments by disabled
        members, so hidden content stays moderatable; everyone else sees
        active-author comments only.
        """
        if viewer is not None and viewer["administrator"]:
            return await self._comments.for_article(article["_id"], {})
        return await self._comments.for_article(article["_id"], {"author_active": True})
