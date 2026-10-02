"""Neo-Blogger application factory (tech-req §3)."""

from dataclasses import dataclass

from quart import Quart

from .app.config import RuntimeConfig, load_config

__all__ = ["AppContext", "build_app", "create_app"]

_CONTEXT_KEY = "neoblogger_context"


@dataclass(slots=True)
class AppContext:
    """Per-application state shared with later layers."""

    config: RuntimeConfig


def build_app(config: RuntimeConfig) -> Quart:
    """Assemble the Quart application from an already-resolved configuration."""
    app = Quart(__name__)
    app.config[_CONTEXT_KEY] = AppContext(config=config)

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
