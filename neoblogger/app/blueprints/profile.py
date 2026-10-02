"""Member workspace: statistics and posts management (spec §4.5, §4.6)."""

from quart import Blueprint, flash, g, redirect, render_template
from werkzeug.wrappers import Response

from ..context import AppContext

__all__ = ["create_profile_blueprint"]


def create_profile_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("profile", __name__)

    @blueprint.route("/profile")
    async def profile() -> str | Response:
        if g.member is None:
            await flash("Sign in first.", "error")
            return redirect("/signin")
        stats = await context.accounts.profile_statistics(g.member)
        posts = await context.visibility.articles_by_author(g.member["display_name"])
        drafts = [post for post in posts if post["status"] == "draft"]
        published = [post for post in posts if post["status"] == "published"]
        g.breadcrumbs = [("Home", "/"), ("Profile", "/profile")]
        return await render_template(
            "profile.html", stats=stats, posts=drafts + published
        )

    return blueprint
