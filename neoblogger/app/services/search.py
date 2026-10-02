"""Search query validation (spec §9): reject non-text input patterns.

Queries containing web addresses, markup/script tags, code or shell
patterns, file paths, or (for longer input) an excessive proportion of
special characters are rejected with a "please use only text" notice.
"""

__all__ = ["validate_query"]

_SHELL_CHARS = "{};|`$()&"
_LENGTH_THRESHOLD = 24
_SPECIAL_LIMIT = 0.5


def _has_web_address(term: str) -> bool:
    lowered = term.lower()
    return "://" in lowered or lowered.startswith("www.") or ".com" in lowered


def _has_markup(term: str) -> bool:
    return "<" in term or ">" in term


def _has_shell_or_code(term: str) -> bool:
    return any(character in _SHELL_CHARS for character in term)


def _has_file_path(term: str) -> bool:
    return "/" in term or "\\" in term or "~" in term


def _excessively_special(term: str) -> bool:
    if len(term) <= _LENGTH_THRESHOLD:
        return False
    special = sum(
        not (character.isalnum() or character.isspace()) for character in term
    )
    return special / len(term) > _SPECIAL_LIMIT


def validate_query(term: str) -> str | None:
    """Return the cleaned query, or ``None`` when it must be rejected (§9)."""
    cleaned = term.strip()
    if not cleaned or len(cleaned) > 200:
        return None
    rejected = (
        _has_web_address(cleaned)
        or _has_markup(cleaned)
        or _has_shell_or_code(cleaned)
        or _has_file_path(cleaned)
        or _excessively_special(cleaned)
    )
    return None if rejected else cleaned
