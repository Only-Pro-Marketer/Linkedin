"""Images for LinkedIn posts.

Uses kie.ai (default model google/nano-banana) when KIE_API_KEY is set, and
Google Gemini when only GEMINI_API_KEY is set. Images are saved under
dashboard/static/images/generated and attached to the post for review;
nothing is published until the post is approved.
"""

import base64
import json
import logging
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from config import settings
from database.models import QueuedPost
from utils.netguard import UnsafeURLError, check_public_url

logger = logging.getLogger(__name__)

IMAGES_DIR = Path("dashboard/static/images/generated")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

KIE_BASE = "https://api.kie.ai/api/v1/jobs"
POLL_SECONDS = 3
KIE_TIMEOUT_SECONDS = 150
MAX_IMAGE_BYTES = 15 * 1024 * 1024
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp"}
NO_PROVIDER = "Add KIE_API_KEY (kie.ai) or GEMINI_API_KEY to .env to generate images, then restart the app."


class ImageError(RuntimeError):
    """Image generation failed; the message is safe to show to the user."""


def _build_image_prompt(post_content: str, topic: str = "") -> str:
    """Prompt for a feed image. It never asks for facts the post doesn't contain."""
    return (
        "Create a clean, professional image for a LinkedIn post that stops the scroll in a feed. "
        "Style: modern, minimal, high contrast, premium.\n"
        "Avoid text in the image. If text truly helps, use at most one short phrase taken word for word "
        "from the post. Never invent numbers, statistics, charts with values, logos or brand names, and "
        "don't show recognizable real people. No watermarks.\n\n"
        f"Post topic: {topic or 'business'}\n\n"
        f"Post (context only):\n{post_content[:800]}"
    )


def provider_name() -> str | None:
    if settings.KIE_API_KEY:
        return "kie"
    if settings.GEMINI_API_KEY:
        return "gemini"
    return None


def _save(image_bytes: bytes, ext: str) -> str:
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    (IMAGES_DIR / filename).write_bytes(image_bytes)
    return f"/static/images/generated/{filename}"


def _kie_json(resp: httpx.Response) -> dict:
    """kie.ai reports errors both as HTTP status and as a `code` field in the body."""
    if resp.status_code == 401:
        raise ImageError("kie.ai rejected the API key. Check KIE_API_KEY in .env.")
    try:
        data = resp.json()
    except ValueError:
        raise ImageError(f"kie.ai answered {resp.status_code} without details.") from None
    code = data.get("code", resp.status_code)
    if code == 401:
        raise ImageError("kie.ai rejected the API key. Check KIE_API_KEY in .env.")
    if code == 402:
        raise ImageError("Your kie.ai account is out of credits.")
    if code == 429:
        raise ImageError("kie.ai is rate limiting requests. Try again in a minute.")
    if resp.status_code >= 400 or code != 200:
        raise ImageError(f"kie.ai error {code}: {str(data.get('msg') or '')[:150]}")
    return data


def remove_post_image(db: Session, post_id: int) -> bool:
    """Detach and delete a post's image (works without any image key)."""
    post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
    if not post:
        return False
    if post.image_path:
        old_file = Path("dashboard" + post.image_path)
        if old_file.exists():
            old_file.unlink()
    post.image_path = None
    post.image_prompt = None
    post.has_image = False
    db.commit()
    return True


class ImageGenerator:
    """Generates an image for a post with kie.ai or Gemini."""

    def __init__(self, provider: str | None = None, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep):
        self.provider = provider or provider_name()
        if not self.provider:
            raise ValueError(NO_PROVIDER)
        self._transport = transport  # tests inject httpx.MockTransport
        self._sleep = sleep

    def generate_image(self, post_content: str, topic: str = "") -> dict:
        """{'success', 'image_path', 'image_prompt', 'provider', 'credits'} or {'success': False, 'error'}."""
        prompt = _build_image_prompt(post_content, topic)
        try:
            result = self._kie(prompt) if self.provider == "kie" else self._gemini(prompt)
        except ImageError as e:
            logger.warning("Image generation failed (%s): %s", self.provider, e)
            return {"success": False, "error": str(e)}
        except Exception:
            logger.exception("Image generation failed (%s)", self.provider)
            return {"success": False, "error": "Image generation failed. See posting.log for details."}
        logger.info("Image generated via %s: %s", self.provider, result["image_path"])
        return {"success": True, "image_prompt": prompt, "provider": self.provider, **result}

    # ── kie.ai ────────────────────────────────────────────────

    def _client(self) -> httpx.Client:
        if self._transport:
            return httpx.Client(transport=self._transport, timeout=30)
        return httpx.Client(timeout=30)

    def _kie(self, prompt: str) -> dict:
        headers = {"Authorization": f"Bearer {settings.KIE_API_KEY}", "Content-Type": "application/json"}
        body = {"model": settings.KIE_IMAGE_MODEL,
                "input": {"prompt": prompt[:5000], "output_format": "png", "aspect_ratio": settings.KIE_IMAGE_ASPECT}}
        with self._client() as client:
            created = _kie_json(client.post(f"{KIE_BASE}/createTask", json=body, headers=headers))
            task_id = (created.get("data") or {}).get("taskId")
            if not task_id:
                raise ImageError("kie.ai didn't return a task ID.")

            deadline = time.monotonic() + KIE_TIMEOUT_SECONDS
            while True:
                info = _kie_json(client.get(f"{KIE_BASE}/recordInfo", params={"taskId": task_id},
                                            headers=headers)).get("data") or {}
                state = info.get("state")
                if state == "success":
                    break
                if state == "fail":
                    reason = info.get("failMsg") or info.get("failCode") or "unknown error"
                    raise ImageError(f"kie.ai couldn't make the image: {reason}")
                if time.monotonic() > deadline:
                    raise ImageError("kie.ai is still working on the image. Try again in a minute.")
                self._sleep(POLL_SECONDS)

            try:
                urls = json.loads(info.get("resultJson") or "{}").get("resultUrls") or []
            except ValueError:
                urls = []
            if not urls:
                raise ImageError("kie.ai finished but returned no image.")
            image_bytes, ext = self._download(client, urls[0])
        return {"image_path": _save(image_bytes, ext), "credits": info.get("creditsConsumed")}

    def _check(self, url: str) -> None:
        if self._transport is not None:  # tests: no DNS lookups
            return
        try:
            check_public_url(url)
        except UnsafeURLError as e:
            raise ImageError("kie.ai returned an image link the app won't open.") from e

    def _download(self, client: httpx.Client, url: str) -> tuple[bytes, str]:
        """Download the result right away (kie.ai links expire after about 24 hours)."""
        self._check(url)
        resp = None
        for _ in range(4):  # follow a few redirects, checking each hop
            resp = client.get(url, timeout=60)
            location = resp.headers.get("location")
            if resp.status_code in (301, 302, 303, 307, 308) and location:
                url = str(resp.url.join(location))
                self._check(url)
                continue
            break
        if resp is None or resp.status_code != 200:
            raise ImageError(f"Couldn't download the image from kie.ai ({resp.status_code if resp else 'no response'}).")
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        path = url.split("?")[0].lower()
        ext = EXTENSIONS.get(ctype) or next((e for s, e in ((".png", "png"), (".jpg", "jpg"), (".jpeg", "jpg"),
                                                             (".webp", "webp")) if path.endswith(s)), None)
        if not ext:
            raise ImageError("kie.ai returned something that isn't an image.")
        if len(resp.content) > MAX_IMAGE_BYTES:
            raise ImageError("The generated image is too large.")
        return resp.content, ext

    # ── Gemini ────────────────────────────────────────────────

    def _gemini(self, prompt: str) -> dict:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL, contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                data = part.inline_data.data
                if isinstance(data, str):
                    data = base64.b64decode(data)
                return {"image_path": _save(data, EXTENSIONS.get(part.inline_data.mime_type, "png"))}
        raise ImageError("Gemini returned no image.")

    # ── Posts ─────────────────────────────────────────────────

    def generate_for_post(self, db: Session, post_id: int) -> dict:
        """Generate an image for a queued post and attach it (replacing any old one)."""
        post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not post:
            return {"success": False, "error": "Post not found"}
        result = self.generate_image(post.user_edits or post.content, post.topic or "")
        if result["success"]:
            if post.image_path:
                old_file = Path("dashboard" + post.image_path)
                if old_file.exists():
                    old_file.unlink()
            post.image_path = result["image_path"]
            post.image_prompt = result["image_prompt"]
            post.has_image = True
            db.commit()
            logger.info("Image saved for post #%s: %s", post_id, post.image_path)
        return result

    def remove_image(self, db: Session, post_id: int) -> bool:
        return remove_post_image(db, post_id)
