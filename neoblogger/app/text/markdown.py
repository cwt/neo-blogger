"""CommonMark rendering with tables (spec §6, tech-req §7).

Raw user HTML in the markup source is escaped, never passed through
(html=False), so the sanitizer is a second line of defense rather than
the only one (spec §15.3).
"""

from markdown_it import MarkdownIt

__all__ = ["render_markdown"]

_md = MarkdownIt("default", {"html": False}).enable("table")


def render_markdown(source: str) -> str:
    """Convert lightweight markup to HTML; user HTML is escaped as text."""
    return str(_md.render(source))
