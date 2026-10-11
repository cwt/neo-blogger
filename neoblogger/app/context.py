"""Per-application context (tech-req §3.4): assembled repositories and services."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, TypeVar

from .config import RuntimeConfig
from .repositories.articles import ArticleRepository
from .repositories.comments import CommentRepository
from .repositories.db import Database
from .repositories.members import MemberRepository
from .repositories.meta import MetaRepository
from .repositories.objects import ObjectRepository
from .security.proxy import ProxyTrust
from .security.sessions import SessionCodec
from .services.accounts import AccountService
from .services.articles import ArticleService
from .services.auth import AuthService
from .services.cache import ResponseCache
from .services.comments import CommentService
from .services.objects import ObjectsService
from .services.visibility import ArticleVisibility

__all__ = ["AppContext"]


T = TypeVar("T")


def _image_runner(
    executor: ThreadPoolExecutor,
) -> Callable[[Callable[[], T]], Any]:
    """An async runner for the image executor (§5.6)."""

    async def run(work: Callable[[], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, work)

    return run


@dataclass(slots=True)
class AppContext:
    """Everything a blueprint needs; the DB connection starts lazily."""

    config: RuntimeConfig
    database: Database
    members: MemberRepository
    articles: ArticleRepository
    comments: CommentRepository
    objects: ObjectRepository
    meta: MetaRepository
    codec: SessionCodec
    auth: AuthService
    accounts: AccountService
    visibility: ArticleVisibility
    article_service: ArticleService
    comment_service: CommentService
    objects_service: ObjectsService
    image_executor: ThreadPoolExecutor
    response_cache: ResponseCache | None = None
    proxy_trust: ProxyTrust = field(default_factory=ProxyTrust)

    async def run_image(self, work: Callable[[], T]) -> T:
        """Offload CPU-bound Pillow work to the image executor (§5.6)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.image_executor, work)

    async def close(self) -> None:
        """Stop executors; used by tests and graceful shutdown."""
        await self.database.close()
        self.image_executor.shutdown(wait=True)

    @classmethod
    def build(cls, config: RuntimeConfig) -> AppContext:
        database = Database(config.database)
        members = MemberRepository(database)
        articles = ArticleRepository(database)
        comments = CommentRepository(database)
        objects = ObjectRepository(database)
        meta = MetaRepository(database)
        codec = SessionCodec(config.application.secret_key)
        auth = AuthService(codec)
        visibility = ArticleVisibility(articles, comments)
        accounts = AccountService(members, comments, visibility)
        article_service = ArticleService(articles, members, meta, visibility)
        comment_service = CommentService(comments, articles, meta)
        image_executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="neoblogger-image"
        )
        objects_service = ObjectsService(
            objects,
            articles,
            _image_runner(image_executor),
            config.uploads.max_body_bytes,
        )
        proxy_trust = ProxyTrust(tuple(config.proxy.trusted_proxies))
        return cls(
            config=config,
            database=database,
            members=members,
            articles=articles,
            comments=comments,
            objects=objects,
            meta=meta,
            codec=codec,
            auth=auth,
            accounts=accounts,
            visibility=visibility,
            article_service=article_service,
            comment_service=comment_service,
            objects_service=objects_service,
            image_executor=image_executor,
            proxy_trust=proxy_trust,
        )
