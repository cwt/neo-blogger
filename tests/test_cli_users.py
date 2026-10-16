"""Tests for the member management CLI (tech-req §3.2, §5.7)."""

import json
from pathlib import Path

import pytest

from neoblogger.app.config import load_config
from neoblogger.app.context import AppContext
from neoblogger.app.security.hashing import verify_secret
from neoblogger.cli.users import build_parser, resolve_member
from tests.conftest import write_cli_test_config as _make_config


async def test_build_parser_help() -> None:
    parser = build_parser()
    assert parser.prog == "neoblogger-users"


async def test_create_and_resolve_member(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    # First member: automatically promoted to admin and publisher (spec §2)
    args = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    code = await args.func(args)
    assert code == 0

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        by_name = await resolve_member(context, "alice")
        assert by_name is not None
        assert by_name["display_name"] == "alice"
        assert by_name["email"] == "alice@example.com"
        assert by_name["administrator"] is True
        assert by_name["publisher"] is True
        assert by_name["active"] is True

        # Resolve by ID and email
        by_id = await resolve_member(context, by_name["_id"])
        assert by_id is not None
        assert by_id["_id"] == by_name["_id"]

        by_email = await resolve_member(context, "alice@example.com")
        assert by_email is not None
        assert by_email["_id"] == by_name["_id"]

        assert await resolve_member(context, "nonexistent") is None
    finally:
        await context.close()


async def test_create_subsequent_member_regular(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    # Create admin first
    args1 = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args1.func(args1) == 0

    # Second member is regular by default
    args2 = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "bob",
            "bob@example.com",
            "--password",
            "secret456",
            "--answer",
            "rover",
        ]
    )
    assert await args2.func(args2) == 0

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        bob = await resolve_member(context, "bob")
        assert bob is not None
        assert bob["administrator"] is False
        assert bob["publisher"] is False
    finally:
        await context.close()


async def test_create_first_member_forces_admin_and_publisher(
    tmp_path: Path,
) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    # Even with --no-admin and --no-publisher, spec §2 mandates
    # first member is admin & publisher
    args = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
            "--no-admin",
            "--no-publisher",
        ]
    )
    assert await args.func(args) == 0

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        alice = await resolve_member(context, "alice")
        assert alice is not None
        assert alice["administrator"] is True
        assert alice["publisher"] is True
    finally:
        await context.close()


async def test_create_subsequent_member_with_explicit_roles(
    tmp_path: Path,
) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    # Create first member
    args1 = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args1.func(args1) == 0

    # Create subsequent member with --admin and --publisher
    args2 = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "bob",
            "bob@example.com",
            "--password",
            "secret456",
            "--answer",
            "rover",
            "--admin",
            "--publisher",
        ]
    )
    assert await args2.func(args2) == 0

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        bob = await resolve_member(context, "bob")
        assert bob is not None
        assert bob["administrator"] is True
        assert bob["publisher"] is True
    finally:
        await context.close()


async def test_create_duplicate_rejected(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    args1 = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args1.func(args1) == 0

    # Same email
    args2 = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice2",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args2.func(args2) == 1

    # Same display name
    args3 = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "other@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args3.func(args3) == 1


async def test_create_lowercases_email_and_resolves_case_insensitively(
    tmp_path: Path,
) -> None:
    from neoblogger.app.config import load_config
    from neoblogger.app.context import AppContext
    from neoblogger.cli.users import resolve_member

    cfg = _make_config(tmp_path)
    parser = build_parser()
    args = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "Alice@Example.COM",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args.func(args) == 0
    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        stored = await context.members.by_display_name("alice")
        assert stored is not None
        assert stored["email"] == "alice@example.com"
        assert await resolve_member(context, "ALICE@EXAMPLE.COM") is not None
    finally:
        await context.close()


async def test_create_empty_piped_answer_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    cfg = _make_config(tmp_path)
    parser = build_parser()
    args = parser.parse_args(
        ["-c", cfg, "create", "alice", "alice@example.com", "--password", "secret123"]
    )
    assert await args.func(args) == 1


async def test_create_validation_failures(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    # Empty display name
    args1 = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "   ",
            "a@b.com",
            "--password",
            "p",
            "--answer",
            "ans",
        ]
    )
    assert await args1.func(args1) == 1

    # Invalid question code
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "-c",
                cfg,
                "create",
                "alice",
                "a@b.com",
                "--question",
                "invalid-question",
            ]
        )


async def test_list_and_show_members(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    args_create = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args_create.func(args_create) == 0

    # List as table
    args_list = parser.parse_args(["-c", cfg, "list"])
    assert await args_list.func(args_list) == 0
    out = capsys.readouterr().out
    assert "alice" in out
    assert "alice@example.com" in out

    # List as JSON
    args_list_json = parser.parse_args(["-c", cfg, "list", "--json"])
    assert await args_list_json.func(args_list_json) == 0
    out_json = capsys.readouterr().out
    records = json.loads(out_json)
    assert len(records) == 1
    assert records[0]["display_name"] == "alice"

    # List with --role author when alice has written 0 articles
    args_list_author = parser.parse_args(["-c", cfg, "list", "--role", "author"])
    assert await args_list_author.func(args_list_author) == 0
    assert "No members found." in capsys.readouterr().out

    # Add an article written by alice and check --role author again
    from neoblogger.app.config import load_config
    from neoblogger.app.context import AppContext

    context = AppContext.build(load_config(cfg))
    await context.database.start()
    await context.articles.create(
        title="Alice Story",
        subtitle="",
        body="Once upon a time",
        cover_url="",
        author="alice",
        created="2026-10-12T00:00:00",
        tags=[],
        status="published",
        author_active=True,
        author_publisher=True,
    )
    await context.close()

    assert await args_list_author.func(args_list_author) == 0
    assert "alice" in capsys.readouterr().out

    # Show as text
    args_show = parser.parse_args(["-c", cfg, "show", "alice"])
    assert await args_show.func(args_show) == 0
    show_out = capsys.readouterr().out
    assert "Member: alice" in show_out
    assert "Administrator:          yes" in show_out

    # Show as JSON
    args_show_json = parser.parse_args(["-c", cfg, "show", "alice", "--json"])
    assert await args_show_json.func(args_show_json) == 0
    show_json_out = capsys.readouterr().out
    doc = json.loads(show_json_out)
    assert doc["display_name"] == "alice"
    assert "statistics" in doc

    # Show nonexistent
    args_show_none = parser.parse_args(["-c", cfg, "show", "missing"])
    assert await args_show_none.func(args_show_none) == 1


async def test_enable_disable_and_sole_admin_protection(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    # Create sole admin
    args_admin = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args_admin.func(args_admin) == 0

    # Create regular user
    args_user = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "bob",
            "bob@example.com",
            "--password",
            "secret123",
            "--answer",
            "rover",
        ]
    )
    assert await args_user.func(args_user) == 0

    # Disabling sole admin is refused
    args_dis_admin = parser.parse_args(["-c", cfg, "disable", "alice"])
    assert await args_dis_admin.func(args_dis_admin) == 1

    # Disabling bob succeeds
    args_dis_bob = parser.parse_args(["-c", cfg, "disable", "bob"])
    assert await args_dis_bob.func(args_dis_bob) == 0

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        bob = await resolve_member(context, "bob")
        assert bob is not None
        assert bob["active"] is False

        # Re-enabling bob succeeds
        args_en_bob = parser.parse_args(["-c", cfg, "enable", "bob"])
        assert await args_en_bob.func(args_en_bob) == 0
        bob_re = await resolve_member(context, "bob")
        assert bob_re is not None
        assert bob_re["active"] is True
    finally:
        await context.close()


async def test_set_role(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    # Create admin and regular user
    args_admin = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "secret123",
            "--answer",
            "fluffy",
        ]
    )
    assert await args_admin.func(args_admin) == 0

    args_user = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "bob",
            "bob@example.com",
            "--password",
            "secret123",
            "--answer",
            "rover",
        ]
    )
    assert await args_user.func(args_user) == 0

    # Promote bob to publisher and admin
    args_promote = parser.parse_args(
        ["-c", cfg, "set-role", "bob", "--admin", "--publisher"]
    )
    assert await args_promote.func(args_promote) == 0

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        bob = await resolve_member(context, "bob")
        assert bob is not None
        assert bob["administrator"] is True
        assert bob["publisher"] is True

        # Demoting bob back
        args_demote = parser.parse_args(
            ["-c", cfg, "set-role", "bob", "--no-admin", "--no-publisher"]
        )
        assert await args_demote.func(args_demote) == 0
        bob_demoted = await resolve_member(context, "bob")
        assert bob_demoted is not None
        assert bob_demoted["administrator"] is False
        assert bob_demoted["publisher"] is False

        # Sole admin cannot be demoted
        args_demote_alice = parser.parse_args(
            ["-c", cfg, "set-role", "alice", "--no-admin"]
        )
        assert await args_demote_alice.func(args_demote_alice) == 1
    finally:
        await context.close()


async def test_set_password_and_email(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    parser = build_parser()

    args_create = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            "alice",
            "alice@example.com",
            "--password",
            "oldpass",
            "--answer",
            "fluffy",
        ]
    )
    assert await args_create.func(args_create) == 0

    # Set password
    args_pw = parser.parse_args(
        ["-c", cfg, "set-password", "alice", "--password", "newsecret999"]
    )
    assert await args_pw.func(args_pw) == 0

    # Set email
    args_em = parser.parse_args(
        ["-c", cfg, "set-email", "alice", "newalice@example.com"]
    )
    assert await args_em.func(args_em) == 0

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        alice = await resolve_member(context, "alice")
        assert alice is not None
        assert alice["email"] == "newalice@example.com"
        assert verify_secret(alice["password_hash"], "newsecret999")
    finally:
        await context.close()
