"""Auth pages: registration, sign-in, sign-out, recovery (spec §4)."""

from quart import Blueprint, flash, redirect, render_template, request
from werkzeug.wrappers import Response

from ..context import AppContext

__all__ = ["create_auth_blueprint"]

QUESTION_LABELS: dict[str, str] = {
    "first-pet": "What was your first pet's name?",
    "elementary-school": "Which elementary school did you attend?",
    "birth-city": "In which city were you born?",
    "mothers-maiden-name": "What is your mother's maiden name?",
    "favorite-book": "Which book is your favorite?",
    "favorite-food": "Which food is your favorite?",
    "first-car": "What was your first car?",
}


def create_auth_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("auth", __name__)

    @blueprint.route("/signup", methods=["GET", "POST"])
    async def signup() -> str | Response:
        if request.method == "POST":
            form = await request.form
            try:
                member_id, promoted = await context.accounts.register(
                    form.get("display_name", "").strip(),
                    form.get("email", "").strip(),
                    form.get("password", ""),
                    form.get("question_code", ""),
                    form.get("answer", ""),
                )
            except Exception as error:
                await flash(str(error), "error")
                return redirect("/signup")
            from ..wiring import issue_session

            issue_session(member_id)
            await flash("Welcome! Your account has been created.", "success")
            if promoted:
                await flash(
                    "You are the first member: administrator and publisher.",
                    "success",
                )
            return redirect("/profile")
        return await render_template("register.html", questions=QUESTION_LABELS.items())

    @blueprint.route("/signin", methods=["GET", "POST"])
    async def signin() -> str | Response:
        if request.method == "POST":
            form = await request.form
            try:
                member = await context.accounts.authenticate(
                    form.get("email", "").strip(), form.get("password", "")
                )
            except Exception as error:
                await flash(str(error), "error")
                return redirect("/signin")
            if member is None:
                await flash("Sign-in failed. Check your email and password.", "error")
                return redirect("/signin")
            from ..wiring import issue_session

            issue_session(member["_id"])
            await flash("Signed in.", "success")
            return redirect("/profile")
        return await render_template("sign_in.html")

    @blueprint.route("/signout", methods=["POST"])
    async def signout() -> Response:
        from ..wiring import drop_session

        drop_session()
        await flash("Signed out.", "success")
        return redirect("/")

    @blueprint.route("/recover", methods=["GET", "POST"])
    async def recover() -> str | Response:
        from ..wiring import recovery_limiter_allow

        email = ""
        question = None
        if request.method == "POST":
            form = await request.form
            email = form.get("email", "").strip()
            if not recovery_limiter_allow(request.remote_addr or "", email.lower()):
                await flash("Too many attempts. Try again later.", "error")
                return redirect("/recover")
            member = await context.members.by_email(email)
            if member is None:
                await flash("No account found with that email address.", "error")
                return redirect("/recover")
            question = QUESTION_LABELS.get(member["security_question_code"])
            if form.get("answer"):
                ok = await context.accounts.recover(
                    email, form.get("answer", ""), form.get("new_password", "")
                )
                if ok:
                    await flash("Password reset. You can now sign in.", "success")
                    return redirect("/signin")
                await flash("The answer did not match. Try again.", "error")
        return await render_template("recovery.html", email=email, question=question)

    return blueprint
