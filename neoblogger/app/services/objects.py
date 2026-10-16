"""Image-object workflows (spec §10, tech-req §9).

Pillow work is CPU-bound and runs on the separate image executor (§5.6),
never on the event loop and never queued behind DB work. Uploads are
extension-allowlisted, content-verified, converted to WebP (quality 85,
transparency flattened onto white), and registered with metadata whose
alt text is seeded from the original filename (§10.2).
"""

import datetime
import io
import re
import secrets
from collections.abc import Callable
from typing import Any

from PIL import Image

from ..repositories.articles import ArticleRepository
from ..repositories.documents import ArticleDocument, MemberDocument
from ..repositories.objects import ObjectRepository
from .theme import THEME_OWNER

__all__ = ["ImageRejectedError", "ObjectsService"]

_ALLOWED_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif"})
_SANITIZER = re.compile(r"[^a-z0-9_-]+")

type ImageRunner = Callable[[Callable[[], Any]], Any]
_LEGACY_EXTENSIONS = frozenset({"jpg", "jpeg", "png"})


class ImageRejectedError(Exception):
    """Raised for extension, size, or content-verification failures (§10.2)."""


def _decoded_rgb(payload: bytes) -> Image.Image:
    """Decode (content verification) and flatten transparency onto white.

    Runs on the image executor; shared by the WebP and legacy conversions
    (spec §10.2, §10.4).
    """
    image: Image.Image = Image.open(io.BytesIO(payload))
    image.load()
    if image.mode in ("RGBA", "LA", "PA", "P"):
        flattened = image.convert("RGBA")
        background = Image.new("RGB", flattened.size, (255, 255, 255))
        background.paste(flattened, mask=flattened.split()[-1])
        return background
    return image.convert("RGB")


def convert_to_webp(payload: bytes) -> bytes:
    """Decode (content verification) and convert to WebP; runs on the image executor.

    Transparency is flattened onto white (spec §10.2).
    """
    buffer = io.BytesIO()
    _decoded_rgb(payload).save(buffer, format="WEBP", quality=85)
    return buffer.getvalue()


_LEGACY_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}


def convert_legacy(payload: bytes, target: str) -> bytes:
    """Convert stored WebP to an older format for preview scrapers (§10.4)."""
    buffer = io.BytesIO()
    _decoded_rgb(payload).save(buffer, format=_LEGACY_FORMATS[target])
    return buffer.getvalue()


def stored_filename(owner: str, original: str) -> str:
    """``owner_original_randomsuffix`` — unique and traceable (spec §10.2)."""
    sanitized = _SANITIZER.sub("_", original.rsplit(".", 1)[0].lower()).strip("_")
    suffix = secrets.token_hex(2)
    return f"{owner}_{sanitized}_{suffix}.webp"


def legacy_url(image_url: str, extension: str = "jpg") -> str:
    """The older-format variant URL for preview metadata (§10.4, §16).

    Only local ``/images/`` URLs have server-side conversions (bugs/005).
    """
    if not image_url.startswith("/images/"):
        return image_url
    root, dot, _extension = image_url.rpartition(".")
    if not dot:
        return image_url
    return f"{root}.{extension}"


def readable_date(iso: str) -> str:
    """``Month DD, YYYY at HH:MM``; date-only at midnight (spec §16)."""
    try:
        moment = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if moment.hour == 0 and moment.minute == 0:
        return moment.strftime("%B %d, %Y")
    return moment.strftime("%B %d, %Y at %H:%M")


def derive_description(markup_body: str) -> str:
    """A plain-text description from the article body (spec §16)."""
    text = re.sub(r"[#*_>|`\[\]()!-]", " ", markup_body)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 160:
        text = text[:157].rstrip() + "…"
    return text


class ObjectsService:
    """Uploads, gallery metadata, deletion guarding (spec §10)."""

    def __init__(
        self,
        objects: ObjectRepository,
        articles: ArticleRepository,
        run_image: ImageRunner,
        max_body_bytes: int,
    ) -> None:
        self._objects = objects
        self._articles = articles
        self._run_image = run_image
        self._max_body_bytes = max_body_bytes

    async def upload(
        self, member: MemberDocument, payload: bytes, original: str
    ) -> str:
        """Validate, convert, and store an upload; returns the hex id (§10)."""
        if not original or "." not in original:
            raise ImageRejectedError("a filename with an extension is required")
        extension = original.rsplit(".", 1)[1].lower()
        if extension not in _ALLOWED_EXTENSIONS:
            raise ImageRejectedError("only common image formats are accepted")
        if len(payload) > self._max_body_bytes:
            raise ImageRejectedError("the image is too large")
        try:

            def conversion() -> bytes:
                return convert_to_webp(payload)

            webp_payload = await self._run_image(conversion)
        except Exception as error:
            raise ImageRejectedError("the file does not decode as an image") from error
        if not webp_payload:
            raise ImageRejectedError("the file does not decode as an image")
        name = stored_filename(member["display_name"], original)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        return await self._objects.upload(
            name,
            webp_payload,
            {
                "owner": member["display_name"],
                "original_filename": original,
                "alt_text": original.rsplit(".", 1)[0],
                "upload_time": now,
                "content_type": "image/webp",
            },
        )

    async def alt_text_for(
        self, viewer: MemberDocument, object_id: str, alt_text: str
    ) -> bool:
        """Owner-or-administrator alt-text update (§10.3); only alt text."""
        registry = await self._objects.metadata(object_id)
        if registry is None:
            return False
        authorized = viewer["administrator"] or (
            registry["metadata"].get("owner") == viewer["display_name"]
        )
        if not authorized:
            return False
        await self._objects.update_alt_text(object_id, alt_text.strip())
        return True

    async def delete(
        self, viewer: MemberDocument, object_id: str
    ) -> tuple[bool, list[ArticleDocument]]:
        """Owner-or-admin delete, refused while an article cover (§10.5)."""
        registry = await self._objects.metadata(object_id)
        if registry is None:
            return False, []
        if registry["metadata"].get("owner") == THEME_OWNER:
            return False, []
        authorized = viewer["administrator"] or (
            registry["metadata"].get("owner") == viewer["display_name"]
        )
        if not authorized:
            return False, []
        # Covers may be referenced in any served format variant (.webp as
        # stored, or a legacy .jpg/.jpeg/.png URL pasted into the editor),
        # so guard against all of them (§10.5).
        variants = [
            f"/images/{object_id}.{extension}"
            for extension in ("webp", "jpg", "jpeg", "png")
        ]
        using = await self._articles.covers_using_image(object_id, variants)
        if using:
            return False, using
        await self._objects.delete(object_id)
        return True, []
