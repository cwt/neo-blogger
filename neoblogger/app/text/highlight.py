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
from pygments.util import ClassNotFound

__all__ = ["highlight_code_blocks"]

_CODE_BLOCK = re.compile(
    r'<pre><code class="language-([\w+.-]+)">(?P<body>.*?)</code></pre>',
    re.DOTALL,
)

_formatter = HtmlFormatter()


def _replace(match: re.Match[str]) -> str:
    language = match.group(1)
    source = html.unescape(match.group("body"))
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        return match.group(0)
    return pygments_highlight(source, lexer, _formatter)


def highlight_code_blocks(fragment: str) -> str:
    """Highlight ``language-*`` code blocks; other markup passes through."""
    return _CODE_BLOCK.sub(_replace, fragment)
