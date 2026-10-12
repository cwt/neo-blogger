"""Article, feed, and discovery workflows (spec §5, §8, §9)."""

import datetime
import logging

from ..repositories.articles import ArticleRepository
from ..repositories.documents import ArticleDocument, MemberDocument
from ..repositories.members import MemberRepository
from ..repositories.meta import MetaRepository
from .visibility import ArticleVisibility, feed_filter, tag_filter

__all__ = ["ArticleService", "CoverRequiredError"]

_logger = logging.getLogger(__name__)


def _parse_tags(raw: str) -> list[str]:
    """Comma-separated field → trimmed, de-duplicated tag list (spec §5.1)."""
    tags: list[str] = []
    for entry in raw.split(","):
        tag = entry.strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _now_iso() -> str:
    """The current local timestamp as an ISO string (spec §5.1)."""
    return datetime.datetime.now().isoformat(timespec="seconds")


class CoverRequiredError(Exception):
    """Raised when publishing without a cover image (spec §5.1, §5.2)."""


class ArticleService:
    """Writing, publishing, reading, and discovery glue."""

    def __init__(
        self,
        articles: ArticleRepository,
        members: MemberRepository,
        meta: MetaRepository,
        visibility: ArticleVisibility,
    ) -> None:
        self._articles = articles
        self._members = members
        self._meta = meta
        self._visibility = visibility

    async def save(
        self,
        author: MemberDocument,
        *,
        article_id: str | None,
        title: str,
        subtitle: str,
        body: str,
        cover_url: str,
        tags_raw: str,
        publish: bool,
        created: str | None = None,
    ) -> str:
        """Create or update an article as draft or published (spec §5.1).

        Publishing requires a cover image. Saving bumps the global
        content version so cached feed pages refresh (spec §14).
        """
        tags = _parse_tags(tags_raw)
        status = "published" if publish else "draft"
        if publish and not cover_url.strip():
            raise CoverRequiredError("a cover image is required to publish")
        if article_id is None:
            created_at = created if created is not None else _now_iso()
            saved_id = await self._articles.create(
                title,
                subtitle,
                body,
                cover_url,
                author["display_name"],
                created_at,
                tags,
                status,
                author_active=author["active"],
                author_publisher=author["publisher"],
            )
        else:
            existing = await self._articles.by_id(article_id)
            snapshot_active: bool | None = author["active"]
            snapshot_publisher: bool | None = author["publisher"]
            if existing is not None and existing["author"] != author["display_name"]:
                # An administrator editing someone else's article must not
                # stamp their own flags onto it; resync from the owner.
                owner = await self._members.by_display_name(existing["author"])
                if owner is not None:
                    snapshot_active = owner["active"]
                    snapshot_publisher = owner["publisher"]
                else:
                    snapshot_active = None
                    snapshot_publisher = None
            await self._articles.update(
                article_id,
                title=title,
                subtitle=subtitle,
                body=body,
                cover_url=cover_url,
                tags=tags,
                status=status,
                author_active=snapshot_active,
                author_publisher=snapshot_publisher,
            )
            saved_id = article_id
        await self._meta.bump_content_version()
        return saved_id

    async def delete(self, article: ArticleDocument) -> None:
        """Cascade comments for published articles and remove the document (§5.4)."""
        if article["status"] == "published":
            await self._visibility.delete_comments_for(article["_id"])
        await self._articles.delete(article["_id"])
        await self._meta.bump_content_version()

    async def feed(
        self, viewer: MemberDocument | None, page: int, per_page: int
    ) -> tuple[list[ArticleDocument], int]:
        return await self._articles.feed_page(feed_filter(viewer), page, per_page)

    async def tag_page(
        self, viewer: MemberDocument | None, tag: str, page: int, per_page: int
    ) -> tuple[list[ArticleDocument], int]:
        return await self._articles.feed_page(tag_filter(viewer, tag), page, per_page)

    async def related_tags(
        self, viewer: MemberDocument | None, tag: str
    ) -> list[tuple[str, int]]:
        return await self._articles.related_tags(tag, feed_filter(viewer))

    async def search(
        self,
        viewer: MemberDocument | None,
        term: str,
        page: int,
        per_page: int,
    ) -> tuple[list[ArticleDocument], int]:
        """Relevance search with a substring fallback (spec §9)."""
        combined = feed_filter(viewer)
        combined["$text"] = {"$search": term}
        try:
            return await self._articles.search(combined, term, page, per_page)
        except Exception as error:
            _logger.warning(
                "FTS search failed for %r; falling back to substring: %s",
                term,
                error,
            )
            return await self._articles.substring_search(
                feed_filter(viewer), term, page, per_page
            )
