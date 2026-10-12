"""Administration: dashboard, member management, review, reindex (spec §11).

Only administrators reach any admin route; role changes resync the
author-visibility snapshots and clear the response cache (§11.2, §14).
"""

from quart import Blueprint, flash, g, redirect, render_template, request
from werkzeug.wrappers import Response

from ..context import AppContext

__all__ = ["create_admin_blueprint"]


def create_admin_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("admin", __name__)

    async def _guard() -> Response | None:
        if g.member is None or not g.member["administrator"]:
            await flash("Administrators only.", "error")
            return redirect("/")
        return None

    @blueprint.route("/admin")
    async def dashboard() -> str | Response:
        refused = await _guard()
        if refused is not None:
            return refused
        member_stats = await context.members.dashboard()
        article_stats = await context.articles.count_by_status()
        comments_total = await context.comments.total()
        g.breadcrumbs = [("Home", "/"), ("Admin", "/admin")]
        return await render_template(
            "admin.html",
            members=member_stats,
            articles=article_stats,
            comments_total=comments_total,
            member_rows=await context.members.all(),
        )

    @blueprint.route("/admin/unpublished")
    async def review() -> str | Response:
        refused = await _guard()
        if refused is not None:
            return refused
        rows = await context.articles.unpublished_review()
        g.breadcrumbs = [
            ("Home", "/"),
            ("Admin", "/admin"),
            ("Review", "/admin/unpublished"),
        ]
        return await render_template("review.html", rows=rows)

    @blueprint.route("/admin/members/<hexid:member_id>/disable", methods=["POST"])
    @blueprint.route("/admin/members/<hexid:member_id>/enable", methods=["POST"])
    async def toggle_active(member_id: str) -> Response:
        refused = await _guard()
        if refused is not None:
            return refused
        disable = request.path.endswith("/disable")
        target = await context.members.by_id(member_id)
        if target is None:
            await flash("No such member.", "error")
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
    async def promote(member_id: str) -> Response:
        refused = await _guard()
        if refused is not None:
            return refused
        target = await context.members.by_id(member_id)
        if target is None:
            await flash("No such member.", "error")
            return redirect("/admin")
        await context.members.set_administrator(member_id, True)
        await context.visibility.resync_author_articles(target)
        await context.meta.bump_content_version()
        await flash("Promoted to administrator.", "success")
        return redirect("/admin")

    @blueprint.route("/admin/members/<hexid:member_id>/publisher", methods=["POST"])
    async def toggle_publisher(member_id: str) -> Response:
        refused = await _guard()
        if refused is not None:
            return refused
        target = await context.members.by_id(member_id)
        if target is None:
            await flash("No such member.", "error")
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
    async def reindex() -> Response:
        refused = await _guard()
        if refused is not None:
            return refused
        await context.articles.rebuild_search_indexes()
        await flash("Search indexes rebuilt.", "success")
        return redirect("/admin")

    return blueprint
