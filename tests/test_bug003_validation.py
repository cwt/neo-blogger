"""Bug 003 regression: server-side validation."""

import pytest

from neoblogger.app.services.accounts import validate_display_name, validate_email
from neoblogger.app.services.articles import (
    _validate_article_fields,
    _validate_cover_url,
)


def test_article_fields_reject_blank_and_long() -> None:
    with pytest.raises(ValueError, match="title is required"):
        _validate_article_fields("   ", "sub", "body")
    with pytest.raises(ValueError, match="subtitle is required"):
        _validate_article_fields("t", "  ", "body")
    with pytest.raises(ValueError, match="body is required"):
        _validate_article_fields("t", "s", "   ")
    with pytest.raises(ValueError, match="at most 200"):
        _validate_article_fields("t" * 201, "s", "b")
    with pytest.raises(ValueError, match="at most 300"):
        _validate_article_fields("t", "s" * 301, "b")
    _validate_article_fields("t", "s", "b")


def test_cover_url_schemes() -> None:
    _validate_cover_url("")
    _validate_cover_url("/images/abc.webp")
    _validate_cover_url("https://cdn.example.com/a.webp")
    _validate_cover_url("http://x.io/a.jpg")
    with pytest.raises(ValueError, match="cover image URL"):
        _validate_cover_url("javascript:alert(1)")
    with pytest.raises(ValueError, match="cover image URL"):
        _validate_cover_url("data:text/html,hi")


def test_email_and_display_name() -> None:
    assert validate_email("A@X.IO ") == "a@x.io"
    with pytest.raises(ValueError):
        validate_email("no-at-sign")
    with pytest.raises(ValueError):
        validate_email("a@nodot")
    with pytest.raises(ValueError):
        validate_email("")
    assert validate_display_name(" alice ") == "alice"
    with pytest.raises(ValueError):
        validate_display_name("   ")
    with pytest.raises(ValueError, match="at most 50"):
        validate_display_name("x" * 51)
