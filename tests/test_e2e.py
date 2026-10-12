"""End-to-end flow: register → write → publish → comment → search →
moderate (spec §20).

Everything runs offline against a real NeoSQLite temp database through
the web test client, exactly like production requests.
"""

import re
from typing import Any

from .conftest import body_of, csrf_token_from


def storage(filename: str, payload: bytes) -> Any:
    import io

    from werkzeug.datastructures import FileStorage

    return FileStorage(stream=io.BytesIO(payload), filename=filename)


def tiny_webp_bytes() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 10, 10)).save(buffer, format="WEBP")
    return buffer.getvalue()


async def signup(app: Any, display_name: str) -> Any:
    client = app.test_client()
    page = await client.get("/signup")
    token = csrf_token_from(await body_of(page))
    response = await client.post(
        "/signup",
        form={
            "display_name": display_name,
            "email": f"{display_name}@e2e.example",
            "password": "sturdy-e2e-password",
            "question_code": "first-pet",
            "answer": "Rex",
            "csrftoken": token,
        },
    )
    assert response.status_code == 302, await body_of(response)
    return client


async def test_full_flow(app: Any) -> None:
    # --- register: the first member becomes administrator and publisher ---
    root_client = await signup(app, "root")
    profile = await body_of(await root_client.get("/profile"))
    assert "Your posts" in profile
    user_client = await signup(app, "user")

    # --- moderate part 1: grant publisher to the second member ---
    context = app.extensions["neoblogger_context"]
    target = await context.members.by_display_name("user")
    assert target is not None
    page = await root_client.get("/admin")
    admin_token = csrf_token_from(await body_of(page))
    granted = await root_client.post(
        f"/admin/members/{target['_id']}/publisher", form={"csrftoken": admin_token}
    )
    assert granted.status_code == 302

    # --- upload an image and publish an article using it as the cover ---
    upload_page = await user_client.get("/upload")
    upload_token = csrf_token_from(await body_of(upload_page))
    uploaded = await user_client.post(
        "/upload",
        form={"csrftoken": upload_token},
        files={"image": storage("journey.png", tiny_webp_bytes())},
    )
    assert uploaded.status_code == 302
    upload_flashed = await body_of(await user_client.get("/upload"))
    match = re.search(r"/images/([0-9a-f]{24})\.webp", upload_flashed)
    assert match is not None
    cover_url = match.group(0)

    write_page = await user_client.get("/write")
    token = csrf_token_from(await body_of(write_page))
    published = await user_client.post(
        "/write",
        form={
            "csrftoken": token,
            "title": "E2E journey",
            "subtitle": "a full-circle tour",
            "body": (
                "The **journey** from register to moderation.\n\n- step one\n- step two"
            ),
            "cover_url": cover_url,
            "tags": "e2e, testing, journey",
            "action": "publish",
        },
    )
    assert published.status_code == 302
    assert published.headers["Location"] == "/"

    # --- comment on the published article ---
    def find_id() -> str:
        document = context.database.connection.articles.find_one(
            {"title": "E2E journey"}
        )
        assert document is not None
        return str(document["_id"])

    article_id = await context.database.run(find_id)
    article_page = await user_client.get(f"/{article_id}")
    assert "E2E journey" in await body_of(article_page)
    comment_token = csrf_token_from(await body_of(article_page))
    commented = await user_client.post(
        f"/articles/{article_id}/comments",
        form={"csrftoken": comment_token, "text": "Journey complete!"},
    )
    assert commented.status_code == 302

    # --- search finds the article for a stranger ---
    stranger = app.test_client()
    results = await body_of(await stranger.get("/search?q=journey"))
    assert "E2E journey" in results
    tag_page = await body_of(await stranger.get("/tag/e2e"))
    assert "E2E journey" in tag_page

    # --- moderate part 2: disabling hides the article everywhere ---
    disable = await root_client.post(
        f"/admin/members/{target['_id']}/disable", form={"csrftoken": admin_token}
    )
    assert disable.status_code == 302
    after_disable = await body_of(await stranger.get("/"))
    assert "E2E journey" not in after_disable
    after_search = await body_of(await stranger.get("/search?q=journey"))
    assert "E2E journey" not in after_search

    # --- re-enable restores it ---
    enable = await root_client.post(
        f"/admin/members/{target['_id']}/enable", form={"csrftoken": admin_token}
    )
    assert enable.status_code == 302
    after_enable = await body_of(await stranger.get("/"))
    assert "E2E journey" in after_enable
