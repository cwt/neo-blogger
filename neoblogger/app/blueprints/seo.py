"""SEO surfaces: sitemap, robots, canonical, metadata, JSON-LD (spec §16)."""

from typing import Any
from xml.sax.saxutils import escape as xml_escape

from quart import Blueprint, Response, request

from ..context import AppContext
from ..services.visibility import PUBLIC_FEED_FILTER

__all__ = ["canonical_url_for", "create_seo_blueprint", "jsonld_document"]

_SITEMAP_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
)
_SITEMAP_FOOTER = "</urlset>\n"
_SITEMAP_PAGE_SIZE = 1_000


def canonical_url_for(external_base: str, request_url_root: str, path: str) -> str:
    """Canonical URL from the configured base with request fallback (§16)."""
    base = external_base.strip().rstrip("/") or request_url_root.rstrip("/")
    return f"{base}{path}"


def jsonld_document(
    article: dict[str, Any] | None, site: dict[str, str]
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
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article["title"],
        "author": {"@type": "Person", "name": article["author"]},
        "datePublished": article["created"],
        "description": article["description"],
        "image": article["image"],
        "keywords": ", ".join(article["tags"]),
        "publisher": {"@type": "Organization", "name": site["title"]},
    }


def create_seo_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("seo", __name__)

    @blueprint.route("/sitemap.xml")
    async def sitemap() -> Response:
        base = context.config.application.base_url or request.url_root
        base = xml_escape(base.rstrip("/"))
        entries = [f"  <url><loc>{base}/</loc></url>"]
        page = 1
        while True:
            batch, _total = await context.articles.feed_page(
                PUBLIC_FEED_FILTER, page, _SITEMAP_PAGE_SIZE
            )
            for article in batch:
                lastmod = article["created"].split("T")[0]
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
        base = context.config.application.base_url or request.url_root
        document = (
            f"User-agent: *\nAllow: /\n\nSitemap: {base.rstrip('/')}/sitemap.xml\n"
        )
        response = Response(document)
        response.headers["Content-Type"] = "text/plain"
        return response

    return blueprint
