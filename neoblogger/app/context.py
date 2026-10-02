"""Per-application context (tech-req §3.4): assembled repositories and services."""

from dataclasses import dataclass

from .config import RuntimeConfig
from .repositories.articles import ArticleRepository
from .repositories.comments import CommentRepository
from .repositories.db import Database
from .repositories.members import MemberRepository
from .repositories.meta import MetaRepository
from .repositories.objects import ObjectRepository
from .security.sessions import SessionCodec
from .services.accounts import AccountService
from .services.articles import ArticleService
from .services.auth import AuthService
from .services.comments import CommentService
from .services.visibility import ArticleVisibility

__all__ = ["AppContext"]


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
        visibility = ArticleVisibility(members, articles, comments)
        accounts = AccountService(members, comments, visibility)
        article_service = ArticleService(articles, members, meta, visibility)
        comment_service = CommentService(comments, articles, meta)
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
        )
