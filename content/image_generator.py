"""Image generation for LinkedIn posts using Gemini (Nano Banana) API."""

import base64
import logging
import uuid
from pathlib import Path

from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from config import settings
from database.models import QueuedPost

logger = logging.getLogger(__name__)

IMAGES_DIR = Path("dashboard/static/images/generated")
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _build_image_prompt(post_content: str, topic: str = "") -> str:
    """Build an image generation prompt from a LinkedIn post's content."""
    return (
        "Create a clean, professional, visually compelling image for a LinkedIn post. "
        "The image should work as a standalone visual that grabs attention in a feed. "
        "Style: modern, minimal, high-contrast, bold typography if text is needed. "
        "Do NOT include any watermarks or logos. "
        "The image should feel premium and authoritative.\n\n"
        f"Post topic: {topic or 'business / entrepreneurship'}\n\n"
        f"Post content (for context, do NOT put all this text in the image):\n"
        f"{post_content[:500]}"
    )


class ImageGenerator:
    """Generates images for LinkedIn posts using Gemini's native image generation."""

    def __init__(self):
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set in .env")
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def generate_image(self, post_content: str, topic: str = "") -> dict:
        """Generate an image for a LinkedIn post.

        Returns dict with 'success', 'image_path', 'image_prompt' on success,
        or 'success': False, 'error' on failure.
        """
        prompt = _build_image_prompt(post_content, topic)

        try:
            response = self.client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            # Extract image from response parts
            for part in response.candidates[0].content.parts:
                if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                    # Save image to disk
                    ext = part.inline_data.mime_type.split("/")[-1]
                    if ext == "jpeg":
                        ext = "jpg"
                    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
                    filepath = IMAGES_DIR / filename

                    image_bytes = part.inline_data.data
                    if isinstance(image_bytes, str):
                        image_bytes = base64.b64decode(image_bytes)

                    filepath.write_bytes(image_bytes)

                    relative_path = f"/static/images/generated/{filename}"
                    logger.info("Image generated: %s", relative_path)
                    return {
                        "success": True,
                        "image_path": relative_path,
                        "image_prompt": prompt,
                    }

            logger.warning("No image found in Gemini response")
            return {"success": False, "error": "No image in response"}

        except Exception as e:
            logger.error("Image generation failed: %s", e)
            return {"success": False, "error": str(e)}

    def generate_for_post(self, db: Session, post_id: int) -> dict:
        """Generate an image for a specific queued post and update the DB record."""
        post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not post:
            return {"success": False, "error": "Post not found"}

        result = self.generate_image(post.content, post.topic or "")

        if result["success"]:
            # Delete old image if exists
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
        """Remove the image from a post."""
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
