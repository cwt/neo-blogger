"""Shared query-string page parsing (bugs/023)."""

from typing import Any

__all__ = ["parse_page_number"]


def parse_page_number(args: Any) -> int:
    """Coerce ?page= to a 1-based integer (spec §14, §18)."""
    try:
        page = int(args.get("page", "1"))
    except TypeError, ValueError:
        return 1
    return max(1, page)
