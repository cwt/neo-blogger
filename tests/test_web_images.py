"""Web-level image tests: upload, serving, alt text, deletion guard (§10)."""

from typing import Any

from .conftest import body_of, csrf_token_from
from .test_web_blog import signup


def tiny_webp_bytes() -> bytes:
    """A real 1x1 WebP built with Pillow (content verification must pass)."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buffer, format="WEBP")
    return buffer.getvalue()


def tiny_png_bytes() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def tiny_gif_bytes() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("P", (2, 2)).save(buffer, format="GIF")
    return buffer.getvalue()


def _storage(filename: str, payload: bytes) -> Any:
    """A werkzeug FileStorage for the test client's multipart upload."""
    import io

    from werkzeug.datastructures import FileStorage

    return FileStorage(stream=io.BytesIO(payload), filename=filename)


async def upload_image(app: Any, client: Any, filename: str, payload: bytes) -> str:
    """Upload through the web form; returns the object hex id."""
    import io

    from werkzeug.datastructures import FileStorage

    page = await client.get("/upload")
    token = csrf_token_from(await body_of(page))
    storage = FileStorage(stream=io.BytesIO(payload), filename=filename)
    response = await client.post(
        "/upload", form={"csrftoken": token}, files={"image": storage}
    )
    assert response.status_code == 302, await body_of(response)
    flashed = await body_of(await client.get("/upload"))
    assert "/images/" in flashed, flashed
    import re

    match = re.search(r"/images/([0-9a-f]{24})\.webp", flashed)
    assert match is not None
    return match.group(1)


async def test_upload_converts_and_serves_webp(app: Any) -> None:
    client = await signup(app, "root")
    object_id = await upload_image(app, client, "photo.png", tiny_png_bytes())
    served = await client.get(f"/images/{object_id}.webp")
    assert served.status_code == 200
    body = await served.get_data()
    assert body[:4] == b"RIFF"  # real WebP payload (converted at save time)
    assert served.headers["Content-Type"].startswith("image/webp")
    assert "immutable" in served.headers["Cache-Control"]
    assert served.headers["ETag"].startswith('"')


async def test_gif_upload_flattens_and_serves_webp(app: Any) -> None:
    client = await signup(app, "root")
    object_id = await upload_image(app, client, "anim.gif", tiny_gif_bytes())
    served = await client.get(f"/images/{object_id}.webp")
    assert served.status_code == 200
    assert (await served.get_data())[:4] == b"RIFF"


async def test_legacy_variant_conversion(app: Any) -> None:
    client = await signup(app, "root")
    object_id = await upload_image(app, client, "photo.png", tiny_png_bytes())
    legacy = await client.get(f"/images/{object_id}.jpg")
    assert legacy.status_code == 200
    body = await legacy.get_data()
    assert body[:8] == b"\xff\xd8\xff\xe0\x00\x10JFIF"[:8] or body[:2] == b"\xff\xd8"
    assert legacy.headers["Content-Type"].startswith("image/jpeg")


async def test_conditional_request_returns_304(app: Any) -> None:
    client = await signup(app, "root")
    object_id = await upload_image(app, client, "photo.png", tiny_png_bytes())
    first = await client.get(f"/images/{object_id}.webp")
    etag = first.headers["ETag"]
    conditional = await client.get(
        f"/images/{object_id}.webp", headers={"If-None-Match": etag}
    )
    assert conditional.status_code == 304


async def test_extension_spoofing_rejected(app: Any) -> None:
    client = await signup(app, "root")
    page = await client.get("/upload")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        "/upload",
        form={"csrftoken": token},
        files={"image": _storage("malware.png", b"#!/bin/bash\nrm -rf /\n")},
    )
    assert response.status_code == 302
    flashed = await body_of(await client.get("/upload"))
    assert "does not decode as an image" in flashed


async def test_disallowed_extension_rejected(app: Any) -> None:
    client = await signup(app, "root")
    page = await client.get("/upload")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        "/upload",
        form={"csrftoken": token},
        files={"image": _storage("doc.pdf", b"%PDF-1.4 fake")},
    )
    assert response.status_code == 302
    flashed = await body_of(await client.get("/upload"))
    assert "only common image formats" in flashed


async def test_member_sees_own_images_admin_sees_all(app: Any) -> None:
    root_client = await signup(app, "root")
    admin_object = await upload_image(app, root_client, "admins.png", tiny_png_bytes())
    user_client = await signup(app, "user")
    user_object = await upload_image(app, user_client, "users.png", tiny_png_bytes())
    user_gallery = await body_of(await user_client.get("/upload"))
    assert user_object in user_gallery
    assert admin_object not in user_gallery
    admin_gallery = await body_of(await root_client.get("/upload"))
    assert user_object in admin_gallery
    assert admin_object in admin_gallery


async def test_alt_text_inline_save(app: Any) -> None:
    client = await signup(app, "root")
    object_id = await upload_image(app, client, "photo.png", tiny_png_bytes())
    page = await client.get("/upload")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        f"/images/{object_id}/alt",
        form={"csrftoken": token, "alt_text": "A better description"},
    )
    assert response.status_code == 302
    context = app.extensions["neoblogger_context"]
    registry = await context.objects.metadata(object_id)
    assert registry is not None
    assert registry["metadata"]["alt_text"] == "A better description"


async def test_oversized_upload_rejected_at_server_limit(app: Any) -> None:
    from neoblogger import build_app
    from neoblogger.app.config import RuntimeConfig

    config = RuntimeConfig()
    config.database.path = app.extensions["neoblogger_context"].config.database.path
    config.uploads.max_body_bytes = 1024
    tiny = build_app(config)
    context = tiny.extensions["neoblogger_context"]
    await context.database.start()
    client = tiny.test_client()
    await client.post(
        "/signup",
        form={
            "display_name": "root",
            "email": "root@example.com",
            "password": "sturdy-password",
            "question_code": "first-pet",
            "answer": "Snowball",
        },
    )
    page = await client.get("/upload")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        "/upload",
        form={"csrftoken": token},
        files={"image": _storage("big.png", b"x" * 100_000)},
    )
    assert response.status_code == 413
    await context.database.close()


async def test_serve_without_upload_time_omits_last_modified(app: Any) -> None:
    client = await signup(app, "user")
    object_id = await upload_image(app, client, "photo.png", tiny_png_bytes())
    context = app.extensions["neoblogger_context"]

    def null_upload_time() -> None:
        context.database.connection.fs.files.update_one(
            {"_id": object_id}, {"$set": {"metadata.upload_time": None}}
        )

    await context.database.run(null_upload_time)
    response = await client.get(f"/images/{object_id}.webp")
    assert response.status_code == 200
    assert "Last-Modified" not in response.headers


async def test_deletion_guard_covers_legacy_format_variant(app: Any) -> None:
    from .test_web_blog import write_article

    user_client = await signup(app, "user")
    object_id = await upload_image(app, user_client, "cover.png", tiny_png_bytes())
    await write_article(
        app,
        user_client,
        title="Legacy covered",
        publish=True,
        cover=f"/images/{object_id}.jpg",
    )
    page = await user_client.get("/upload")
    token = csrf_token_from(await body_of(page))
    refused = await user_client.post(
        f"/images/{object_id}/delete", form={"csrftoken": token}
    )
    assert refused.status_code == 302
    context = app.extensions["neoblogger_context"]
    assert await context.objects.metadata(object_id) is not None


async def test_deletion_guard_refuses_article_covers(app: Any) -> None:
    from .test_web_blog import write_article

    user_client = await signup(app, "user")
    object_id = await upload_image(app, user_client, "cover.png", tiny_png_bytes())
    cover_url = f"/images/{object_id}.webp"
    article_id = await write_article(
        app, user_client, title="Covered", publish=True, cover=cover_url
    )
    page = await user_client.get("/upload")
    token = csrf_token_from(await body_of(page))
    refused = await user_client.post(
        f"/images/{object_id}/delete", form={"csrftoken": token}
    )
    assert refused.status_code == 302
    context = app.extensions["neoblogger_context"]
    assert await context.objects.metadata(object_id) is not None
    assert await context.articles.by_id(article_id) is not None
    # Remove the cover usage, then deletion succeeds.
    await context.articles.update(
        article_id,
        title="Covered",
        subtitle="sub",
        body="body",
        cover_url="",
        tags=[],
        status="published",
    )
    allowed = await user_client.post(
        f"/images/{object_id}/delete", form={"csrftoken": token}
    )
    assert allowed.status_code == 302
    assert await context.objects.metadata(object_id) is None


async def test_cover_picker_lists_uploads(app: Any) -> None:
    user_client = await signup(app, "user")
    object_id = await upload_image(app, user_client, "cover.png", tiny_png_bytes())
    rendered = await body_of(await user_client.get("/write"))
    assert f'data-cover-url="/images/{object_id}.webp"' in rendered
    assert f"<code>{object_id}.webp</code>" in rendered


async def test_cover_picker_empty_state(app: Any) -> None:
    user_client = await signup(app, "user")
    rendered = await body_of(await user_client.get("/write"))
    assert "upload an image" in rendered
    assert "data-cover-url" not in rendered
