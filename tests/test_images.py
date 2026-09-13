"""Post images through kie.ai, clear errors, and removing images without any key."""

import json

import httpx
import pytest

from config import settings
from tests.conftest import make_post

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def kie(monkeypatch, tmp_path):
    """Fake kie.ai: createTask → recordInfo (generating, then success) → image download."""
    import content.image_generator as ig

    monkeypatch.setattr(settings, "KIE_API_KEY", "test-kie")
    monkeypatch.setattr(ig, "IMAGES_DIR", tmp_path)
    state = {"states": ["generating", "success"], "create_code": 200, "fail": False}

    def handler(request: httpx.Request):
        if request.url.path.endswith("/createTask"):
            state["body"] = json.loads(request.content)
            code = state["create_code"]
            return httpx.Response(200, json={"code": code, "msg": "success" if code == 200 else "insufficient credits",
                                             "data": {"taskId": "task_1"}})
        if request.url.path.endswith("/recordInfo"):
            s = "fail" if state["fail"] else (state["states"].pop(0) if state["states"] else "success")
            data = {"taskId": "task_1", "state": s, "failMsg": "content policy" if s == "fail" else "",
                    "creditsConsumed": 4}
            if s == "success":
                data["resultJson"] = json.dumps({"resultUrls": ["https://files.example/img.png"]})
            return httpx.Response(200, json={"code": 200, "msg": "success", "data": data})
        if request.url.host == "files.example":
            return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real = ig.ImageGenerator
    monkeypatch.setattr(ig, "ImageGenerator",
                        lambda *a, **k: real(*a, transport=transport, sleep=lambda s: None, **k))
    return state


def test_kie_image_is_attached_to_the_post(client, db, kie, tmp_path):
    post = make_post(db)
    r = client.post(f"/api/queue/{post.id}/generate-image")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "kie" and body["credits"] == 4
    db.refresh(post)
    assert post.has_image and post.image_path.endswith(".png")
    assert (tmp_path / post.image_path.rsplit("/", 1)[1]).read_bytes() == PNG
    sent = kie["body"]
    assert sent["model"] == "google/nano-banana" and sent["input"]["aspect_ratio"] == settings.KIE_IMAGE_ASPECT
    assert "Never invent numbers" in sent["input"]["prompt"]


def test_kie_failure_is_explained(client, db, kie):
    kie["fail"] = True
    post = make_post(db)
    r = client.post(f"/api/queue/{post.id}/generate-image")
    assert r.status_code == 502 and "content policy" in r.json()["error"]
    db.refresh(post)
    assert not post.has_image


def test_kie_out_of_credits(client, db, kie):
    kie["create_code"] = 402
    post = make_post(db)
    r = client.post(f"/api/queue/{post.id}/generate-image")
    assert r.status_code == 502 and "out of credits" in r.json()["error"]


def test_no_image_key_and_removal_still_works(client, db, monkeypatch):
    monkeypatch.setattr(settings, "KIE_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    post = make_post(db)
    r = client.post(f"/api/queue/{post.id}/generate-image")
    assert r.status_code == 400 and "KIE_API_KEY" in r.json()["error"]
    post.image_path, post.has_image = "/static/images/generated/missing.png", True
    db.commit()
    assert client.delete(f"/api/queue/{post.id}/image").status_code == 200
    db.refresh(post)
    assert not post.has_image and post.image_path is None
