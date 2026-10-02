"""Neo-Blogger application factory (tech-req §3)."""

import secrets

from quart import Quart

from .app.config import RuntimeConfig, load_config
from .app.context import AppContext
from .app.wiring import assemble

__all__ = ["AppContext", "build_app", "create_app"]


def build_app(config: RuntimeConfig) -> Quart:
    """Assemble the Quart application from an already-resolved configuration."""
    app = Quart(
        __name__,
        template_folder="app/web/templates",
        static_folder="app/web/static",
    )
    context = AppContext.build(config)
    # Quart's own session (flash messages) needs a signing key; production
    # enforces a configured secret (§15.9), while development falls back to
    # an ephemeral one. The session cookie itself is the signed cookie in
    # security.sessions (Appendix B D4), not this.
    app.secret_key = config.application.secret_key or secrets.token_hex(32)
    assemble(app, context)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def create_app(config_path: str | None = None) -> Quart:
    """Load configuration from TOML, then assemble the application.

    The path resolution order is: explicit argument, then the
    ``NEOBLOGGER_CONFIG`` environment variable, then the default file name
    (tech-req §14).
    """
    return build_app(load_config(config_path))
