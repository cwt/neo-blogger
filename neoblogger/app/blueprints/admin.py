"""Administration: dashboard, member management, review, reindex (spec §11).

Only administrators reach any admin route; role changes resync the
author-visibility snapshots and clear the response cache (§11.2, §14).
"""

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Any

from quart import Blueprint, flash, g, redirect, render_template, request
from werkzeug.wrappers import Response

from ..context import AppContext
from ..repositories.documents import MemberDocument

__all__ = ["create_admin_blueprint"]


def _admin_required(
    view: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Refuse non-administrators with the standard flash + redirect (§11)."""

    @functools.wraps(view)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if g.member is None or not g.member["administrator"]:
            await flash("Administrators only.", "error")
            return redirect("/")
        return await view(*args, **kwargs)

    return wrapper


def create_admin_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("admin", __name__)

    async def _load_member(member_id: str) -> MemberDocument | None:
        """Fetch a member, flashing when missing (§11.2)."""
        target = await context.members.by_id(member_id)
        if target is None:
            await flash("No such member.", "error")
        return target

    @blueprint.route("/admin")
    @_admin_required
    async def dashboard() -> str | Response:
        member_stats: dict[str, int] = {}
        article_stats: dict[str, int] = {}
        comments_total = 0
        member_rows: list[object] = []
        async with asyncio.TaskGroup() as group:

            async def _load_members() -> None:
                nonlocal member_stats
                member_stats = await context.members.dashboard()

            async def _load_articles() -> None:
                nonlocal article_stats
                article_stats = await context.articles.count_by_status()

            async def _load_comments() -> None:
                nonlocal comments_total
                comments_total = await context.comments.total()

            async def _load_rows() -> None:
                nonlocal member_rows
                rows = await context.members.all()
                member_rows = list(rows)

            group.create_task(_load_members())
            group.create_task(_load_articles())
            group.create_task(_load_comments())
            group.create_task(_load_rows())
        g.breadcrumbs = [("Home", "/"), ("Admin", "/admin")]
        return await render_template(
            "admin.html",
            members=member_stats,
            articles=article_stats,
            comments_total=comments_total,
            member_rows=member_rows,
        )

    @blueprint.route("/admin/unpublished")
    @_admin_required
    async def review() -> str | Response:
        rows = await context.articles.unpublished_review()
        g.breadcrumbs = [
            ("Home", "/"),
            ("Admin", "/admin"),
            ("Review", "/admin/unpublished"),
        ]
        return await render_template("review.html", rows=rows)

    @blueprint.route("/admin/members/<hexid:member_id>/disable", methods=["POST"])
    @blueprint.route("/admin/members/<hexid:member_id>/enable", methods=["POST"])
    @_admin_required
    async def toggle_active(member_id: str) -> Response:
        disable = request.path.endswith("/disable")
        target = await _load_member(member_id)
        if target is None:
            return redirect("/admin")
        if disable and target["administrator"]:
            await flash("An administrator can never be disabled.", "error")
            return redirect("/admin")
        await context.members.set_active(member_id, not disable)
        target["active"] = not disable
        await context.visibility.resync_author_articles(target)
        await context.meta.bump_content_version()
        await flash("Account updated.", "success")
        return redirect("/admin")

    @blueprint.route("/admin/members/<hexid:member_id>/promote", methods=["POST"])
    @_admin_required
    async def promote(member_id: str) -> Response:
        target = await _load_member(member_id)
        if target is None:
            return redirect("/admin")
        await context.members.set_administrator(member_id, True)
        await context.visibility.resync_author_articles(target)
        await context.meta.bump_content_version()
        await flash("Promoted to administrator.", "success")
        return redirect("/admin")

    @blueprint.route("/admin/members/<hexid:member_id>/publisher", methods=["POST"])
    @_admin_required
    async def toggle_publisher(member_id: str) -> Response:
        target = await _load_member(member_id)
        if target is None:
            return redirect("/admin")
        granted = not target["publisher"]
        if not granted and target["administrator"]:
            stats = await context.members.dashboard()
            if stats.get("admins", 0) <= 1:
                await flash("The sole administrator must remain a publisher.", "error")
                return redirect("/admin")
        await context.members.set_publisher(member_id, granted)
        target["publisher"] = granted
        await context.visibility.resync_author_articles(target)
        await context.meta.bump_content_version()
        await flash(
            "Publisher status granted." if granted else "Publisher status revoked.",
            "success",
        )
        return redirect("/admin")

    @blueprint.route("/admin/reindex", methods=["POST"])
    @_admin_required
    async def reindex() -> Response:
        await context.articles.rebuild_search_indexes()
        await flash("Search indexes rebuilt.", "success")
        return redirect("/admin")

    return blueprint
