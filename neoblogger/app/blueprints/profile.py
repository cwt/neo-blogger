"""Member workspace: statistics and posts management (spec §4.5, §4.6)."""

import asyncio

from quart import Blueprint, flash, g, redirect, render_template, request
from werkzeug.wrappers import Response

from ..context import AppContext
from ..services.accounts import SECURITY_QUESTION_LABELS as QUESTION_LABELS

__all__ = ["create_profile_blueprint"]


_RECENT_PUBLISHED_LIMIT = 5


def create_profile_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("profile", __name__)

    @blueprint.route("/profile")
    async def profile() -> str | Response:
        if g.member is None:
            await flash("Sign in first.", "error")
            return redirect("/signin")
        display = g.member["display_name"]
        stats, (drafts, recent) = await asyncio.gather(
            context.accounts.profile_statistics(g.member),
            context.articles.author_profile_posts(display, _RECENT_PUBLISHED_LIMIT),
        )
        g.breadcrumbs = [("Home", "/"), ("Profile", "/profile")]
        return await render_template("profile.html", stats=stats, posts=drafts + recent)

    @blueprint.route("/profile/edit", methods=["GET", "POST"])
    async def edit() -> str | Response:
        if g.member is None:
            await flash("Sign in first.", "error")
            return redirect("/signin")
        if request.method == "POST":
            form = await request.form
            new_password = form.get("new_password", "")
            try:
                new_version = await context.accounts.update_credentials(
                    g.member,
                    new_email=form.get("email", "").strip(),
                    new_password=new_password if new_password else None,
                    question_code=form.get("question_code", ""),
                    answer=form.get("answer", ""),
                )
                from ..wiring import issue_session

                issue_session(g.member["_id"], session_version=new_version)
            except Exception as error:  # — flashed, never a trace
                await flash(str(error), "error")
                return redirect("/profile/edit")
            await flash("Profile updated.", "success")
            return redirect("/profile")
        member = await context.members.by_id(g.member["_id"])
        if member is None:
            # Deleted between session resolution and this view: treat as
            # signed out rather than crashing (asserts vanish under -O).
            await flash("Sign in first.", "error")
            return redirect("/signin")
        g.breadcrumbs = [
            ("Home", "/"),
            ("Profile", "/profile"),
            ("Edit", "/profile/edit"),
        ]
        return await render_template(
            "profile_edit.html", member=member, questions=QUESTION_LABELS.items()
        )

    return blueprint
