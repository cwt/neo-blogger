"""Regression tests for bugs 008 (recovery), 009 (sole admin), 012 (config)."""

from pathlib import Path
from typing import Any

from .conftest import body_of, csrf_token_from

RECOVERY_ANSWER = "Snowball"
RECOVERY_PASSWORD = "brand-new-password"


def _write_config(tmp_path: Path, text: str) -> str:
    path = tmp_path / "neo-blogger.toml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_config_bool_as_int_degrades_to_default(tmp_path: Path) -> None:
    from neoblogger.app.config import load_config

    path = _write_config(tmp_path, "[posts]\nper_page = true\n")
    assert load_config(path).posts.per_page == 10


def test_config_zero_and_negative_limits_degrade(tmp_path: Path) -> None:
    from neoblogger.app.config import load_config

    path = _write_config(
        tmp_path,
        "[posts]\nper_page = 0\nmax_per_page = -3\n"
        "[caching]\ntimeout_seconds = -1\nmax_size_mb = 0\n"
        "[uploads]\nmax_body_bytes = -1\n"
        "[application]\nport = 0\n",
    )
    config = load_config(path)
    assert config.posts.per_page == 10
    assert config.posts.max_per_page == 50
    assert config.caching.timeout_seconds == 300
    assert config.caching.max_size_mb == 100
    assert config.uploads.max_body_bytes == 16_777_216
    assert config.application.port == 8000


def test_config_port_above_max_degrades(tmp_path: Path) -> None:
    from neoblogger.app.config import load_config

    path = _write_config(tmp_path, "[application]\nport = 99999\n")
    assert load_config(path).application.port == 8000


def test_config_unknown_storage_degrades_to_memory(tmp_path: Path) -> None:
    from neoblogger.app.config import load_config

    path = _write_config(tmp_path, '[caching]\nstorage = "files"\n')
    assert load_config(path).caching.storage == "memory"


def test_config_numeric_string_degrades_to_default(tmp_path: Path) -> None:
    from neoblogger.app.config import load_config

    path = _write_config(tmp_path, '[posts]\nper_page = "20"\n')
    assert load_config(path).posts.per_page == 10


def test_config_valid_values_still_accepted(tmp_path: Path) -> None:
    from neoblogger.app.config import load_config

    path = _write_config(
        tmp_path,
        "[posts]\nper_page = 20\nmax_per_page = 60\n"
        '[caching]\nstorage = "file"\ntimeout_seconds = 60\n'
        "[application]\nport = 9000\n",
    )
    config = load_config(path)
    assert config.posts.per_page == 20
    assert config.posts.max_per_page == 60
    assert config.caching.storage == "file"
    assert config.caching.timeout_seconds == 60
    assert config.application.port == 9000


def _make_cli_config(tmp_path: Path) -> str:
    db_file = tmp_path / "cli_bug.db"
    cfg_file = tmp_path / "cli_bug.toml"
    cfg_file.write_text(
        "[application]\n"
        'secret_key = "test-secret-key-sufficiently-long-for-testing"\n'
        "\n[database]\n"
        f'path = "{db_file}"\n'
    )
    return str(cfg_file)


async def _create_member(
    parser: Any, cfg: str, name: str, email: str, *flags: str
) -> int:
    from typing import cast

    args = parser.parse_args(
        [
            "-c",
            cfg,
            "create",
            name,
            email,
            "--password",
            "secret123",
            "--answer",
            "fluffy",
            *flags,
        ]
    )
    return cast(int, await args.func(args))


async def test_set_role_rejects_no_publisher_on_sole_admin(
    tmp_path: Path, capsys: Any
) -> None:
    from neoblogger.app.config import load_config
    from neoblogger.app.context import AppContext
    from neoblogger.cli.users import build_parser, resolve_member

    cfg = _make_cli_config(tmp_path)
    parser = build_parser()
    assert await _create_member(parser, cfg, "alice", "alice@example.com") == 0

    args = parser.parse_args(["-c", cfg, "set-role", "alice", "--no-publisher"])
    assert await args.func(args) == 1
    assert "sole administrator must remain a publisher" in capsys.readouterr().err

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        alice = await resolve_member(context, "alice")
        assert alice is not None
        assert alice["publisher"] is True
    finally:
        await context.close()


async def test_demote_leaves_sole_admin_as_publisher(tmp_path: Path) -> None:
    from neoblogger.app.config import load_config
    from neoblogger.app.context import AppContext
    from neoblogger.cli.users import build_parser, resolve_member

    cfg = _make_cli_config(tmp_path)
    parser = build_parser()
    assert await _create_member(parser, cfg, "alice", "alice@example.com") == 0
    assert await _create_member(parser, cfg, "bob", "bob@example.com", "--admin") == 0

    args = parser.parse_args(["-c", cfg, "set-role", "alice", "--no-admin"])
    assert await args.func(args) == 0

    context = AppContext.build(load_config(cfg))
    try:
        await context.database.start()
        bob = await resolve_member(context, "bob")
        assert bob is not None
        assert bob["administrator"] is True
        assert bob["publisher"] is True
    finally:
        await context.close()


async def test_list_role_author_without_per_member_counts(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    from neoblogger.app.config import load_config
    from neoblogger.app.context import AppContext
    from neoblogger.app.repositories.articles import ArticleRepository
    from neoblogger.cli.users import build_parser

    cfg = _make_cli_config(tmp_path)
    parser = build_parser()
    assert await _create_member(parser, cfg, "alice", "alice@example.com") == 0

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

    async def _forbidden_count(self: Any, author: str) -> dict[str, int]:
        raise AssertionError("per-member count_by_author must not run")

    monkeypatch.setattr(ArticleRepository, "count_by_author", _forbidden_count)
    args = parser.parse_args(["-c", cfg, "list", "--role", "author"])
    assert await args.func(args) == 0
    assert "alice" in capsys.readouterr().out


async def _signup(
    client: Any, display_name: str, email: str, answer: str = RECOVERY_ANSWER
) -> None:
    page = await client.get("/signup")
    token = csrf_token_from(await body_of(page))
    await client.post(
        "/signup",
        form={
            "display_name": display_name,
            "email": email,
            "password": "original-password",
            "question_code": "first-pet",
            "answer": answer,
            "csrftoken": token,
        },
    )


async def test_recover_empty_answer_flashes_required(app: Any) -> None:
    await _signup(app.test_client(), "anna", "anna@example.com")
    client = app.test_client()
    page = await client.get("/recover")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        "/recover",
        form={
            "email": "anna@example.com",
            "answer": "",
            "new_password": RECOVERY_PASSWORD,
            "csrftoken": token,
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/recover"
    flashed = await body_of(await client.get("/recover"))
    assert "Answer is required" in flashed


async def test_recover_empty_password_flashes_required(app: Any) -> None:
    await _signup(app.test_client(), "bert", "bert@example.com")
    client = app.test_client()
    page = await client.get("/recover")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        "/recover",
        form={
            "email": "bert@example.com",
            "answer": RECOVERY_ANSWER,
            "new_password": "",
            "csrftoken": token,
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/recover"
    flashed = await body_of(await client.get("/recover"))
    assert "New password is required" in flashed


async def test_recover_lookups_do_not_consume_verify_budget(app: Any) -> None:
    await _signup(app.test_client(), "cara", "cara@example.com")
    client = app.test_client()
    page = await client.get("/recover")
    token = csrf_token_from(await body_of(page))
    for _ in range(5):
        response = await client.post(
            "/recover",
            form={"email": "cara@example.com", "csrftoken": token},
        )
        assert response.status_code == 200
    verify = await client.post(
        "/recover",
        form={
            "email": "cara@example.com",
            "answer": RECOVERY_ANSWER,
            "new_password": RECOVERY_PASSWORD,
            "csrftoken": token,
        },
    )
    assert verify.status_code == 302
    assert verify.headers["Location"] == "/signin"
