"""Allowlist sanitizer (spec §15.3, tech-req §7).

Rendered markup passes through nh3 (Rust ammonia bindings) with an
explicit element/attribute allowlist. Inline CSS is denied in v1: the
allowlist of style properties is empty, which is a valid instance of the
spec's "small set of inline CSS properties" and keeps the pipeline
deny-by-default. Raw user HTML never bypasses this pipeline.
"""

import re

import nh3

__all__ = ["sanitize_html"]

_ALLOWED_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "em",
        "strong",
        "ul",
        "ol",
        "li",
        "a",
        "img",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "pre",
        "code",
        "blockquote",
        "hr",
        "br",
        "span",
    }
)

_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "code": {"class"},
    "span": {"class"},
}

_CODE_LANGUAGE_CLASS = re.compile(r"^language-[\w+.-]+$")

_URL_SCHEMES = frozenset({"http", "https", "mailto"})


def _filter_attribute(tag: str, attribute: str, value: str) -> str | None:
    """Keep ``class`` values only for code-language annotations (§7)."""
    if attribute == "class":
        return value if _CODE_LANGUAGE_CLASS.match(value.strip()) else None
    return value


def sanitize_html(fragment: str) -> str:
    """Strictly allowlist-sanitize rendered markup (spec §15.3)."""
    return nh3.clean(
        fragment,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        attribute_filter=_filter_attribute,
        clean_content_tags=frozenset({"script", "style"}),
        link_rel="noopener noreferrer",
        url_schemes=_URL_SCHEMES,
    )
