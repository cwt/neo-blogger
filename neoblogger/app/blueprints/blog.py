"""Reading and writing: home feed, article pages, editor, deletion (spec §5, §6)."""

import logging
from collections.abc import Awaitable

from quart import Blueprint, flash, g, redirect, render_template, request
from werkzeug.routing import BaseConverter
from werkzeug.wrappers import Response as WerkzeugResponse

from ..context import AppContext
from ..repositories.documents import ArticleDocument, MemberDocument
from ..security.proxy import forwarded_base
from ..services.articles import CoverRequiredError
from ..services.objects import derive_description, legacy_url
from ..services.timestamps import now_iso as _now_iso
from ..text.pipeline import render_rich_text
from .paging import parse_page_number
from .seo import canonical_url_for

__all__ = [
    "HexIdConverter",
    "create_blog_blueprint",
    "page_parameters",
    "render_home_page",
]

_logger = logging.getLogger(__name__)


_COVER_PICKER_LIMIT = 48
"""Recent uploads offered by the editor cover picker (spec §5.1)."""


def page_parameters(context: AppContext) -> tuple[int, int]:
    """Clamped (page, per_page) from the query string (spec §14, §18)."""
    page = parse_page_number(request.args)
    per_page = context.config.posts.per_page
    if per_page < 1:
        per_page = 1
    maximum = context.config.posts.max_per_page
    if per_page > maximum:
        per_page = maximum
    return page, per_page


class HexIdConverter(BaseConverter):
    """Matches opaque hex document ids (identifier-based URLs, §19)."""

    regex = "[0-9a-f]{24}"


async def _load_editable_article(
    context: AppContext, member: MemberDocument, article_id: str | None
) -> ArticleDocument | None:
    """The article being edited, or ``None`` when missing/forbidden (§5)."""
    if article_id is None:
        return None
    article = await context.articles.by_id(article_id)
    if article is None or not context.visibility.can_edit(member, article):
        return None
    return article


async def _handle_write_post(
    context: AppContext, member: MemberDocument, article_id: str | None
) -> WerkzeugResponse:
    """Persist the editor POST; returns the follow-up redirect (§5.1)."""
    form = await request.form
    publish = form.get("action") == "publish"
    try:
        saved_id = await context.article_service.save(
            member,
            article_id=article_id,
            title=form.get("title", "").strip(),
            subtitle=form.get("subtitle", "").strip(),
            body=form.get("body", ""),
            cover_url=form.get("cover_url", "").strip(),
            tags_raw=form.get("tags", ""),
            publish=publish,
        )
    except CoverRequiredError:
        await flash("A cover image is required to publish.", "error")
        return redirect(f"/write/{article_id}" if article_id else "/write")
    except Exception as error:
        _logger.error("Failed to save article: %s", error, exc_info=True)
        await flash("Failed to save article. Please try again.", "error")
        edit_target = f"/write/{article_id}" if article_id else "/write"
        return redirect(edit_target)
    await flash("Saved.", "success")
    if publish:
        if article_id is None:
            return redirect("/")
        return redirect(f"/{saved_id}")
    return redirect("/profile")


def create_blog_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("blog", __name__)

    @blueprint.route("/")
    async def home() -> str | WerkzeugResponse:
        page, per_page = page_parameters(context)
        g.breadcrumbs = [("Home", "/")]
        return await render_home_page(context, page, per_page, g.member)

    @blueprint.route("/<hexid:article_id>")
    async def article_page(article_id: str) -> str | WerkzeugResponse:
        is_admin = bool(g.member and g.member["administrator"])
        article, comments = await context.articles.page_data(article_id, is_admin)
        if article is None or not context.visibility.can_view(g.member, article):
            await flash("That content is not available.", "error")
            return redirect("/")
        rendered_body = render_rich_text(article["body"])
        comment_rendered = {
            comment["_id"]: render_rich_text(comment["text"]) for comment in comments
        }
        g.article = {
            "title": article["title"],
            "author": article["author"],
            "created": article["created"],
            "description": derive_description(article["body"]),
            "image": _absolute_image_url(context, article["cover_url"])
            if article["cover_url"]
            else None,
            "tags": article["tags"],
        }
        g.breadcrumbs = [("Home", "/"), (article["title"], f"/{article_id}")]
        return await render_template(
            "article.html",
            article=article,
            rendered_body=rendered_body,
            comments=comments,
            comment_rendered=comment_rendered,
        )

    @blueprint.route("/write", methods=["GET", "POST"])
    @blueprint.route("/write/<hexid:article_id>", methods=["GET", "POST"])
    async def write(article_id: str | None = None) -> str | WerkzeugResponse:
        if g.member is None:
            await flash("Sign in to write.", "error")
            return redirect("/signin")
        article: ArticleDocument | None = None
        if article_id is not None:
            article = await _load_editable_article(context, g.member, article_id)
            if article is None:
                await flash("You cannot edit that article.", "error")
                return redirect("/profile")
        if request.method == "POST":
            return await _handle_write_post(context, g.member, article_id)
        g.breadcrumbs = [("Home", "/"), ("Write", "/write")]
        owner = None if g.member["administrator"] else g.member["display_name"]
        cover_images, _total = await context.objects.list_for(
            owner, 1, _COVER_PICKER_LIMIT
        )
        return await render_template(
            "write.html", article=article, cover_images=cover_images
        )

    @blueprint.route("/articles/<hexid:article_id>/delete", methods=["POST"])
    async def delete_article(article_id: str) -> WerkzeugResponse:
        article = await context.articles.by_id(article_id)
        if article is None or not context.visibility.can_delete(g.member, article):
            await flash("You cannot delete that article.", "error")
            return redirect("/")
        await context.article_service.delete(article)
        await flash("Article deleted.", "success")
        return redirect("/profile")

    @blueprint.route("/articles/<hexid:article_id>/comments", methods=["POST"])
    async def add_comment(article_id: str) -> WerkzeugResponse:
        if g.member is None:
            await flash("Sign in to comment.", "error")
            return redirect("/signin")
        article = await context.articles.by_id(article_id)
        if article is None or not context.visibility.can_view(g.member, article):
            await flash("That content is not available.", "error")
            return redirect("/")
        if article.get("status") != "published":
            await flash("That content is not available.", "error")
            return redirect("/")
        form = await request.form
        try:
            await context.comment_service.add(
                g.member, article, form.get("text", "").strip(), _now_iso()
            )
        except Exception as error:
            _logger.error("Failed to post comment: %s", error, exc_info=True)
            await flash("Failed to post comment. Please try again.", "error")
            return redirect(f"/{article_id}")
        await flash("Comment added.", "success")
        return redirect(f"/{article_id}#comments")

    @blueprint.route("/comments/<hexid:comment_id>/delete", methods=["POST"])
    async def delete_comment(comment_id: str) -> WerkzeugResponse:
        comment = await context.comments.by_id(comment_id)
        if comment is None or g.member is None:
            await flash("That comment is not available.", "error")
            return redirect("/")
        if not await context.comment_service.delete(g.member, comment):
            await flash("You cannot delete that comment.", "error")
            return redirect(f"/{comment['article_id']}")
        await flash("Comment deleted.", "success")
        return redirect(f"/{comment['article_id']}#comments")

    return blueprint


def render_home_page(
    context: AppContext, page: int, per_page: int, member: MemberDocument | None
) -> Awaitable[str]:
    """Awaitable of the home-feed page; shared by route and pre-warm (§14)."""

    async def _render() -> str:
        articles, total = await context.article_service.feed(member, page, per_page)
        g.breadcrumbs = [("Home", "/")]
        return await render_template(
            "home.html",
            articles=articles,
            page=page,
            per_page=per_page,
            has_more=total > page * per_page,
        )

    return _render()


def _absolute_image_url(context: AppContext, cover_url: str) -> str:
    """Canonical absolute image URL for metadata (bugs/005, spec §18)."""
    local = legacy_url(cover_url)
    if local.startswith("http://") or local.startswith("https://"):
        return local
    peer = request.remote_addr or ""
    fallback = forwarded_base(
        peer,
        request.scheme,
        request.host,
        request.headers.get("X-Forwarded-Proto"),
        request.headers.get("X-Forwarded-Host"),
        request.url_root,
        context.proxy_trust,
    )
    return canonical_url_for(context.config.application.base_url, fallback, local)
