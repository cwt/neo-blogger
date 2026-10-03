"""Fetch and vendor the IBM Plex webfonts (tech-req §10, §19.1).

Provenance policy (run to re-vendor):

    uv run python tools/fetch_fonts.py

1. Google Fonts css2 API (woff2 UA) for the families that ship there,
   one request per family. For per-script families the latin/cyrillic/
   greek/vietnamese subset faces are DROPPED, so their faces only match
   their own script's unicode-range and a page without, say, Thai never
   downloads Thai Looped (spec: load only what the screen shows).
2. ``@ibm/plex-sans-sc`` / ``@ibm/plex-sans-tc`` npm packages for the
   Simplified/Traditional Chinese families, which Google Fonts does not
   host. IBM ships unicode-range-split woff2 (216 slices per weight); the
   Regular and SemiBold weights are vendored with ``font-display: swap``
   added (IBM's CSS omits it).

Everything lands in ``neoblogger/app/web/static/fonts`` plus a merged
``neoblogger/app/web/static/fonts.css`` whose URLs are CSP-``self``
paths. The vendored output is committed; this tool exists for provenance
and re-vendoring, not for runtime.
"""

import io
import re
import tarfile
import urllib.request
from pathlib import Path

__all__ = ["main"]

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "neoblogger" / "app" / "web" / "static" / "fonts"
FONTS_CSS = ROOT / "neoblogger" / "app" / "web" / "static" / "fonts.css"

DROP_SUBSETS = frozenset(
    {"latin", "latin-ext", "cyrillic", "cyrillic-ext", "vietnamese", "greek"}
)

# (family, css2 axis spec, drop the listed subsets)
GF_FAMILIES: list[tuple[str, str, bool]] = [
    ("IBM Plex Sans", "ital,wght@0,400;0,500;0,600;0,700;1,400;1,600", False),
    ("IBM Plex Mono", "wght@400;600", False),
    ("IBM Plex Sans Thai Looped", "wght@400;600", True),
    ("IBM Plex Sans Hebrew", "wght@400;600", True),
    ("IBM Plex Sans Arabic", "wght@400;600", True),
    ("IBM Plex Sans Devanagari", "wght@400;600", True),
    ("IBM Plex Sans JP", "wght@400;600", True),
    ("IBM Plex Sans KR", "wght@400;600", True),
]

IBM_PACKAGES = [
    ("IBM Plex Sans SC", "@ibm/plex-sans-sc", "1.1.0", "sc", "SC"),
    ("IBM Plex Sans TC", "@ibm/plex-sans-tc", "1.1.1", "tc", "TC"),
]
_IBM_WEIGHT_FILES = ("Regular", "SemiBold")


def _slug(family: str) -> str:
    return family.lower().replace(" ", "-")


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(request, timeout=60).read()


def _add_font_display(block: str) -> str:
    """IBM and Google CSS omit font-display; the spec requires swap (§10)."""
    if "font-display" in block:
        return block
    trimmed = block.rstrip()
    if trimmed.endswith("}"):
        return trimmed[:-1].rstrip() + "\n\tfont-display: swap;\n}"
    return block


def _google_faces(family: str, spec: str, drop_non_native: bool) -> str:
    query = f"family={family.replace(' ', '+')}:{spec}&display=swap"
    css = _fetch(f"https://fonts.googleapis.com/css2?{query}").decode("utf-8")
    face_pattern = re.compile(
        r"(/\*\s*(\S+)\s*\*/\s*)?(@font-face\s*\{[^}]*\})", re.DOTALL
    )
    downloaded: dict[str, bytes] = {}
    kept: list[str] = []
    dropped = 0
    directory = _slug(family)
    for _, label, face in face_pattern.findall(css):
        if drop_non_native and label in DROP_SUBSETS:
            dropped += 1
            continue
        match = re.search(r"url\((https://fonts\.gstatic\.com[^)]+\.woff2)\)", face)
        if match is None:
            dropped += 1
            continue
        remote = match.group(1)
        filename = remote.rsplit("/", 1)[1]
        if filename not in downloaded:
            downloaded[filename] = _fetch(remote)
        rewritten = face.replace(remote, f"/static/fonts/{directory}/{filename}")
        header = f"/* subset: {label} */\n" if label else ""
        kept.append(header + _add_font_display(rewritten))
    target = FONTS_DIR / directory
    target.mkdir(parents=True, exist_ok=True)
    for filename, payload in downloaded.items():
        (target / filename).write_bytes(payload)
    total = sum(len(payload) for payload in downloaded.values()) / 1e6
    print(f"{family}: kept {len(kept)} faces ({dropped} dropped), {total:.1f} MB")
    return "\n".join(kept)


def _ibm_faces(
    family: str, package: str, version: str, directory: str, code: str
) -> str:
    tarball_url = (
        f"https://registry.npmjs.org/{package.replace('@', '%40')}"
        f"/-/{package.split('/')[-1]}-{version}.tgz"
    )
    payload_by_name: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(_fetch(tarball_url)), mode="r:gz") as tarball:
        for member in tarball.getmembers():
            if not member.isfile():
                continue
            extracted = tarball.extractfile(member)
            if extracted is not None:
                payload_by_name[member.name] = extracted.read()

    downloaded: dict[str, bytes] = {}
    kept: list[str] = []
    for weight in _IBM_WEIGHT_FILES:
        css_name = f"package/fonts/split/woff2/hinted/IBMPlexSans{code}-{weight}.css"
        if css_name not in payload_by_name:
            print(f"warning: {css_name} missing in {package}")
            continue
        css = payload_by_name[css_name].decode("utf-8")
        pattern = re.compile(r"@font-face\s*\{[^}]*\}", re.DOTALL)
        for face in pattern.findall(css):
            match = re.search(r"url\(['\"]?([^)'\"]+\.woff2)['\"]?\)", face)
            if match is None:
                continue
            basename = match.group(1).rsplit("/", 1)[-1]
            source_name = f"package/fonts/split/woff2/hinted/{basename}"
            if basename not in downloaded:
                if source_name not in payload_by_name:
                    continue
                downloaded[basename] = payload_by_name[source_name]
            rewritten = face.replace(
                match.group(1), f"/static/fonts/{directory}/{basename}"
            )
            kept.append(_add_font_display(rewritten))
    target = FONTS_DIR / directory
    target.mkdir(parents=True, exist_ok=True)
    for filename, payload in downloaded.items():
        (target / filename).write_bytes(payload)
    total = sum(len(payload) for payload in downloaded.values()) / 1e6
    print(f"{family}: kept {len(kept)} faces, {total:.1f} MB")
    return "\n".join(kept)


def main() -> None:
    if FONTS_DIR.exists():
        for path in FONTS_DIR.rglob("*"):
            if path.is_file():
                path.unlink()
    sections = [
        "/* IBM Plex webfonts - vendored by tools/fetch_fonts.py;",
        "   families host-locally to keep the CSP self-only (spec §15.4).",
        "   Loading is conditional via unicode-range: a face is only",
        "   downloaded when the page renders characters inside its range. */\n",
    ]
    for family, spec, drop in GF_FAMILIES:
        sections.append(
            f"/* {family} (Google Fonts) */\n" + _google_faces(family, spec, drop)
        )
    for family, package, version, directory, code in IBM_PACKAGES:
        sections.append(
            f"/* {family} (IBM npm split webfonts) */\n"
            + _ibm_faces(family, package, version, directory, code)
        )
    FONTS_CSS.write_text("\n".join(sections) + "\n", encoding="utf-8")
    print(f"wrote {FONTS_CSS}")


if __name__ == "__main__":
    main()
