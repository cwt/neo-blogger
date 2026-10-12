"""Application assembly (tech-req §3.3/§3.4): lifecycle hooks and blueprints.

Every request: start the DB lazily (idempotent), resolve the session cookie
into a member (destroying the cookie for disabled accounts), enforce CSRF
on authenticated mutations, and serve cached home pages to anonymous
visitors. Finalization adds security headers, the sliding session cookie,
cache-control policy, and HTML minification.
"""

import datetime
import secrets
from typing import Any

from quart import Quart, Response, abort, g, render_template, request

from .blueprints.admin import create_admin_blueprint
from .blueprints.auth import create_auth_blueprint
from .blueprints.blog import HexIdConverter, create_blog_blueprint, render_home_page
from .blueprints.discovery import create_discovery_blueprint
from .blueprints.images import create_images_blueprint
from .blueprints.profile import create_profile_blueprint
from .blueprints.seo import canonical_url_for, create_seo_blueprint, jsonld_document
from .context import AppContext
from .security.csrf import new_csrf_token, tokens_match
from .security.headers import security_headers
from .security.proxy import ProxyTrust, forwarded_base, forwarded_client
from .security.ratelimit import FixedWindowRateLimiter
from .services.cache import ResponseCache
from .services.objects import legacy_url, readable_date
from .services.theme import THEME_BANNER_KEY, THEME_OWNER, banner_for_path
from .text.minify import minify_html

__all__ = [
    "assemble",
    "drop_session",
    "issue_session",
    "recovery_limiter_allow",
    "request_base",
    "request_client",
    "signin_limiter_allow",
]

_CONTEXT_KEY = "neoblogger_context"
_COOKIE_NAME = "neoblogger_session"
_CSRF_COOKIE_NAME = "neoblogger_csrf"
_COOKIE_MAX_AGE = 24 * 60 * 60
_MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE"})

_recovery_limiter = FixedWindowRateLimiter(max_attempts=5, window_seconds=300.0)
_signin_limiter = FixedWindowRateLimiter(max_attempts=5, window_seconds=300.0)


def issue_session(member_id: str, session_version: int = 1) -> None:
    """Start a session; the cookie is written by ``after_request``."""
    context: AppContext = g.neoblogger_context
    cookie, token = context.auth.start_session(
        member_id, session_version=session_version
    )
    g.set_session_cookie = cookie
    g.csrf_token = token


def drop_session() -> None:
    g.destroy_session_cookie = True
    # Explicit sign-out busts the anonymous page cache (spec §4.3).
    g.clear_response_cache = True
    g.member = None
    g.session = None


def recovery_limiter_allow(peer: str, email: str) -> bool:
    """Rate-limit gate for password recovery (Appendix B D5)."""
    return _recovery_limiter.allow(peer, email)


def signin_limiter_allow(peer: str, email: str) -> bool:
    """Rate-limit gate for sign-in attempts."""
    return _signin_limiter.allow(peer, email)


async def ensure_theme_banners(context: AppContext) -> dict[str, str]:
    """Load the deploy-time banner mapping once; empty without a theme.

    Theme objects are ordinary gallery images owned by ``"theme"``; the
    mapping survives restarts because it lives in the database, and a
    regeneration takes effect on the next boot (spec §10).
    """
    if context.theme_banners is None:
        rows, _total = await context.objects.list_for(THEME_OWNER, 1, 50)
        context.theme_banners = {
            str(row["metadata"].get(THEME_BANNER_KEY, "")): f"/images/{row['id']}.webp"
            for row in rows
            if row["metadata"].get(THEME_BANNER_KEY)
        }
    return context.theme_banners


def request_client(trust: ProxyTrust) -> str:
    """The client address for rate-limit keys (§15.8).

    Honors ``X-Forwarded-For`` from a trusted adjacent hop only, so a
    reverse proxy's clients do not share one bucket.
    """
    peer = request.remote_addr or ""
    return forwarded_client(peer, request.headers.get("X-Forwarded-For"), trust)


def request_base(trust: ProxyTrust) -> str:
    """The fallback base URL for canonical links (§15.8, §16)."""
    peer = request.remote_addr or ""
    return forwarded_base(
        peer,
        request.scheme,
        request.host,
        request.headers.get("X-Forwarded-Proto"),
        request.headers.get("X-Forwarded-Host"),
        request.url_root,
        trust,
    )


def _set_session_cookie(response: Response, value: str, *, secure: bool) -> None:
    response.set_cookie(
        _COOKIE_NAME,
        value,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=secure,
    )


def _cache_key(per_page: int = 10) -> str:
    """The home-feed cache key: validated page number and page size (spec §14).

    Raw query input would mint a junk key per malformed value ("abc",
    "-3", ...) for identical content; coerce exactly like the feed
    renderer so one page maps to one key.
    """
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        page = 1
    return f"home:{max(1, page)}:{per_page}"


def _is_home_page() -> bool:
    return request.path == "/" and request.method == "GET"


def assemble(app: Quart, context: AppContext) -> None:
    """Register blueprints and wire the request lifecycle onto ``app``."""
    app.extensions[_CONTEXT_KEY] = context
    app.url_map.converters["hexid"] = HexIdConverter
    app.register_blueprint(create_auth_blueprint(context))
    app.register_blueprint(create_blog_blueprint(context))
    app.register_blueprint(create_profile_blueprint(context))
    app.register_blueprint(create_admin_blueprint(context))
    app.register_blueprint(create_discovery_blueprint(context))
    app.register_blueprint(create_images_blueprint(context))
    app.register_blueprint(create_seo_blueprint(context))
    app.jinja_env.filters["readable_date"] = readable_date

    def _legacy_filter(value: str) -> str:
        return legacy_url(value)

    app.jinja_env.filters["legacy_ext"] = _legacy_filter

    caching = context.config.caching
    cache = ResponseCache(
        enabled=caching.enabled,
        timeout_seconds=caching.timeout_seconds,
        max_size_mb=caching.max_size_mb,
        storage=caching.storage,
        directory=caching.directory,
    )

    context.response_cache = cache

    @app.before_serving
    async def _prewarm() -> None:
        """Per-worker startup state warmup (spec §14, §19.4).

        Starts the DB lazily here instead of waiting for the first request,
        and renders anonymous home page 1 into the response cache so the
        first request of the day is already fast.
        """
        await context.database.start()
        await ensure_theme_banners(context)
        if not (cache.active() and context.response_cache is not None):
            return
        version = await context.meta.content_version()
        per_page = context.config.posts.per_page
        key = f"home:1:{per_page}"
        # Page 1 under its validated key; _cache_key() itself is unusable
        # here — there is no request context during startup.
        cached = await cache.get(key, version)
        if cached is not None:
            return
        async with app.test_request_context("/"):
            g.member = None
            g.session = None
            nonce = secrets.token_hex(16)
            g.csp_nonce = nonce
            rendered = await render_home_page(context, 1, per_page, None)
            await cache.put(key, minify_html(rendered), version, nonce=nonce)

    @app.errorhandler(404)
    async def _not_found(_: Exception) -> tuple[str, int]:
        return (
            await render_template(
                "error.html",
                heading="Not found",
                description="That page does not exist.",
            ),
            404,
        )

    @app.errorhandler(403)
    async def _forbidden(_: Exception) -> tuple[str, int]:
        return (
            await render_template(
                "error.html",
                heading="Access denied",
                description="You cannot do that here.",
            ),
            403,
        )

    @app.errorhandler(500)
    async def _server_error(_: Exception) -> tuple[str, int]:
        return (
            await render_template(
                "error.html",
                heading="Something went wrong",
                description="Please try again later.",
            ),
            500,
        )

    @app.before_request
    async def _prepare() -> Response | None:
        g.neoblogger_context = context
        g.csp_nonce = secrets.token_hex(16)
        await context.database.start()
        await ensure_theme_banners(context)
        raw_cookie = request.cookies.get(_COOKIE_NAME)
        session = context.codec.load(raw_cookie) if raw_cookie else None
        g.session = session
        member = None
        if session is not None:
            member = await context.members.by_id(session.member_id)
            if member is not None and (
                not member["active"]
                or member.get("session_version", 1) != session.session_version
            ):
                member = None
        g.member = member
        if member is None and session is not None:
            g.destroy_session_cookie = True
            g.session = None
            session = None
        if session is not None:
            g.csrf_token = session.csrf_token
        else:
            anon_csrf = request.cookies.get(_CSRF_COOKIE_NAME)
            if not anon_csrf:
                anon_csrf = new_csrf_token()
                g.set_anon_csrf_cookie = anon_csrf
            g.csrf_token = anon_csrf

        if request.method in _MUTATING_METHODS:
            form = await request.form
            candidate = form.get("csrftoken", "") or request.headers.get(
                "X-CSRFToken", ""
            )
            expected = g.csrf_token
            if not tokens_match(candidate, expected):
                abort(403)
        if cache.active() and member is None and _is_home_page():
            version = await context.meta.content_version()
            hit = await cache.get(_cache_key(context.config.posts.per_page), version)
            if hit is not None:
                cached_html, cached_nonce = hit
                g.csp_nonce = cached_nonce
                return Response(cached_html, content_type="text/html; charset=utf-8")
        return None

    @app.context_processor
    def _template_globals() -> dict[str, Any]:
        session = getattr(g, "session", None)
        article = getattr(g, "article", None)
        site = {
            "title": context.config.application.site_title,
            "author": context.config.application.site_author,
            "description": context.config.application.site_description,
        }
        if article is not None:
            structured = jsonld_document(article, site)
        else:
            structured = jsonld_document(None, site)
        banners = context.theme_banners or {}
        banner_url = banners.get(banner_for_path(request.path))
        if banner_url is not None and article is not None and article.get("image"):
            # An article's own cover wins over the page banner (spec §10).
            banner_url = None
        return {
            "site_title": context.config.application.site_title,
            "site_author": context.config.application.site_author,
            "site_description": context.config.application.site_description,
            "member": getattr(g, "member", None),
            "csrf_token": getattr(g, "csrf_token", "")
            or (session.csrf_token if session is not None else ""),
            "csp_nonce": getattr(g, "csp_nonce", ""),
            "year": datetime.datetime.now().year,
            "breadcrumbs": getattr(g, "breadcrumbs", []),
            "theme_banner": banner_url,
            "theme_active": bool(banners),
            "canonical_url": canonical_url_for(
                context.config.application.base_url,
                request_base(context.proxy_trust),
                request.path,
            ),
            "jsonld": structured,
        }

    @app.after_request
    async def _finalize(response: Response) -> Response:
        secure = context.config.application.https
        nonce = getattr(g, "csp_nonce", None)
        for name, value in security_headers(https=secure, nonce=nonce).items():
            response.headers[name] = value
        session = getattr(g, "session", None)
        member = getattr(g, "member", None)
        if getattr(g, "destroy_session_cookie", False):
            response.delete_cookie(_COOKIE_NAME)
        if getattr(g, "clear_response_cache", False):
            # Sign-out clears the response cache (spec §4.3). Stale-cookie
            # hygiene above only drops the cookie: a disabled account's
            # leftover cookie must not evict cached pages for everyone.
            cache.clear()
        elif getattr(g, "set_session_cookie", None):
            _set_session_cookie(response, g.set_session_cookie, secure=secure)
            response.delete_cookie(_CSRF_COOKIE_NAME)
            if "text/html" in response.headers.get("Content-Type", ""):
                response.headers["Cache-Control"] = "no-store"
        elif member is not None and session is not None:
            _set_session_cookie(response, context.auth.refresh(session), secure=secure)
            response.delete_cookie(_CSRF_COOKIE_NAME)
            if "text/html" in response.headers.get("Content-Type", ""):
                response.headers["Cache-Control"] = "no-store"
        if (
            getattr(g, "set_anon_csrf_cookie", None)
            and session is None
            and not getattr(g, "set_session_cookie", None)
        ):
            response.set_cookie(
                _CSRF_COOKIE_NAME,
                g.set_anon_csrf_cookie,
                max_age=_COOKIE_MAX_AGE,
                httponly=True,
                samesite="Lax",
                secure=secure,
            )
        if request.path.startswith("/search") or request.path.startswith("/tag/"):
            response.headers["Cache-Control"] = "no-cache"
        if (
            request.path.startswith("/static/fonts/")
            or request.path == "/static/fonts.css"
        ):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        if (
            cache.active()
            and member is None
            and _is_home_page()
            and response.status_code == 200
            and "text/html" in response.headers.get("Content-Type", "")
        ):
            body = await response.get_data()
            rendered = body.decode("utf-8") if isinstance(body, bytes) else body
            minified = minify_html(rendered)
            version = await context.meta.content_version()
            await cache.put(
                _cache_key(context.config.posts.per_page),
                minified,
                version,
                nonce=nonce or "",
            )
            response.set_data(minified)
        return response
