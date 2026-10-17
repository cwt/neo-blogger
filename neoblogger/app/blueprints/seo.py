"""SEO surfaces: sitemap, robots, canonical, metadata, JSON-LD (spec §16)."""

from typing import Any
from xml.sax.saxutils import escape as xml_escape

from quart import Blueprint, Response

from ..context import AppContext
from ..services.visibility import PUBLIC_FEED_FILTER

__all__ = ["canonical_url_for", "create_seo_blueprint", "jsonld_document"]

_SITEMAP_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
)
_SITEMAP_FOOTER = "</urlset>\n"
_SITEMAP_PAGE_SIZE = 1_000
_FEED_PAGE_SIZE = 20
_LLM_DOCS_SIZE = 50


def _rfc3339(iso: str) -> str:
    """Normalize a stored timestamp for feed output (assumes UTC when naive)."""
    text = str(iso)
    if "T" in text and not text.endswith("Z") and "+" not in text[10:]:
        return f"{text}+00:00"
    return text


def _one_line(text: object) -> str:
    """Collapse a free-text field for line-oriented output (llms.txt)."""
    return " ".join(str(text).split())


def canonical_url_for(external_base: str, request_url_root: str, path: str) -> str:
    """Canonical URL from the configured base with request fallback (§16)."""
    base = external_base.strip().rstrip("/") or request_url_root.rstrip("/")
    return f"{base}{path}"


def jsonld_document(
    article: dict[str, Any] | None, site: dict[str, str], url: str = ""
) -> dict[str, Any]:
    """Article schema on article pages; WebSite schema elsewhere (§16)."""
    if article is None:
        return {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": site["title"],
            "description": site["description"],
            "publisher": {
                "@type": "Organization",
                "name": site["author"] or site["title"],
            },
        }
    document: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article["title"],
        "author": {"@type": "Person", "name": article["author"]},
        "datePublished": article["created"],
        "description": article["description"],
        "image": article["image"],
        "keywords": ", ".join(article["tags"]),
        "publisher": {"@type": "Organization", "name": site["title"]},
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": [".article-header h1", ".article-body"],
        },
    }
    if url:
        document["mainEntityOfPage"] = url
    return document


def create_seo_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("seo", __name__)

    @blueprint.route("/sitemap.xml")
    async def sitemap() -> Response:
        base = context.config.application.base_url or _request_base(context)
        base = xml_escape(base.rstrip("/"))
        entries = [f"  <url><loc>{base}/</loc></url>"]
        page = 1
        while True:
            batch = await context.articles.sitemap_entries(page, _SITEMAP_PAGE_SIZE)
            for article in batch:
                lastmod = str(article["created"]).split("T")[0]
                entries.append(
                    f"  <url><loc>{base}/{article['_id']}</loc>"
                    f"<lastmod>{lastmod}</lastmod></url>"
                )
            if len(batch) < _SITEMAP_PAGE_SIZE:
                break
            page += 1
        xml = _SITEMAP_HEADER + "\n".join(entries) + "\n" + _SITEMAP_FOOTER
        response = Response(xml)
        response.headers["Content-Type"] = "application/xml"
        return response

    @blueprint.route("/robots.txt")
    async def robots() -> Response:
        base = context.config.application.base_url or _request_base(context)
        document = (
            f"User-agent: *\nAllow: /\n\nSitemap: {base.rstrip('/')}/sitemap.xml\n"
        )
        response = Response(document)
        response.headers["Content-Type"] = "text/plain"
        return response

    @blueprint.route("/feed.xml")
    async def feed() -> Response:
        """Atom feed of the latest public articles (spec §16)."""
        base = (context.config.application.base_url or _request_base(context)).rstrip(
            "/"
        )
        site_title = context.config.application.site_title
        articles, _total = await context.articles.feed_page(
            PUBLIC_FEED_FILTER, 1, _FEED_PAGE_SIZE
        )
        items: list[str] = []
        for article in articles:
            url = f"{base}/{article['_id']}"
            title = xml_escape(str(article["title"]))
            subtitle = xml_escape(str(article.get("subtitle", "")))
            updated = xml_escape(_rfc3339(str(article["created"])))
            items.append(
                "  <entry>\n"
                f"    <title>{title}</title>\n"
                f'    <link href="{url}"/>\n'
                f"    <id>{url}</id>\n"
                f"    <updated>{updated}</updated>\n"
                f"    <summary>{subtitle}</summary>\n"
                "  </entry>"
            )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<feed xmlns="http://www.w3.org/2005/Atom">\n'
            f"  <title>{xml_escape(site_title)}</title>\n"
            f'  <link href="{base}/feed.xml" rel="self"/>\n'
            f'  <link href="{base}/"/>\n' + "\n".join(items) + "\n</feed>\n"
        )
        response = Response(xml)
        response.headers["Content-Type"] = "application/atom+xml"
        return response

    @blueprint.route("/llms.txt")
    async def llms() -> Response:
        """LLM-readable site map: title, description, latest articles (GEO)."""
        base = (context.config.application.base_url or _request_base(context)).rstrip(
            "/"
        )
        site = context.config.application
        articles, _total = await context.articles.feed_page(
            PUBLIC_FEED_FILTER, 1, _LLM_DOCS_SIZE
        )
        lines = [
            f"# {_one_line(site.site_title)}",
            "",
            _one_line(site.site_description),
            "",
            "## Articles",
            "",
        ]
        for article in articles:
            title = _one_line(article["title"])
            subtitle = _one_line(article.get("subtitle", ""))
            lines.append(f"- [{title}]({base}/{article['_id']}): {subtitle}")
        lines += [
            "",
            "## Feeds",
            "",
            f"- [Atom feed]({base}/feed.xml)",
            f"- [Sitemap]({base}/sitemap.xml)",
        ]
        response = Response("\n".join(lines) + "\n")
        response.headers["Content-Type"] = "text/plain; charset=utf-8"
        return response

    return blueprint


def _request_base(context: AppContext) -> str:
    """Fallback base URL honoring a trusted proxy (§15.8, §16)."""
    from ..wiring import request_base

    return request_base(context.proxy_trust)
