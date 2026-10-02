"""Minification and search-validation unit tests (§9, §14)."""

from neoblogger.app.services.search import validate_query
from neoblogger.app.text.minify import minify_html


def test_minify_trims_outside_pre() -> None:
    rendered = "<p>one</p>\n      \n<p>two</p>\n\n\n\n<p>three</p>\n"
    minified = minify_html(rendered)
    assert "<p>one</p>" in minified
    assert "<p>two</p>" in minified
    assert "<p>three</p>" in minified
    assert "\n\n\n" not in minified


def test_minify_preserves_pre_content() -> None:
    rendered = "<pre><code>x   =   1\n\n\nkeep  this</code></pre>\n<p>after</p>"
    minified = minify_html(rendered)
    assert "x   =   1\n\n\nkeep  this" in minified
    assert "<p>after</p>" in minified


def test_minify_preserves_blank_line_outside_pre() -> None:
    rendered = "<p>a</p>\n\n<p>b</p>"
    assert minify_html(rendered) == "<p>a</p>\n\n<p>b</p>"


def test_validate_query_accepts_plain_text() -> None:
    assert validate_query("  sqlite  ") == "sqlite"
    assert validate_query("full-text search deep dive") == "full-text search deep dive"
    assert validate_query("ภาษาไทย") == "ภาษาไทย"


def test_validate_query_rejects_addresses() -> None:
    assert validate_query("https://example.com/x") is None
    assert validate_query("see www.example.com") is None


def test_validate_query_rejects_markup() -> None:
    assert validate_query("<script>alert(1)</script>") is None
    assert validate_query("a > b") is None


def test_validate_query_rejects_shell_and_paths() -> None:
    assert validate_query("SELECT {x}") is None
    assert validate_query("cat /etc/passwd") is None
    assert validate_query("rm -rf ~") is None
    assert validate_query("echo $(id)") is None


def test_validate_query_rejects_special_heavy_long_input() -> None:
    assert validate_query("!" * 30) is None
    assert validate_query("word " + '!?"' * 10) is None


def test_validate_query_rejects_empty_and_overlong() -> None:
    assert validate_query("") is None
    assert validate_query("   ") is None
    assert validate_query("x" * 201) is None
