"""Bug 005 regression: image URL generation."""

from neoblogger.app.services.objects import legacy_url


def test_legacy_url_only_local() -> None:
    assert legacy_url("/images/abc.webp") == "/images/abc.jpg"
    assert legacy_url("/images/abc.webp", "png") == "/images/abc.png"
    assert (
        legacy_url("https://cdn.example.com/photo.webp")
        == "https://cdn.example.com/photo.webp"
    )
    assert legacy_url("https://x.io/c.jpg") == "https://x.io/c.jpg"
    assert legacy_url("no-dot") == "no-dot"


def test_article_template_uses_absolute_image() -> None:
    from pathlib import Path

    template = Path("neoblogger/app/web/templates/article.html").read_text()
    assert "url_root" not in template
    assert '<meta property="og:image" content="{{ g.article.image }}">' in template
