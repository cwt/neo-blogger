"""Server-side syntax highlighting with Pygments (spec §6, tech-req §7).

Runs over already-sanitized HTML (server-trusted transform of trusted
input), replacing fenced code blocks with highlighted markup. Blocks
whose language has no lexer are left unchanged.
"""

import html
import re

from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

__all__ = ["highlight_code_blocks"]

_CODE_BLOCK = re.compile(
    r'<pre><code class="language-([\w+.-]+)">(?P<body>.*?)</code></pre>',
    re.DOTALL,
)

_EMPTY_BLOCK = re.compile(r"<pre><code>\s*</code></pre>\n?")

_formatter = HtmlFormatter()


def _highlight_block(match: re.Match[str]) -> str:
    """Render one fenced code block with Pygments, or leave it unchanged."""
    language = match.group(1)
    source = html.unescape(match.group("body"))
    try:
        lexer = get_lexer_by_name(language)
        return pygments_highlight(source, lexer, _formatter)
    except Exception:
        # Highlighting must never break rendering: unknown languages and
        # lexer failures on odd input leave the sanitized block as-is.
        return match.group(0)


def highlight_code_blocks(fragment: str) -> str:
    """Highlight ``language-*`` code blocks; other markup passes through.

    Empty code blocks (a stray fence with no code, which markdown renders
    as ``<pre><code></code></pre>``) are dropped: they carry no content
    and otherwise render as a confusing empty gray rectangle.
    """
    return _EMPTY_BLOCK.sub("", _CODE_BLOCK.sub(_highlight_block, fragment))
