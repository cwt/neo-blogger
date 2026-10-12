"""Document shapes for the NeoSQLite collections (tech-req §5.2).

TypedDicts describe the normalized repository-level shape: ``_id`` is the
hex-string form (§5.1 ID policy) and is absent on documents not yet saved.
"""

from collections.abc import Mapping
from typing import Any, Literal, NotRequired, TypedDict

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
    session_version: NotRequired[int]


class ArticleDocument(TypedDict):
    """An article in lightweight markup (spec §12.1).

    ``author_active``/``author_publisher`` are denormalized visibility
    snapshots (§13) kept coherent by role-change resync and a startup
    backfill; they let feed/search filters run as single-round-trip
    indexed matches (spec §14).
    """

    _id: NotRequired[str]
    title: str
    subtitle: str
    body: str
    cover_url: str
    author: str
    created: str
    tags: list[str]
    status: ArticleStatus
    author_active: bool
    author_publisher: bool


class CommentDocument(TypedDict):
    """A comment attached to an article by reference (spec §12.1).

    ``author_active`` is the denormalized visibility snapshot (§7).
    """

    _id: NotRequired[str]
    text: str
    author: str
    article_id: str
    created: str
    author_active: bool


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


def normalized_document(
    document: Mapping[str, Any], boolean_fields: tuple[str, ...]
) -> dict[str, Any]:
    """Apply both boundary policies: hex-string ``_id`` and ``bool`` fields (§5.1)."""
    normalized: dict[str, Any] = dict(document)
    normalized["_id"] = document_id(document)
    for field in boolean_fields:
        normalized[field] = bool(normalized.get(field, False))
    return normalized
