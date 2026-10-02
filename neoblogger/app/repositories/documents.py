"""Document shapes for the NeoSQLite collections (tech-req §5.2).

TypedDicts describe the normalized repository-level shape: ``_id`` is the
hex-string form (§5.1 ID policy) and is absent on documents not yet saved.
"""

from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict

type ArticleStatus = Literal["draft", "published"]


class MemberDocument(TypedDict):
    """A registered member (spec §12.1)."""

    _id: NotRequired[str]
    display_name: str
    email: str
    password_hash: str
    security_question_code: str
    security_answer_hash: str
    active: bool
    administrator: bool
    publisher: bool


class ArticleDocument(TypedDict):
    """An article in lightweight markup (spec §12.1)."""

    _id: NotRequired[str]
    title: str
    subtitle: str
    body: str
    cover_url: str
    author: str
    created: str
    tags: list[str]
    status: ArticleStatus


class CommentDocument(TypedDict):
    """A comment attached to an article by reference (spec §12.1)."""

    _id: NotRequired[str]
    text: str
    author: str
    article_id: str
    created: str


class MetaDocument(TypedDict):
    """A named value in the ``meta`` collection (tech-req §5.2)."""

    name: str
    value: int


def document_id(document: Mapping[str, object]) -> str:
    """Normalize an engine ``_id`` to a hex string at the boundary (§5.1)."""
    identifier = document.get("_id")
    if isinstance(identifier, str):
        return identifier
    if identifier is None:
        raise KeyError("document has no _id")
    return str(identifier)
