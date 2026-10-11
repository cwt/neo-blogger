"""Member workspace: statistics and posts management (spec §4.5, §4.6)."""

from quart import Blueprint, flash, g, redirect, render_template, request
from werkzeug.wrappers import Response

from ..context import AppContext

__all__ = ["create_profile_blueprint"]

QUESTION_LABELS: dict[str, str] = {
    "first-pet": "What was your first pet's name?",
    "elementary-school": "Which elementary school did you attend?",
    "birth-city": "In which city were you born?",
    "mothers-maiden-name": "What is your mother's maiden name?",
    "favorite-book": "Which book is your favorite?",
    "favorite-food": "Which food is your favorite?",
    "first-car": "What was your first car?",
}


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

    @blueprint.route("/profile/edit", methods=["GET", "POST"])
    async def edit() -> str | Response:
        if g.member is None:
            await flash("Sign in first.", "error")
            return redirect("/signin")
        if request.method == "POST":
            form = await request.form
            new_password = form.get("new_password", "")
            try:
                await context.accounts.update_credentials(
                    g.member,
                    new_email=form.get("email", "").strip(),
                    new_password=new_password if new_password else None,
                    question_code=form.get("question_code", ""),
                    answer=form.get("answer", ""),
                )
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
