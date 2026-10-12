"""Image uploads, gallery, serving, alt text, deletion (spec §10)."""

import datetime
import json
from functools import partial
from typing import Any

from quart import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
)
from quart import (
    Response as QuartResponse,
)
from werkzeug.exceptions import abort as _abort
from werkzeug.wrappers import Response as WerkzeugResponse

from ..context import AppContext
from ..services.objects import ImageRejectedError, convert_legacy

__all__ = ["create_images_blueprint"]

_GALLERY_PAGE_SIZE = 12
_CONVERSION_CAP = 20 * 1024 * 1024
_YEAR_SECONDS = 31_536_000


def _content_type_for(extension: str) -> str:
    return {
        "webp": "image/webp",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }.get(extension, "application/octet-stream")


def create_images_blueprint(context: AppContext) -> Blueprint:
    blueprint = Blueprint("images", __name__)

    @blueprint.route("/upload/editor", methods=["POST"])
    async def upload_for_editor() -> QuartResponse:
        """JSON upload for the editor's image button (spec §10.1).

        The client sends the CSRF token in the X-CSRFToken header (§15.2).
        """
        if g.member is None:
            return QuartResponse(
                json.dumps({"error": "sign in first"}),
                status=401,
                content_type="application/json",
            )
        files = await request.files
        file = files.get("image")
        if file is None:
            return QuartResponse(
                json.dumps({"error": "no image"}),
                status=400,
                content_type="application/json",
            )
        try:
            object_id = await context.objects_service.upload(
                g.member, file.read(), file.filename or ""
            )
        except ImageRejectedError as error:
            return QuartResponse(
                json.dumps({"error": str(error)}),
                status=422,
                content_type="application/json",
            )
        return QuartResponse(
            json.dumps({"url": f"/images/{object_id}.webp"}),
            content_type="application/json",
        )

    @blueprint.route("/upload", methods=["GET", "POST"])
    async def upload() -> str | WerkzeugResponse:
        if g.member is None:
            await flash("Sign in to upload images.", "error")
            return redirect("/signin")
        if request.method == "POST":
            files = await request.files
            file = files.get("image")
            if file is None:
                await flash("Choose an image to upload.", "error")
                return redirect("/upload")
            payload = file.read()
            try:
                object_id = await context.objects_service.upload(
                    g.member, payload, file.filename or ""
                )
            except ImageRejectedError as error:
                await flash(str(error), "error")
                return redirect("/upload")
            await flash(f"Uploaded: /images/{object_id}.webp", "success")
            return redirect("/upload")
        page = 1
        try:
            page = int(request.args.get("page", "1"))
        except ValueError:
            page = 1
        page = max(1, page)
        owner = None if g.member["administrator"] else g.member["display_name"]
        rows, total = await context.objects.list_for(owner, page, _GALLERY_PAGE_SIZE)
        g.breadcrumbs = [("Home", "/"), ("Upload image", "/upload")]
        return await render_template(
            "upload.html",
            images=rows,
            page=page,
            per_page=_GALLERY_PAGE_SIZE,
            has_more=total > page * _GALLERY_PAGE_SIZE,
            admin_view=g.member["administrator"],
        )

    @blueprint.route("/images/<hexid:object_id>.<extension>")
    async def serve(object_id: str, extension: str) -> WerkzeugResponse:
        registry = await context.objects.metadata(object_id)
        if registry is None or extension not in ("webp", "jpg", "jpeg", "png"):
            _abort(404)
        etag = registry["md5"]
        if request.if_none_match and etag in request.if_none_match:
            response = WerkzeugResponse("", status=304)
            response.headers["Cache-Control"] = (
                f"public, max-age={_YEAR_SECONDS}, immutable"
            )
            response.headers["ETag"] = f'"{etag}"'
            last_modified = _http_date(registry)
            if last_modified:
                response.headers["Last-Modified"] = last_modified
            return response

        payload = await context.objects.data(object_id)
        if payload is None:
            _abort(404)
        target = ""
        content_type = _content_type_for(extension)
        if extension != "webp":
            target = "jpg" if extension in ("jpg", "jpeg") else "png"
        if target:
            if len(payload) <= _CONVERSION_CAP:
                payload = await context.run_image(
                    partial(convert_legacy, payload, target)
                )
            else:
                content_type = "image/webp"

        response = WerkzeugResponse(payload)
        response.headers["Content-Type"] = content_type
        response.headers["Cache-Control"] = (
            f"public, max-age={_YEAR_SECONDS}, immutable"
        )
        response.headers["ETag"] = f'"{etag}"'
        last_modified = _http_date(registry)
        if last_modified:
            response.headers["Last-Modified"] = last_modified
        return response

    @blueprint.route("/images/<hexid:object_id>/alt", methods=["POST"])
    async def set_alt_text(object_id: str) -> WerkzeugResponse:
        if g.member is None:
            await flash("Sign in first.", "error")
            return redirect("/signin")
        form = await request.form
        ok = await context.objects_service.alt_text_for(
            g.member, object_id, form.get("alt_text", "")
        )
        await flash(
            "Alt text saved." if ok else "You cannot edit that image.",
            "success" if ok else "error",
        )
        return redirect("/upload")

    @blueprint.route("/images/<hexid:object_id>/delete", methods=["POST"])
    async def delete(object_id: str) -> WerkzeugResponse:
        if g.member is None:
            await flash("Sign in first.", "error")
            return redirect("/signin")
        ok, using = await context.objects_service.delete(g.member, object_id)
        if ok:
            await flash("Image deleted.", "success")
            return redirect("/upload")
        if using:
            titles = ", ".join(str(article.get("title", "")) for article in using)
            await flash(
                f"In use as an article cover by {len(using)} article(s): {titles}.",
                "error",
            )
        else:
            await flash("You cannot delete that image.", "error")
        return redirect("/upload")

    return blueprint


def _http_date(registry: dict[str, Any]) -> str:
    upload_time = registry["metadata"].get("upload_time", "")
    try:
        moment = datetime.datetime.fromisoformat(upload_time)
    except TypeError, ValueError:
        return ""
    return moment.strftime("%a, %d %b %Y %H:%M:%S GMT")
