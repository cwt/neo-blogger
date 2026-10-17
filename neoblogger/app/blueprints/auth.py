"""Auth pages: registration, sign-in, sign-out, recovery (spec §4)."""

from typing import Any

from quart import Blueprint, flash, redirect, render_template, request
from werkzeug.wrappers import Response

from ..context import AppContext
from ..services.accounts import SECURITY_QUESTION_LABELS as QUESTION_LABELS
from ..services.accounts import AccountDisabledError

__all__ = ["create_auth_blueprint"]


async def _find_recovery_member(
    context: AppContext, email: str
) -> tuple[Any | None, str | None]:
    """Look up the recovery member; returns (member, error-flash)."""
    member = await context.members.by_email(email)
    if member is None:
        return None, "No account found with that email address."
    if not member["active"]:
        return (
            None,
            "This account is disabled. Please contact an administrator.",
        )
    return member, None


async def _verify_recovery_answer(
    context: AppContext, email: str, answer: str, new_password: str
) -> tuple[str | None, str, str]:
    """Verify the answer; returns (redirect-to, flash-text, category).

    An empty redirect-to means re-render the recovery page (wrong answer).
    """
    if not answer.strip():
        return "/recover", "Answer is required", "error"
    if not new_password:
        return "/recover", "New password is required", "error"
    if len(new_password) < 8:
        return "/recover", "New password must be at least 8 characters", "error"
    try:
        ok = await context.accounts.recover(email, answer, new_password)
    except AccountDisabledError:
        return (
            "/recover",
            "This account is disabled. Please contact an administrator.",
            "error",
        )
    if ok:
        return "/signin", "Password reset. You can now sign in.", "success"
    return "", "The answer did not match. Try again.", "error"


def create_auth_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("auth", __name__)

    @blueprint.route("/signup", methods=["GET", "POST"])
    async def signup() -> str | Response:
        if request.method == "POST":
            form = await request.form
            from ..wiring import (
                issue_session,
                request_client,
                signup_limiter_allow,
            )

            email = form.get("email", "").strip()
            if not signup_limiter_allow(
                request_client(context.proxy_trust), email.lower()
            ):
                await flash("Too many attempts. Please wait a few minutes.", "error")
                return redirect("/signup")
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
            from ..wiring import (
                issue_session,
                request_client,
                signin_limiter_allow,
            )

            email = form.get("email", "").strip()
            if not signin_limiter_allow(
                request_client(context.proxy_trust), email.lower()
            ):
                await flash("Too many attempts. Try again later.", "error")
                return redirect("/signin")
            try:
                member = await context.accounts.authenticate(
                    email, form.get("password", "")
                )
            except AccountDisabledError:
                await flash(
                    "This account is disabled. Please contact an administrator.",
                    "error",
                )
                return redirect("/signin")
            except Exception as error:
                await flash(str(error), "error")
                return redirect("/signin")
            if member is None:
                await flash("Sign-in failed. Check your email and password.", "error")
                return redirect("/signin")

            issue_session(
                member["_id"],
                session_version=member.get("session_version", 1),
            )
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
        from ..wiring import recovery_limiter_allow, request_client

        email = ""
        question = None
        if request.method == "POST":
            form = await request.form
            email = form.get("email", "").strip()
            verify = "answer" in form
            step = "verify" if verify else "lookup"
            if not recovery_limiter_allow(
                request_client(context.proxy_trust), f"{email.lower()}#{step}"
            ):
                await flash("Too many attempts. Try again later.", "error")
                return redirect("/recover")
            member, lookup_error = await _find_recovery_member(context, email)
            if member is None:
                assert lookup_error is not None
                await flash(lookup_error, "error")
                return redirect("/recover")
            question = QUESTION_LABELS.get(member["security_question_code"])
            if verify:
                target, message, category = await _verify_recovery_answer(
                    context,
                    email,
                    form.get("answer", ""),
                    form.get("new_password", ""),
                )
                await flash(message, category)
                if target:
                    return redirect(target)
        return await render_template("recovery.html", email=email, question=question)

    return blueprint
