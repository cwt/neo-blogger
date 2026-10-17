"""Discovery pages: tag feeds and search results (spec §8, §9).

Tag pages are explicitly no-cache; search responses are never cached.
Rejections flash "please use only text" and redirect home (§9).
"""

import asyncio
from urllib.parse import quote, quote_plus

from quart import Blueprint, flash, g, redirect, render_template, request
from werkzeug.wrappers import Response as WerkzeugResponse

from ..context import AppContext
from ..services.search import validate_query
from .blog import page_parameters

__all__ = ["create_discovery_blueprint"]


def create_discovery_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("discovery", __name__)

    @blueprint.route("/tag/<name>")
    async def tag_page(name: str) -> str | WerkzeugResponse:
        page, per_page = page_parameters(context)
        (articles, total), related = await asyncio.gather(
            context.article_service.tag_page(g.member, name, page, per_page),
            context.article_service.related_tags(g.member, name),
        )
        g.breadcrumbs = [("Home", "/"), (f"#{name}", f"/tag/{name}")]
        return await render_template(
            "tag.html",
            heading=f"#{name}",
            articles=articles,
            page=page,
            per_page=per_page,
            has_more=total > page * per_page,
            base_url_path=f"/tag/{name}",
            query_suffix="",
            related_tags=related,
        )

    @blueprint.route("/author/<path:display_name>")
    async def author_page(display_name: str) -> str | WerkzeugResponse:
        member = await context.members.by_display_name(display_name)
        if member is None:
            await flash("That member does not exist.", "error")
            return redirect("/")
        page, per_page = page_parameters(context)
        name = member["display_name"]
        author_path = f"/author/{quote(name, safe='')}"
        articles, total = await context.article_service.author_page(
            g.member, name, page, per_page
        )
        g.breadcrumbs = [("Home", "/"), (name, author_path)]
        return await render_template(
            "author.html",
            display_name=name,
            articles=articles,
            page=page,
            per_page=per_page,
            has_more=total > page * per_page,
            base_url_path=author_path,
            query_suffix="",
        )

    @blueprint.route("/search")
    async def search() -> str | WerkzeugResponse:
        raw = request.args.get("q", "")
        page, per_page = page_parameters(context)
        query = validate_query(raw)
        if query is None:
            await flash("Please use only text in your search.", "error")
            return redirect("/")
        articles, total = await context.article_service.search(
            g.member, query, page, per_page
        )
        g.breadcrumbs = [("Home", "/"), (f"Search: {query}", "/search")]
        return await render_template(
            "search.html",
            query=query,
            articles=articles,
            page=page,
            per_page=per_page,
            has_more=total > page * per_page,
            base_url_path="/search",
            query_suffix=f"&q={quote_plus(query)}",
            related_tags=None,
        )

    return blueprint
