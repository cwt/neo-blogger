"""Vendored font tests: conditional loading contract, self-only CSP (§10, §17)."""

import re
from pathlib import Path
from typing import Any

from .conftest import body_of

STATIC_DIR = (
    Path(__file__).resolve().parent.parent / "neoblogger" / "app" / "web" / "static"
)


def test_fonts_css_is_self_only() -> None:
    css = (STATIC_DIR / "fonts.css").read_text(encoding="utf-8")
    assert "@font-face" in css
    # Every face points inside /static/fonts/; no CDN at runtime (§10, §15.4).
    for url in re.findall(r"url\((['\"]?)([^)'\"]+)\1\)", css):
        path = url[1]
        assert path.startswith("/static/fonts/"), path
        assert path.endswith(".woff2")


def test_every_referenced_font_file_exists() -> None:
    css = (STATIC_DIR / "fonts.css").read_text(encoding="utf-8")
    referenced = re.findall(r"url\((['\"]?)(/static/fonts/[^)'\"]+)\1\)", css)
    assert len(referenced) > 500
    for _, path in referenced:
        assert (STATIC_DIR / path.removeprefix("/static/")).is_file(), path


def test_all_faces_use_swap() -> None:
    css = (STATIC_DIR / "fonts.css").read_text(encoding="utf-8")
    faces = css.count("@font-face")
    swaps = css.count("font-display: swap")
    assert faces == swaps, f"{faces} faces vs {swaps} swap declarations"


def test_per_script_families_have_no_latin_faces() -> None:
    """A Thai-less page must not download Thai Looped (the core contract).

    Each per-script family keeps only its native-block faces, so the
    browser's unicode-range mechanism fetches them exclusively when the
    page renders those characters.
    """
    css = (STATIC_DIR / "fonts.css").read_text(encoding="utf-8")
    blocks = re.findall(r"(@font-face\s*\{[^}]*\})", css, re.DOTALL)
    native_tokens = {
        "Thai Looped": "U+0E01-0E5B",
        "Hebrew": "U+0590-05FF",
        "Arabic": "U+0600-06FF",
    }
    for key, token in native_tokens.items():
        matching = [b for b in blocks if f"IBM Plex Sans {key}';" in b]
        assert len(matching) == 2, f"unexpected face count for {key}"
        assert all(token in b for b in matching), f"{key} missing native range"
        assert all("U+0000-00FF" not in b for b in matching), f"{key} covers latin"
    # JP/KR/SC/TC are slice-based: hundreds of unlabeled native faces each.
    for key in ("JP", "KR", "SC", "TC"):
        count = css.count(f"IBM Plex Sans {key}';")
        assert count > 100, f"suspicious slice count for {key}: {count}"


def test_latin_cyrillic_greek_in_base_sans() -> None:
    css = (STATIC_DIR / "fonts.css").read_text(encoding="utf-8")
    sans_faces = css.count("'IBM Plex Sans';")
    assert sans_faces >= 12  # latin/latin-ext/cyrillic-ext/cyrillic/greek/vietnamese


async def test_pages_link_fonts_and_font_files_serve_cached(app: Any) -> None:
    client = app.test_client()
    rendered = await body_of(await client.get("/"))
    assert "/static/fonts.css" in rendered
    css_response = await client.get("/static/fonts.css")
    css_response = await client.get("/static/fonts.css")
    assert css_response.status_code == 200
    assert "immutable" in css_response.headers["Cache-Control"]
    match = re.search(
        r"url\((/static/fonts/[^)']+\.woff2)\)", await body_of(css_response)
    )
    assert match is not None
    font_response = await client.get(match.group(1))
    assert font_response.status_code == 200
    assert "immutable" in font_response.headers["Cache-Control"]
