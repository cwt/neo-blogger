"""Repository tests: members, meta, comments (tech-req §5)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.db import Database
from neoblogger.app.repositories.members import (
    MemberAlreadyExistsError,
    MemberRepository,
)
from neoblogger.app.repositories.meta import MetaRepository


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(DatabaseConfig(path=str(tmp_path / "repo.db")))
    await database.start()
    yield database
    await database.close()


@pytest.fixture
def members(database: Database) -> MemberRepository:
    return MemberRepository(database)


@pytest.fixture
def meta(database: Database) -> MetaRepository:
    return MetaRepository(database)


def credentials(name: str) -> dict[str, str]:
    return {
        "email": f"{name}@example.com",
        "password_hash": f"hash-{name}",
        "security_question_code": "first-pet",
        "security_answer_hash": f"answer-{name}",
    }


async def test_member_create_returns_hex_id(members: MemberRepository) -> None:
    creds = credentials("alice")
    member_id = await members.create(
        "alice",
        creds["email"],
        creds["password_hash"],
        creds["security_question_code"],
        creds["security_answer_hash"],
    )
    assert len(member_id) == 24
    assert all(character in "0123456789abcdef" for character in member_id)


async def test_member_duplicate_display_name(members: MemberRepository) -> None:
    creds = credentials("alice")
    await members.create(
        "alice", creds["email"], creds["password_hash"], "first-pet", "answer"
    )
    with pytest.raises(MemberAlreadyExistsError):
        await members.create("alice", "other@example.com", "h", "first-pet", "a")


async def test_member_lookup_paths(members: MemberRepository) -> None:
    creds = credentials("bob")
    member_id = await members.create(
        "bob", creds["email"], creds["password_hash"], "first-pet", "answer"
    )
    by_id = await members.by_id(member_id)
    assert by_id is not None
    assert by_id["display_name"] == "bob"
    assert by_id["_id"] == member_id
    assert by_id["active"] is True
    by_name = await members.by_display_name("BOB".lower())
    assert by_name is not None
    by_email = await members.by_email("bob@example.com")
    assert by_email is not None
    assert await members.by_id("ffffffffffffffffffffffff") is None
    assert await members.by_display_name("nobody") is None


async def test_member_flag_toggles(members: MemberRepository) -> None:
    member_id = await members.create("carol", "c@x.io", "h", "first-pet", "a")
    await members.set_publisher(member_id, True)
    publisher = await members.by_id(member_id)
    assert publisher is not None
    assert publisher["publisher"] is True
    await members.set_publisher(member_id, False)
    revoked = await members.by_id(member_id)
    assert revoked is not None
    assert revoked["publisher"] is False


async def test_member_flag_validation(members: MemberRepository) -> None:
    member_id = await members.create("dave", "d@x.io", "h", "first-pet", "a")
    with pytest.raises(ValueError):
        await members.set_flag(member_id, "email", True)


async def test_member_credential_rotation(members: MemberRepository) -> None:
    member_id = await members.create("erin", "e@x.io", "h1", "first-pet", "a1")
    await members.update_credentials(
        member_id,
        email="erin2@x.io",
        password_hash="h2",
        security_question_code="first-car",
        security_answer_hash="a2",
    )
    rotated = await members.by_id(member_id)
    assert rotated is not None
    assert rotated["email"] == "erin2@x.io"
    assert rotated["password_hash"] == "h2"
    assert rotated["security_question_code"] == "first-car"
    assert rotated["display_name"] == "erin"


async def test_member_all_and_exists(members: MemberRepository) -> None:
    assert await members.exists_any() is False
    for name in ("frank", "grace"):
        await members.create(name, f"{name}@x.io", "h", "first-pet", "a")
    assert await members.exists_any() is True
    roster = await members.all()
    assert [member["display_name"] for member in roster] == ["grace", "frank"]


async def test_meta_version_bumps(meta: MetaRepository) -> None:
    assert await meta.content_version() == 0
    assert await meta.bump_content_version() == 1
    assert await meta.bump_content_version() == 2
    assert await meta.content_version() == 2


async def test_meta_version_self_heals_when_missing(
    meta: MetaRepository, database: Database
) -> None:
    def wipe() -> None:
        database.connection.meta.delete_many({})

    await database.run(wipe)
    assert await meta.content_version() == 0
    assert await meta.bump_content_version() == 1
    assert await meta.content_version() == 1
