"""Shared Markdown rendering pipeline (bugs/023)."""

from .highlight import highlight_code_blocks
from .markdown import render_markdown
from .sanitize import sanitize_html

__all__ = ["render_rich_text"]


def render_rich_text(markup: str) -> str:
    """Render Markdown to safe highlighted HTML in one call."""
    return highlight_code_blocks(sanitize_html(render_markdown(markup)))
