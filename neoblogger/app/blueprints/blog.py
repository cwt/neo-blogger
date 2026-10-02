"""Reading and writing: home feed, article pages, editor, deletion (spec §5, §6)."""

import datetime
from collections.abc import Awaitable
from typing import Any

from quart import Blueprint, flash, g, redirect, render_template, request
from werkzeug.routing import BaseConverter
from werkzeug.wrappers import Response as WerkzeugResponse

from ..context import AppContext
from ..services.articles import CoverRequiredError
from ..services.objects import derive_description, legacy_url
from ..text.highlight import highlight_code_blocks
from ..text.markdown import render_markdown
from ..text.sanitize import sanitize_html

__all__ = ["HexIdConverter", "create_blog_blueprint", "render_home_page"]


def _page_parameters(context: AppContext) -> tuple[int, int]:
    """Clamped (page, per_page) from the query string (spec §14, §18)."""
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    if page < 1:
        page = 1
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


def create_blog_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("blog", __name__)

    @blueprint.route("/")
    async def home() -> str | WerkzeugResponse:
        page, per_page = _page_parameters(context)
        g.breadcrumbs = [("Home", "/")]
        return await render_home_page(context, page, per_page, g.member)

    @blueprint.route("/<hexid:article_id>")
    async def article_page(article_id: str) -> str | WerkzeugResponse:
        article = await context.articles.by_id(article_id)
        if article is None or not context.visibility.can_view(g.member, article):
            await flash("That content is not available.", "error")
            return redirect("/")
        rendered_body = highlight_code_blocks(
            sanitize_html(render_markdown(article["body"]))
        )
        comments = await context.comment_service.list(article)
        comment_rendered = {
            comment["_id"]: highlight_code_blocks(
                sanitize_html(render_markdown(comment["text"]))
            )
            for comment in comments
        }
        g.article = {
            "title": article["title"],
            "author": article["author"],
            "created": article["created"],
            "description": derive_description(article["body"]),
            "image": legacy_url(article["cover_url"]) if article["cover_url"] else None,
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
        article = None
        if article_id is not None:
            article = await context.articles.by_id(article_id)
            if article is None or not context.visibility.can_edit(g.member, article):
                await flash("You cannot edit that article.", "error")
                return redirect("/profile")
        if request.method == "POST":
            form = await request.form
            publish = form.get("action") == "publish"
            try:
                saved_id = await context.article_service.save(
                    g.member,
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
            except Exception as error:  # — flashed, never a trace
                await flash(str(error), "error")
                return redirect("/write")
            await flash("Saved.", "success")
            if publish:
                if article_id is None:
                    return redirect("/")
                return redirect(f"/{saved_id}")
            return redirect("/profile")
        g.breadcrumbs = [("Home", "/"), ("Write", "/write")]
        return await render_template("write.html", article=article)

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
        form = await request.form
        try:
            await context.comment_service.add(
                g.member, article, form.get("text", "").strip(), _now()
            )
        except Exception as error:  # — flashed, never a trace
            await flash(str(error), "error")
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
    context: AppContext, page: int, per_page: int, member: Any
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


def _now() -> str:
    """The current local timestamp as an ISO string (spec §5.1)."""
    return datetime.datetime.now().isoformat(timespec="seconds")
