"""Deploy-time theme artwork (tech-req §10).

Banner images are generated once by the ``neoblogger-theme`` CLI and stored
as ordinary image objects owned by ``"theme"``; every page maps to one
banner name, and pages render exactly as today when no theme exists
(the themeless default). Nothing is fetched at runtime.
"""

import re
from typing import Any

__all__ = [
    "THEME_BANNER_KEY",
    "THEME_OWNER",
    "THEME_PAGE_SIZE",
    "banner_for_path",
    "list_theme_banners",
]

THEME_OWNER = "theme"
THEME_BANNER_KEY = "theme_banner"
THEME_PAGE_SIZE = 50

_PAGE_BANNERS: dict[str, str] = {
    "tag": "tag",
    "search": "search",
    "signup": "auth",
    "signin": "auth",
    "recover": "auth",
    "profile": "profile",
    "write": "write",
    "upload": "upload",
    "admin": "admin",
}

_HEXID = re.compile(r"[0-9a-f]{24}")


def banner_for_path(path: str) -> str:
    """The theme banner name for a page path (spec §10).

    Article pages resolve by hex id; anything unrecognized falls back to
    the error banner, which only ever renders on error pages.
    """
    if path == "/":
        return "home"
    first = path.strip("/").split("/", 1)[0]
    if first in _PAGE_BANNERS:
        return _PAGE_BANNERS[first]
    if _HEXID.fullmatch(first) is not None and "/" not in path.strip("/"):
        return "article"
    return "error"


async def list_theme_banners(objects: object) -> Any:
    """Single shared theme-banner query (bugs/023)."""
    from typing import cast

    repository = cast(Any, objects)
    result = await repository.list_for(THEME_OWNER, 1, THEME_PAGE_SIZE)
    return result
