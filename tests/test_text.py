"""Tests for the text pipeline: markdown, sanitizer, highlighting (§7)."""

from neoblogger.app.text.highlight import highlight_code_blocks
from neoblogger.app.text.markdown import render_markdown
from neoblogger.app.text.sanitize import sanitize_html


def test_markdown_renders_documented_elements() -> None:
    rendered = render_markdown(
        "# Heading\n\nSome *emphasis* and **strength**.\n\n"
        "- one\n- two\n\n> quoted\n\n```python\nprint(1)\n```\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n"
    )
    assert "<h1>" in rendered
    assert "<em>emphasis</em>" in rendered
    assert "<strong>strength</strong>" in rendered
    assert "<ul>" in rendered and "<li>one</li>" in rendered
    assert "<blockquote>" in rendered
    assert '<pre><code class="language-python">' in rendered
    assert "<table>" in rendered and "<td>1</td>" in rendered


def test_markdown_escapes_raw_user_html() -> None:
    rendered = render_markdown("<script>alert(1)</script>\n\n<div>x</div>")
    assert "<script>" not in rendered
    assert "<div>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_sanitizer_strips_scripts_and_content() -> None:
    cleaned = sanitize_html("<p>ok</p><script>alert(1)</script>")
    assert "<script>" not in cleaned
    assert "alert(1)" not in cleaned
    assert "<p>ok</p>" in cleaned


def test_sanitizer_removes_event_handlers() -> None:
    cleaned = sanitize_html('<p onclick="evil()">text</p>')
    assert "onclick" not in cleaned
    assert "evil()" not in cleaned
    assert "text" in cleaned


def test_sanitizer_neutralizes_javascript_links() -> None:
    cleaned = sanitize_html('<a href="javascript:alert(1)">click</a>')
    assert "javascript:" not in cleaned


def test_sanitizer_keeps_documented_elements_and_attributes() -> None:
    fragment = (
        '<h2>Head</h2><p><a href="https://x.io" title="t">link</a>'
        '<img src="https://x.io/i.png" alt="pic"> '
        '<code class="language-py">c</code></p>'
    )
    cleaned = sanitize_html(fragment)
    assert '<a href="https://x.io" title="t"' in cleaned
    assert '<img src="https://x.io/i.png" alt="pic"' in cleaned
    assert 'class="language-py"' in cleaned


def test_sanitizer_only_allows_language_classes() -> None:
    cleaned = sanitize_html('<span class="evil">x</span><code class="y">c</code>')
    assert 'class="evil"' not in cleaned
    assert 'class="y"' not in cleaned


def test_sanitizer_denies_inline_style() -> None:
    cleaned = sanitize_html('<p style="color: red">t</p>')
    assert "style" not in cleaned


def test_sanitizer_adds_rel_to_links() -> None:
    cleaned = sanitize_html('<a href="https://x.io">l</a><a href="/local">l2</a>')
    assert 'rel="noopener noreferrer"' in cleaned


def test_highlight_replaces_python_block() -> None:
    fragment = '<pre><code class="language-python">print(&quot;hi&quot;)</code></pre>'
    highlighted = highlight_code_blocks(fragment)
    assert 'class="highlight"' in highlighted
    assert "print" in highlighted
    assert 'class="language-python"' not in highlighted


def test_highlight_keeps_unknown_language_plain() -> None:
    fragment = '<pre><code class="language-nosuchlang">x &lt; 1</code></pre>'
    assert highlight_code_blocks(fragment) == fragment


def test_highlight_unescapes_source_before_lexing() -> None:
    fragment = '<pre><code class="language-python">s = "&lt;b&gt;"</code></pre>'
    highlighted = highlight_code_blocks(fragment)
    assert "&lt;b&gt;" in highlighted
    assert '<span class="s2">' in highlighted
    assert 'class="highlight"' in highlighted


def test_pipeline_order_markdown_sanitize_highlight() -> None:
    rendered = render_markdown("```python\nif x:\n    pass\n```\n")
    cleaned = sanitize_html(rendered)
    final = highlight_code_blocks(cleaned)
    assert 'class="highlight"' in final
    assert "if" in final
