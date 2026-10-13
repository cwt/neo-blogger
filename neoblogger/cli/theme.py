"""Deploy-time theme artwork generation (tech-req §10).

Usage: ``neoblogger-theme [-c CONFIG] [-e ENV_FILE] generate [--force]``

In Neo-Blogger, theme assets designate deploy-time 21:9 page-family banners
generated once with Agnes Image 2.5 and stored as ordinary gallery
images owned by ``"theme"`` (palettes and typography remain standard
self-hosted Pico CSS).

Runs once: an existing set is only completed, never silently replaced (pass
``--force`` to wipe and regenerate). Without ``AGNES_API_KEY`` (env var,
``--env-file``, or ``./.env``) the command refuses and the app keeps
rendering the themeless default — nothing is ever fetched at runtime.
"""

import argparse
import asyncio
import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from ..app.config import load_config
from ..app.context import AppContext
from ..app.services.theme import THEME_BANNER_KEY, THEME_OWNER

__all__ = [
    "API_ENDPOINT",
    "BANNERS",
    "DEFAULT_API_ENDPOINT",
    "DEFAULT_MODEL",
    "MODEL",
    "RATIO",
    "SIZE",
    "build_parser",
    "main",
    "prompt_for",
    "read_dotenv",
    "resolve_dotenv_path",
    "resolve_endpoint",
    "resolve_key",
    "resolve_model",
]

DEFAULT_API_ENDPOINT = "https://apihub.agnes-ai.com/v1/images/generations"
DEFAULT_MODEL = "agnes-image-2.5-flash"
API_ENDPOINT = DEFAULT_API_ENDPOINT
MODEL = DEFAULT_MODEL
SIZE = "1K"
RATIO = "21:9"
REQUEST_TIMEOUT_SECONDS = 180
MAX_WIDTH = 1600

_STYLE_SUFFIX = (
    "minimal editorial banner illustration, warm paper texture, muted "
    "indigo and amber palette, wide composition, no text, no words, "
    "no letters, no watermark"
)

_SUBJECTS: dict[str, str] = {
    "home": "sunrise over a calm harbor with paper boats",
    "article": "an open book whose pages turn into birds",
    "tag": "apothecary labels and paper tags on wooden shelves",
    "search": "a magnifying glass over a dotted paper map",
    "auth": "a brass key on linen cloth beside a sealed envelope",
    "profile": "a writing desk with a fountain pen and stacked letters",
    "write": "a fountain pen drawing a rising sun from one line",
    "upload": "framed landscape photographs drying on a line",
    "admin": "a lighthouse control room with brass gauges",
    "error": "a paper boat in soft fog",
}

BANNERS: tuple[str, ...] = (
    "home",
    "article",
    "tag",
    "search",
    "auth",
    "profile",
    "write",
    "upload",
    "admin",
    "error",
)


def prompt_for(name: str) -> str:
    """The generation prompt for a banner: subject plus house style."""
    return f"{_SUBJECTS[name]}, {_STYLE_SUFFIX}"


def read_dotenv(path: str) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` file without third-party help (stdlib only).

    Blank lines and ``#`` comments are skipped; surrounding single or
    double quotes are stripped. Last assignment wins.
    """
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        key = key.strip()
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_dotenv_path(
    explicit: str | None = None, config_path: str | None = None
) -> str:
    """The path to .env: explicit option first, then config dir, then ./.env."""
    if explicit:
        return explicit
    if config_path:
        adjacent = Path(config_path).parent / ".env"
        if adjacent.is_file():
            return str(adjacent)
    return ".env"


def resolve_key(environ: Mapping[str, str], dotenv_path: str) -> str:
    """The Agnes key: explicit environment first, then the dotenv file."""
    if environ.get("AGNES_API_KEY", "").strip():
        return environ["AGNES_API_KEY"].strip()
    return read_dotenv(dotenv_path).get("AGNES_API_KEY", "").strip()


def resolve_endpoint(environ: Mapping[str, str], dotenv_path: str) -> str:
    """The generation API endpoint: env var first, then dotenv, then default."""
    for key in ("AGNES_API_ENDPOINT", "AGNES_ENDPOINT"):
        val = environ.get(key, "").strip()
        if val:
            return val
    dotenv = read_dotenv(dotenv_path)
    for key in ("AGNES_API_ENDPOINT", "AGNES_ENDPOINT"):
        val = dotenv.get(key, "").strip()
        if val:
            return val
    return DEFAULT_API_ENDPOINT


def resolve_model(environ: Mapping[str, str], dotenv_path: str) -> str:
    """The generation model: AGNES_MODEL env var, then dotenv, then default."""
    val = environ.get("AGNES_MODEL", "").strip()
    if val:
        return val
    dotenv = read_dotenv(dotenv_path)
    val = dotenv.get("AGNES_MODEL", "").strip()
    if val:
        return val
    return DEFAULT_MODEL


def _post_json(
    key: str, payload: dict[str, Any], *, endpoint: str = DEFAULT_API_ENDPOINT
) -> dict[str, Any]:
    """POST the generation request; transport errors propagate."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as reply:
        document: dict[str, Any] = json.loads(reply.read().decode("utf-8"))
        return document


def _fetch_pixels(
    key: str, payload: dict[str, Any], *, endpoint: str = DEFAULT_API_ENDPOINT
) -> bytes:
    """Run one generation; returns the raw image bytes.

    Prefers inline Base64 (no second download); falls back to fetching
    the result URL when the service returns one instead.
    """
    document = _post_json(key, payload, endpoint=endpoint)
    entries = document.get("data", [])
    if not entries:
        raise ValueError("empty image response")
    entry = entries[0]
    if entry.get("b64_json"):
        decoded: bytes = base64.b64decode(entry["b64_json"])
        return decoded
    if entry.get("url"):
        with urllib.request.urlopen(
            entry["url"], timeout=REQUEST_TIMEOUT_SECONDS
        ) as reply:
            downloaded: bytes = reply.read()
            return downloaded
    raise ValueError("image response has neither payload nor URL")


def _to_webp(raw: bytes) -> bytes:
    """Verify, bound, and convert to WebP (spec §10.2 policy)."""
    image = Image.open(io.BytesIO(raw))
    image.load()
    rgb = image.convert("RGB")
    if rgb.width > MAX_WIDTH:
        rgb.thumbnail((MAX_WIDTH, MAX_WIDTH * 2), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    rgb.save(buffer, format="WEBP", quality=85)
    return buffer.getvalue()


def _generation_payload(name: str, *, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    return {
        "model": model,
        "prompt": prompt_for(name),
        "size": SIZE,
        "ratio": RATIO,
        "return_base64": True,
    }


async def _existing_banners(context: AppContext) -> set[str]:
    rows, _total = await context.objects.list_for(THEME_OWNER, 1, 50)
    return {
        str(row["metadata"].get(THEME_BANNER_KEY, ""))
        for row in rows
        if row["metadata"].get(THEME_BANNER_KEY)
    }


async def _clear_theme(context: AppContext) -> int:
    rows, _total = await context.objects.list_for(THEME_OWNER, 1, 50)
    for row in rows:
        await context.objects.delete(str(row["id"]))
    return len(rows)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


async def run(
    config_path: str | None, *, force: bool, env_file: str | None = None
) -> int:
    """Generate the missing banners (everything with ``--force``)."""
    dotenv_path = resolve_dotenv_path(env_file, config_path)
    key = resolve_key(os.environ, dotenv_path)
    if not key:
        print(
            f"AGNES_API_KEY is not set (env var or {dotenv_path}). Nothing generated; "
            "the app keeps rendering the themeless default.",
            file=sys.stderr,
        )
        return 2
    endpoint = resolve_endpoint(os.environ, dotenv_path)
    model = resolve_model(os.environ, dotenv_path)
    context = AppContext.build(load_config(config_path))
    try:
        await context.database.start()
        if force:
            removed = await _clear_theme(context)
            if removed:
                print(f"Removed {removed} existing theme image(s).")
            missing = list(BANNERS)
        else:
            present = await _existing_banners(context)
            missing = [name for name in BANNERS if name not in present]
            if not missing:
                print(
                    "Theme already generated; pass --force to wipe and regenerate.",
                    file=sys.stderr,
                )
                return 1
            if present:
                print(f"Resuming with {len(missing)} missing banner(s).")
        for name in missing:
            print(f"Generating {name} ...", flush=True)

            def fetch_and_convert(target: str = name) -> bytes:
                payload = _generation_payload(target, model=model)
                raw = _fetch_pixels(key, payload, endpoint=endpoint)
                return _to_webp(raw)

            try:
                webp = await asyncio.to_thread(fetch_and_convert)
            except (urllib.error.URLError, ValueError, OSError) as error:
                print(f"Failed to generate {name!r}: {error}", file=sys.stderr)
                print(
                    "Rerun (it resumes) or pass --force to start over.",
                    file=sys.stderr,
                )
                return 1
            await context.objects.upload(
                f"theme_{name}.webp",
                webp,
                {
                    "owner": THEME_OWNER,
                    "original_filename": f"theme_{name}.webp",
                    "alt_text": f"{name} banner",
                    "upload_time": _now_iso(),
                    "content_type": "image/webp",
                    THEME_BANNER_KEY: name,
                },
            )
            print(f"Stored {name}.")
        print(f"Theme complete: {len(BANNERS)} banner(s). Restart the app to apply it.")
        return 0
    finally:
        await context.close()


def build_parser() -> argparse.ArgumentParser:
    """CLI parser (tested without touching the network)."""
    parser = argparse.ArgumentParser(
        prog="neoblogger-theme",
        description="Generate deploy-time theme artwork once (Agnes Image 2.5).",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="Path to neo-blogger.toml configuration file.",
    )
    parser.add_argument(
        "--env-file",
        "-e",
        default=None,
        help="Path to .env file for AGNES_API_KEY (default: ./.env).",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    generate = subparsers.add_parser("generate", help="Generate missing banners.")
    generate.add_argument(
        "--force",
        action="store_true",
        help="Wipe the existing set and regenerate everything.",
    )
    generate.set_defaults(func=run)
    return parser


def main(argv: list[str] | None = None) -> None:
    """Entry point: ``neoblogger-theme [-c CONFIG] [-e ENV] generate [--force]``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    code = asyncio.run(args.func(args.config, force=args.force, env_file=args.env_file))
    if code != 0:
        sys.exit(code)


if __name__ == "__main__":
    main()
