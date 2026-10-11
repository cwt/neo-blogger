"""Service tests: visibility rules and account workflows (spec §2, §4, §13)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from neoblogger.app.config import DatabaseConfig
from neoblogger.app.repositories.articles import ArticleRepository
from neoblogger.app.repositories.comments import CommentRepository
from neoblogger.app.repositories.db import Database
from neoblogger.app.repositories.members import MemberRepository
from neoblogger.app.repositories.meta import MetaRepository
from neoblogger.app.services.accounts import AccountDisabledError, AccountService
from neoblogger.app.services.visibility import (
    ArticleVisibility,
    feed_filter,
    tag_filter,
)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(DatabaseConfig(path=str(tmp_path / "svc.db")))
    await database.start()
    yield database
    await database.close()


@pytest.fixture
def services(database: Database) -> dict[str, Any]:
    members = MemberRepository(database)
    comments = CommentRepository(database)
    articles = ArticleRepository(database)
    visibility = ArticleVisibility(members, articles, comments)
    accounts = AccountService(members, comments, visibility)
    meta = MetaRepository(database)
    return {
        "members": members,
        "articles": articles,
        "comments": comments,
        "visibility": visibility,
        "accounts": accounts,
        "meta": meta,
    }


def test_public_feed_filter_shape() -> None:
    viewer_filter = feed_filter(None)
    assert viewer_filter == {
        "status": "published",
        "author_active": True,
        "author_publisher": True,
    }


def test_admin_feed_filter_broader() -> None:
    admin: dict[str, Any] = {
        "_id": "a",
        "display_name": "root",
        "email": "r@x.io",
        "password_hash": "h",
        "security_question_code": "first-pet",
        "security_answer_hash": "h",
        "active": True,
        "administrator": True,
        "publisher": True,
    }
    assert feed_filter(admin) == {"status": "published"}


def test_security_question_labels_match_codes() -> None:
    from neoblogger.app.services.accounts import (
        SECURITY_QUESTION_LABELS,
        SECURITY_QUESTIONS,
    )

    assert tuple(SECURITY_QUESTION_LABELS) == SECURITY_QUESTIONS
    assert len(SECURITY_QUESTIONS) == 7


def test_tag_filter_scopes() -> None:
    admin: dict[str, Any] = {
        "_id": "a",
        "display_name": "root",
        "email": "r@x.io",
        "password_hash": "h",
        "security_question_code": "first-pet",
        "security_answer_hash": "h",
        "active": True,
        "administrator": True,
        "publisher": True,
    }
    admin_tagged = tag_filter(admin, "python")
    assert "status" not in admin_tagged["$and"][0]
    assert admin_tagged["$and"][1] == {"tags": "python"}


async def test_first_member_becomes_admin_and_publisher(
    services: dict[str, Any],
) -> None:
    accounts: AccountService = services["accounts"]
    first_id, promoted = await accounts.register(
        "root", "root@x.io", "pw", "first-pet", "City"
    )
    assert promoted is True
    member = await services["members"].by_id(first_id)
    assert member is not None
    assert member["administrator"] is True
    assert member["publisher"] is True
    second_id, promoted_second = await accounts.register(
        "user", "user@x.io", "pw", "first-pet", "Town"
    )
    assert promoted_second is False
    second = await services["members"].by_id(second_id)
    assert second is not None
    assert second["administrator"] is False


async def test_register_rejects_duplicate_email(
    services: dict[str, Any],
) -> None:
    from neoblogger.app.repositories.members import MemberAlreadyExistsError

    accounts: AccountService = services["accounts"]
    await accounts.register("root", "root@x.io", "pw", "first-pet", "City")
    with pytest.raises(MemberAlreadyExistsError):
        await accounts.register("twin", "root@x.io", "pw", "first-pet", "City")


async def test_authenticate_paths(services: dict[str, Any]) -> None:
    accounts: AccountService = services["accounts"]
    await accounts.register("root", "root@x.io", "pw", "first-pet", "City")
    member = await accounts.authenticate("root@x.io", "pw")
    assert member is not None
    assert member["display_name"] == "root"
    assert await accounts.authenticate("root@x.io", "wrong") is None
    assert await accounts.authenticate("ghost@x.io", "pw") is None


async def test_disabled_account_refused(services: dict[str, Any]) -> None:
    accounts: AccountService = services["accounts"]
    members: MemberRepository = services["members"]
    member_id, _ = await accounts.register(
        "root", "root@x.io", "pw", "first-pet", "City"
    )
    await members.set_active(member_id, False)
    with pytest.raises(AccountDisabledError):
        await accounts.authenticate("root@x.io", "pw")
    with pytest.raises(AccountDisabledError):
        await accounts.recover("root@x.io", "city", "new")


async def test_recovery_flow(services: dict[str, Any]) -> None:
    accounts: AccountService = services["accounts"]
    await accounts.register("root", "root@x.io", "pw", "first-pet", "Snowball")
    assert await accounts.recover("root@x.io", "snowball", "newpw") is True
    member = await accounts.authenticate("root@x.io", "newpw")
    assert member is not None
    assert await accounts.recover("root@x.io", "wrong", "x") is False
    assert await accounts.recover("ghost@x.io", "x", "y") is False


async def test_profile_statistics(services: dict[str, Any]) -> None:
    accounts: AccountService = services["accounts"]
    member_id, _ = await accounts.register(
        "root", "root@x.io", "pw", "first-pet", "City"
    )
    member = await services["members"].by_id(member_id)
    assert member is not None
    stats = await accounts.profile_statistics(member)
    assert stats == {
        "published": 0,
        "drafts": 0,
        "comments_written": 0,
        "contributions": 0,
    }


async def test_edit_resyncs_author_snapshots(services: dict[str, Any]) -> None:
    from neoblogger.app.services.articles import ArticleService

    article_service = ArticleService(
        services["articles"],
        services["members"],
        services["meta"],
        services["visibility"],
    )
    member_id, _ = await services["accounts"].register(
        "root", "root@x.io", "pw", "first-pet", "City"
    )
    assert member_id is not None
    writer_id, _ = await services["accounts"].register(
        "writer", "writer@x.io", "pw", "first-pet", "Town"
    )
    member = await services["members"].by_id(writer_id)
    assert member is not None
    assert member["publisher"] is False
    article_id = await article_service.save(
        member,
        article_id=None,
        title="T",
        subtitle="s",
        body="body",
        cover_url="",
        tags_raw="",
        publish=False,
    )
    # The writer gains publisher status; editing must refresh the snapshot.
    await services["members"].set_publisher(writer_id, True)
    member = await services["members"].by_id(writer_id)
    assert member is not None
    await article_service.save(
        member,
        article_id=article_id,
        title="T",
        subtitle="s",
        body="body",
        cover_url="",
        tags_raw="",
        publish=False,
    )
    fetched = await services["articles"].by_id(article_id)
    assert fetched is not None
    assert fetched["author_publisher"] is True


async def test_admin_edit_keeps_owner_snapshots(services: dict[str, Any]) -> None:
    from neoblogger.app.services.articles import ArticleService

    article_service = ArticleService(
        services["articles"],
        services["members"],
        services["meta"],
        services["visibility"],
    )
    owner_id, _ = await services["accounts"].register(
        "root", "root@x.io", "pw", "first-pet", "City"
    )
    assert owner_id is not None
    writer_id, _ = await services["accounts"].register(
        "writer", "writer@x.io", "pw", "first-pet", "Town"
    )
    owner = await services["members"].by_id(writer_id)
    assert owner is not None
    article_id = await article_service.save(
        owner,
        article_id=None,
        title="T",
        subtitle="s",
        body="body",
        cover_url="",
        tags_raw="",
        publish=False,
    )
    admin = dict(owner)
    admin["display_name"] = "root"
    admin["administrator"] = True
    admin["publisher"] = True
    await article_service.save(
        admin,  # type: ignore[arg-type]
        article_id=article_id,
        title="T edited",
        subtitle="s",
        body="body",
        cover_url="",
        tags_raw="",
        publish=False,
    )
    fetched = await services["articles"].by_id(article_id)
    assert fetched is not None
    assert fetched["title"] == "T edited"
    assert fetched["author"] == "writer"
    assert fetched["author_publisher"] is False
