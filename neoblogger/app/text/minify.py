"""Conservative HTML minification (spec §14).

Whitespace is trimmed while preserving single blank lines needed by the
markup converter and the exact content of <pre>/<code> blocks.
"""

import re

__all__ = ["minify_html"]

_BLANK_RUN = re.compile(r"\n[ \t]*\n[ \t\n]*")
_TRAILING = re.compile(r"[ \t]+\n")
_PROTECTED = re.compile(r"<pre\b.*?</pre>|<code\b.*?</code>", re.DOTALL)


def minify_html(html: str) -> str:
    """Trim whitespace outside protected blocks; never touch their content."""
    parts: list[str] = []
    position = 0
    for match in _PROTECTED.finditer(html):
        parts.append(_compress(html[position : match.start()]))
        parts.append(match.group(0))
        position = match.end()
    parts.append(_compress(html[position:]))
    return "".join(parts)


def _compress(fragment: str) -> str:
    fragment = _BLANK_RUN.sub("\n\n", fragment)
    fragment = _TRAILING.sub("\n", fragment)
    return fragment.strip("\n")
