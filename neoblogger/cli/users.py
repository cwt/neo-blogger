"""Member management CLI (tech-req §3.2, §5.7).

Usage:
    uv run python -m neoblogger.cli.users list [--status ...] [--role ...] [--json]
    uv run python -m neoblogger.cli.users show <identifier> [--json]
    uv run python -m neoblogger.cli.users create <display_name> <email> [options]
    uv run python -m neoblogger.cli.users enable <identifier>
    uv run python -m neoblogger.cli.users disable <identifier>
    uv run python -m neoblogger.cli.users set-role <identifier>
        [--admin/--no-admin] [--publisher/--no-publisher]
    uv run python -m neoblogger.cli.users set-password <identifier> [--password ...]
    uv run python -m neoblogger.cli.users set-email <identifier> <new_email>

Where <identifier> can be a display name, an email address, or a 24-character hex ID.
"""

import argparse
import asyncio
import getpass
import json
import sys
from collections.abc import Callable, Coroutine
from typing import Any

from ..app.config import load_config
from ..app.context import AppContext
from ..app.repositories.documents import MemberDocument
from ..app.repositories.members import MemberAlreadyExistsError
from ..app.security.hashing import hash_secret, normalize_answer
from ..app.services.accounts import SECURITY_QUESTIONS

__all__ = ["build_parser", "main", "resolve_member"]


async def resolve_member(context: AppContext, identifier: str) -> MemberDocument | None:
    """Find a member by hex ID, display name, or email address.

    Emails are stored lowercased, so email-shaped identifiers match
    regardless of case; display names stay case-sensitive.
    """
    if len(identifier) == 24:
        try:
            int(identifier, 16)
            by_id = await context.members.by_id(identifier)
            if by_id is not None:
                return by_id
        except ValueError:
            pass
    by_name = await context.members.by_display_name(identifier)
    if by_name is not None:
        return by_name
    email = identifier.lower() if "@" in identifier else identifier
    return await context.members.by_email(email)


async def _run_list(args: argparse.Namespace) -> int:
    context = AppContext.build(load_config(args.config))
    try:
        await context.database.start()
        members = await context.members.all()
        filtered: list[MemberDocument] = []
        for member in members:
            if args.status == "active" and not member["active"]:
                continue
            if args.status == "disabled" and member["active"]:
                continue
            if args.role == "admin" and not member["administrator"]:
                continue
            if args.role == "publisher" and not member["publisher"]:
                continue
            if args.role == "author" and (
                member["administrator"] or member["publisher"]
            ):
                continue
            filtered.append(member)

        if args.json:
            records = [
                {
                    "id": m["_id"],
                    "display_name": m["display_name"],
                    "email": m["email"],
                    "active": m["active"],
                    "administrator": m["administrator"],
                    "publisher": m["publisher"],
                    "security_question_code": m["security_question_code"],
                }
                for m in filtered
            ]
            print(json.dumps(records, indent=2))
            return 0

        if not filtered:
            print("No members found.")
            return 0

        header = (
            f"{'ID':<24}  {'DISPLAY NAME':<20}  {'EMAIL':<28}  "
            f"{'ACTIVE':<6}  {'ADMIN':<5}  {'PUBLISHER':<9}"
        )
        print(header)
        print("-" * len(header))
        for m in filtered:
            active_s = "yes" if m["active"] else "no"
            admin_s = "yes" if m["administrator"] else "no"
            pub_s = "yes" if m["publisher"] else "no"
            print(
                f"{m['_id']:<24}  {m['display_name']:<20}  {m['email']:<28}  "
                f"{active_s:<6}  {admin_s:<5}  {pub_s:<9}"
            )
        return 0
    finally:
        await context.close()


async def _run_show(args: argparse.Namespace) -> int:
    context = AppContext.build(load_config(args.config))
    try:
        await context.database.start()
        member = await resolve_member(context, args.identifier)
        if member is None:
            print(f"Member {args.identifier!r} not found.", file=sys.stderr)
            return 1
        stats = await context.accounts.profile_statistics(member)
        if args.json:
            doc = {
                "id": member["_id"],
                "display_name": member["display_name"],
                "email": member["email"],
                "active": member["active"],
                "administrator": member["administrator"],
                "publisher": member["publisher"],
                "security_question_code": member["security_question_code"],
                "statistics": stats,
            }
            print(json.dumps(doc, indent=2))
            return 0

        print(f"Member: {member['display_name']}")
        print(f"  ID:                     {member['_id']}")
        print(f"  Email:                  {member['email']}")
        print(f"  Active:                 {'yes' if member['active'] else 'no'}")
        print(f"  Administrator:          {'yes' if member['administrator'] else 'no'}")
        print(f"  Publisher:              {'yes' if member['publisher'] else 'no'}")
        print(f"  Security question code: {member['security_question_code']}")
        print("  Statistics:")
        print(f"    Published articles:   {stats['published']}")
        print(f"    Drafts:               {stats['drafts']}")
        print(f"    Comments written:     {stats['comments_written']}")
        print(f"    Total contributions:  {stats['contributions']}")
        return 0
    finally:
        await context.close()


def _read_secret(prompt: str) -> str:
    """Read a secret from the terminal, or the first stdin line piped in.

    Empty input yields an empty string so callers reject it; there is no
    fallback value that could silently become a weak known secret.
    """
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    return sys.stdin.readline().strip()


async def _run_create(args: argparse.Namespace) -> int:
    context = AppContext.build(load_config(args.config))
    try:
        await context.database.start()
        display_name: str = args.display_name.strip()
        email: str = args.email.strip().lower()
        if not display_name:
            print("Display name cannot be empty.", file=sys.stderr)
            return 1
        if not email:
            print("Email cannot be empty.", file=sys.stderr)
            return 1

        password: str | None = args.password
        if password is None:
            password = _read_secret("Password: ")
        if not password:
            print("Password cannot be empty.", file=sys.stderr)
            return 1

        question_code: str = args.question
        if question_code not in SECURITY_QUESTIONS:
            print(
                f"Invalid question code {question_code!r}. "
                f"Must be one of: {', '.join(SECURITY_QUESTIONS)}",
                file=sys.stderr,
            )
            return 1

        answer: str | None = args.answer
        if answer is None:
            answer = _read_secret(f"Security answer for '{question_code}': ")
        if not answer.strip():
            print("Security answer cannot be empty.", file=sys.stderr)
            return 1

        is_first = not await context.members.exists_any()
        if is_first:
            is_admin = True if args.admin is None else bool(args.admin)
            is_publisher = True if args.publisher is None else bool(args.publisher)
        else:
            is_admin = bool(args.admin)
            is_publisher = bool(args.publisher)

        password_hash = hash_secret(password)
        answer_hash = hash_secret(normalize_answer(answer))
        try:
            member_id = await context.members.create(
                display_name=display_name,
                email=email,
                password_hash=password_hash,
                security_question_code=question_code,
                security_answer_hash=answer_hash,
                administrator=is_admin,
                publisher=is_publisher,
            )
        except MemberAlreadyExistsError as err:
            print(f"Error: {err}", file=sys.stderr)
            return 1

        if is_admin or is_publisher:
            await context.meta.bump_content_version()

        print(f"Created member {display_name!r} ({member_id}).")
        roles: list[str] = []
        if is_admin:
            roles.append("administrator")
        if is_publisher:
            roles.append("publisher")
        if roles:
            print(f"  Roles: {', '.join(roles)}")
        return 0
    finally:
        await context.close()


async def _run_enable(args: argparse.Namespace) -> int:
    context = AppContext.build(load_config(args.config))
    try:
        await context.database.start()
        member = await resolve_member(context, args.identifier)
        if member is None:
            print(f"Member {args.identifier!r} not found.", file=sys.stderr)
            return 1
        await context.members.set_active(member["_id"], True)
        updated = await context.members.by_id(member["_id"])
        if updated is not None:
            await context.visibility.resync_author_articles(updated)
        await context.meta.bump_content_version()
        print(f"Member {member['display_name']!r} enabled.")
        return 0
    finally:
        await context.close()


async def _run_disable(args: argparse.Namespace) -> int:
    context = AppContext.build(load_config(args.config))
    try:
        await context.database.start()
        member = await resolve_member(context, args.identifier)
        if member is None:
            print(f"Member {args.identifier!r} not found.", file=sys.stderr)
            return 1
        if member["administrator"]:
            stats = await context.members.dashboard()
            if stats["admins"] <= 1:
                name = member["display_name"]
                print(
                    f"Cannot disable the sole administrator {name!r}.",
                    file=sys.stderr,
                )
                return 1
        await context.members.set_active(member["_id"], False)
        updated = await context.members.by_id(member["_id"])
        if updated is not None:
            await context.visibility.resync_author_articles(updated)
        await context.meta.bump_content_version()
        print(f"Member {member['display_name']!r} disabled.")
        return 0
    finally:
        await context.close()


async def _run_set_role(args: argparse.Namespace) -> int:
    if args.admin is None and args.publisher is None:
        print(
            "No role flag specified. "
            "Use --admin/--no-admin or --publisher/--no-publisher.",
            file=sys.stderr,
        )
        return 1

    context = AppContext.build(load_config(args.config))
    try:
        await context.database.start()
        member = await resolve_member(context, args.identifier)
        if member is None:
            print(f"Member {args.identifier!r} not found.", file=sys.stderr)
            return 1
        if args.admin is not None:
            if not args.admin and member["administrator"]:
                stats = await context.members.dashboard()
                if stats["admins"] <= 1:
                    name = member["display_name"]
                    print(
                        f"Cannot demote the sole administrator {name!r}.",
                        file=sys.stderr,
                    )
                    return 1
            await context.members.set_administrator(member["_id"], args.admin)
        if args.publisher is not None:
            await context.members.set_publisher(member["_id"], args.publisher)
        updated = await context.members.by_id(member["_id"])
        if updated is not None:
            await context.visibility.resync_author_articles(updated)
        await context.meta.bump_content_version()
        if updated is not None:
            print(
                f"Updated roles for {member['display_name']!r}: "
                f"admin={updated['administrator']}, publisher={updated['publisher']}."
            )
        return 0
    finally:
        await context.close()


async def _run_set_password(args: argparse.Namespace) -> int:
    context = AppContext.build(load_config(args.config))
    try:
        await context.database.start()
        member = await resolve_member(context, args.identifier)
        if member is None:
            print(f"Member {args.identifier!r} not found.", file=sys.stderr)
            return 1
        password: str | None = args.password
        if password is None:
            password = _read_secret("New password: ")
        if not password:
            print("Password cannot be empty.", file=sys.stderr)
            return 1
        password_hash = hash_secret(password)
        await context.members.update_credentials(
            member["_id"],
            email=member["email"],
            password_hash=password_hash,
            security_question_code=member["security_question_code"],
            security_answer_hash=member["security_answer_hash"],
        )
        print(f"Password updated for {member['display_name']!r}.")
        return 0
    finally:
        await context.close()


async def _run_set_email(args: argparse.Namespace) -> int:
    context = AppContext.build(load_config(args.config))
    try:
        await context.database.start()
        member = await resolve_member(context, args.identifier)
        if member is None:
            print(f"Member {args.identifier!r} not found.", file=sys.stderr)
            return 1
        new_email: str = args.new_email.strip().lower()
        if not new_email:
            print("New email cannot be empty.", file=sys.stderr)
            return 1
        existing = await context.members.by_email(new_email)
        if existing is not None and existing["_id"] != member["_id"]:
            print(
                f"Email {new_email!r} is already registered to another member.",
                file=sys.stderr,
            )
            return 1
        try:
            await context.members.update_credentials(
                member["_id"],
                email=new_email,
                password_hash=member["password_hash"],
                security_question_code=member["security_question_code"],
                security_answer_hash=member["security_answer_hash"],
            )
        except MemberAlreadyExistsError:
            print(
                f"Email {new_email!r} is already registered to another member.",
                file=sys.stderr,
            )
            return 1
        print(f"Email updated to {new_email!r} for {member['display_name']!r}.")
        return 0
    finally:
        await context.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neoblogger-users",
        description="Neo-Blogger member and user management CLI.",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="Path to neo-blogger.toml configuration file.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # list
    list_p = subparsers.add_parser("list", help="List registered members.")
    list_p.add_argument(
        "--status",
        choices=["all", "active", "disabled"],
        default="all",
        help="Filter by account status (default: all).",
    )
    list_p.add_argument(
        "--role",
        choices=["all", "admin", "publisher", "author"],
        default="all",
        help="Filter by member role (default: all).",
    )
    list_p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON.",
    )
    list_p.set_defaults(func=_run_list)

    # show
    show_p = subparsers.add_parser("show", help="Show member details and statistics.")
    show_p.add_argument(
        "identifier",
        help="Display name, email address, or 24-character hex ID.",
    )
    show_p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON.",
    )
    show_p.set_defaults(func=_run_show)

    # create
    create_p = subparsers.add_parser("create", help="Create a new member.")
    create_p.add_argument("display_name", help="Display name (immutable).")
    create_p.add_argument("email", help="Email address.")
    create_p.add_argument(
        "--password",
        "-p",
        default=None,
        help="Password (prompted if omitted).",
    )
    create_p.add_argument(
        "--admin",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Administrator role (default: true if first member, else false).",
    )
    create_p.add_argument(
        "--publisher",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Publisher role (default: true if first member, else false).",
    )
    create_p.add_argument(
        "--question",
        "-q",
        choices=SECURITY_QUESTIONS,
        default="first-pet",
        help="Security question code (default: first-pet).",
    )
    create_p.add_argument(
        "--answer",
        "-a",
        default=None,
        help="Security answer (prompted if omitted).",
    )
    create_p.set_defaults(func=_run_create)

    # enable
    enable_p = subparsers.add_parser("enable", help="Enable a member account.")
    enable_p.add_argument(
        "identifier",
        help="Display name, email address, or 24-character hex ID.",
    )
    enable_p.set_defaults(func=_run_enable)

    # disable
    disable_p = subparsers.add_parser("disable", help="Disable a member account.")
    disable_p.add_argument(
        "identifier",
        help="Display name, email address, or 24-character hex ID.",
    )
    disable_p.set_defaults(func=_run_disable)

    # set-role
    role_p = subparsers.add_parser("set-role", help="Update member roles.")
    role_p.add_argument(
        "identifier",
        help="Display name, email address, or 24-character hex ID.",
    )
    role_p.add_argument(
        "--admin",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Set or unset administrator role.",
    )
    role_p.add_argument(
        "--publisher",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Set or unset publisher role.",
    )
    role_p.set_defaults(func=_run_set_role)

    # set-password
    pw_p = subparsers.add_parser(
        "set-password", help="Set or reset a member's password."
    )
    pw_p.add_argument(
        "identifier",
        help="Display name, email address, or 24-character hex ID.",
    )
    pw_p.add_argument(
        "--password",
        "-p",
        default=None,
        help="New password (prompted if omitted).",
    )
    pw_p.set_defaults(func=_run_set_password)

    # set-email
    email_p = subparsers.add_parser("set-email", help="Change a member's email.")
    email_p.add_argument(
        "identifier",
        help="Display name, email address, or 24-character hex ID.",
    )
    email_p.add_argument(
        "new_email",
        help="New email address.",
    )
    email_p.set_defaults(func=_run_set_email)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        sys.exit(2)
    async_runner: Callable[[argparse.Namespace], Coroutine[Any, Any, int]] = func
    exit_code = asyncio.run(async_runner(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
