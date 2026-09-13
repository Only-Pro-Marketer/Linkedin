"""GIF generation for LinkedIn posts — screen recording, programmatic animation, and upload processing."""

import io
import json
import logging
import uuid
from pathlib import Path

import imageio
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from config import settings
from database.models import QueuedPost

logger = logging.getLogger(__name__)

VIDEOS_DIR = Path(settings.VIDEO_STORAGE_DIR)
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# Default brand colors — customize to match your brand
BRAND_COLORS = {
    "dark_bg": (15, 23, 42),         # slate-900
    "card_bg": (30, 41, 59),         # slate-800
    "accent": (59, 130, 246),        # blue-500
    "accent_light": (96, 165, 250),  # blue-400
    "success": (34, 197, 94),        # green-500
    "warning": (250, 204, 21),       # yellow-400
    "white": (255, 255, 255),
    "gray": (148, 163, 184),         # slate-400
    "light_gray": (203, 213, 225),   # slate-300
}

# Font paths (macOS)
FONT_BOLD = "/System/Library/Fonts/Avenir Next.ttc"
FONT_REGULAR = "/System/Library/Fonts/Avenir Next.ttc"
FONT_FALLBACK = "/System/Library/Fonts/Geneva.ttf"


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a font, falling back to system default if not found."""
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        # Avenir Next .ttc: index 0=Regular, index 9=Bold
        return ImageFont.truetype(path, size, index=9 if bold else 0)
    except Exception:
        try:
            return ImageFont.truetype(FONT_FALLBACK, size)
        except Exception:
            return ImageFont.load_default()


def _save_gif(frames: list[Image.Image], fps: int = None) -> str:
    """Save a list of PIL images as an optimized GIF. Returns relative web path."""
    if fps is None:
        fps = settings.GIF_FPS
    duration_ms = int(1000 / fps)
    filename = f"{uuid.uuid4().hex[:12]}.gif"
    filepath = VIDEOS_DIR / filename

    # Save with optimization
    frames[0].save(
        filepath,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )

    # Check file size and reduce quality if needed
    file_size_mb = filepath.stat().st_size / (1024 * 1024)
    if file_size_mb > settings.GIF_MAX_FILE_SIZE_MB:
        logger.info("GIF too large (%.1fMB), reducing to 256 colors", file_size_mb)
        reduced = [f.quantize(colors=256, method=Image.Quantize.MEDIANCUT) for f in frames]
        reduced[0].save(
            filepath,
            save_all=True,
            append_images=reduced[1:],
            duration=duration_ms,
            loop=0,
            optimize=True,
        )

    relative_path = f"/static/videos/generated/{filename}"
    file_size_mb = filepath.stat().st_size / (1024 * 1024)
    logger.info("GIF saved: %s (%.1fMB, %d frames, %dfps)", relative_path, file_size_mb, len(frames), fps)
    return relative_path


# ─────────────────────────────────────────────────────────────
# Mode B: Programmatic Animated GIFs
# ─────────────────────────────────────────────────────────────

def _draw_rounded_rect(draw, xy, radius, fill):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    draw.pieslice([x0, y0, x0 + 2 * radius, y0 + 2 * radius], 180, 270, fill=fill)
    draw.pieslice([x1 - 2 * radius, y0, x1, y0 + 2 * radius], 270, 360, fill=fill)
    draw.pieslice([x0, y1 - 2 * radius, x0 + 2 * radius, y1], 90, 180, fill=fill)
    draw.pieslice([x1 - 2 * radius, y1 - 2 * radius, x1, y1], 0, 90, fill=fill)


def _extract_key_lines(post_content: str, max_lines: int = 5) -> list[str]:
    """Extract the most meaningful lines from a post for text_reveal GIF.

    Skips the hook (first line), hashtags, and very short/empty lines.
    Returns up to max_lines trimmed to 40 chars each.
    """
    raw_lines = post_content.strip().split("\n")
    candidates = []
    for line in raw_lines[1:]:  # skip hook (first line)
        stripped = line.strip()
        # Skip empty, hashtags, very short lines, and emoji-only lines
        if not stripped or stripped.startswith("#") or len(stripped) < 10:
            continue
        # Skip CTA-like last lines
        lower = stripped.lower()
        if any(cta in lower for cta in ["comment below", "follow me", "drop a", "let me know", "agree?", "what do you think"]):
            continue
        candidates.append(stripped)

    # Take the best lines (prefer lines that start with numbers, dashes, or arrows)
    prioritized = []
    regular = []
    for c in candidates:
        if c[0].isdigit() or c.startswith(("-", "→", "•", "✓", ">")):
            prioritized.append(c)
        else:
            regular.append(c)

    selected = (prioritized + regular)[:max_lines]

    # Trim to 40 chars max, breaking at word boundary
    result = []
    for s in selected:
        if len(s) <= 40:
            result.append(s)
        else:
            trimmed = s[:37].rsplit(" ", 1)[0] + "..."
            result.append(trimmed)

    return result or ["Key insights from this post"]


class ProgrammaticGifGenerator:
    """Creates animated GIFs from data using Pillow — no external dependencies needed."""

    WIDTH = 1080
    HEIGHT = 1080

    def generate_before_after(self, before_text: str, after_text: str,
                              metric_label: str = "", title: str = "") -> str:
        """Alternating before/after comparison GIF."""
        frames = []
        title = title or "THE TRANSFORMATION"

        for phase in ["BEFORE", "AFTER"]:
            text = before_text if phase == "BEFORE" else after_text
            color = BRAND_COLORS["warning"] if phase == "BEFORE" else BRAND_COLORS["success"]

            # Hold each frame for ~2 seconds (generate multiple copies)
            frame = Image.new("RGB", (self.WIDTH, self.HEIGHT), BRAND_COLORS["dark_bg"])
            draw = ImageDraw.Draw(frame)

            # Title
            title_font = _load_font(36, bold=True)
            draw.text((self.WIDTH // 2, 80), title, fill=BRAND_COLORS["gray"],
                       font=title_font, anchor="mm")

            # Phase label
            phase_font = _load_font(72, bold=True)
            draw.text((self.WIDTH // 2, 220), phase, fill=color,
                       font=phase_font, anchor="mm")

            # Divider line
            draw.line([(140, 300), (self.WIDTH - 140, 300)], fill=color, width=4)

            # Main text
            text_font = _load_font(48)
            y = 380
            for line in text.split("\n"):
                draw.text((self.WIDTH // 2, y), line.strip(), fill=BRAND_COLORS["white"],
                           font=text_font, anchor="mm")
                y += 70

            # Metric label at bottom
            if metric_label:
                metric_font = _load_font(28)
                draw.text((self.WIDTH // 2, self.HEIGHT - 80), metric_label,
                           fill=BRAND_COLORS["gray"], font=metric_font, anchor="mm")

            # Hold for ~2 seconds at 10fps = 20 frames
            for _ in range(20):
                frames.append(frame.copy())

        return _save_gif(frames)

    def generate_data_counter(self, metric: str, from_val: float, to_val: float,
                              unit: str = "%", title: str = "") -> str:
        """Animated counter counting from one value to another."""
        frames = []
        title = title or "THE RESULT"
        total_frames = settings.GIF_MAX_DURATION_SECONDS * settings.GIF_FPS

        # Easing function (ease-out cubic)
        def ease_out(t):
            return 1 - (1 - t) ** 3

        for i in range(total_frames):
            frame = Image.new("RGB", (self.WIDTH, self.HEIGHT), BRAND_COLORS["dark_bg"])
            draw = ImageDraw.Draw(frame)

            progress = ease_out(i / max(total_frames - 1, 1))
            current_val = from_val + (to_val - from_val) * progress

            # Title
            title_font = _load_font(36, bold=True)
            draw.text((self.WIDTH // 2, 150), title, fill=BRAND_COLORS["gray"],
                       font=title_font, anchor="mm")

            # Metric name
            metric_font = _load_font(42)
            draw.text((self.WIDTH // 2, 300), metric.upper(),
                       fill=BRAND_COLORS["accent_light"], font=metric_font, anchor="mm")

            # Big number
            if unit == "%" or unit == "x":
                display = f"{current_val:.1f}{unit}"
            elif unit == "$":
                display = f"${current_val:,.0f}"
            else:
                display = f"{current_val:,.0f} {unit}"

            number_font = _load_font(140, bold=True)
            draw.text((self.WIDTH // 2, 520), display, fill=BRAND_COLORS["white"],
                       font=number_font, anchor="mm")

            # Progress bar
            bar_x = 140
            bar_y = 700
            bar_w = self.WIDTH - 280
            bar_h = 24
            _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                               12, BRAND_COLORS["card_bg"])
            fill_w = int(bar_w * progress)
            if fill_w > 24:
                _draw_rounded_rect(draw, (bar_x, bar_y, bar_x + fill_w, bar_y + bar_h),
                                   12, BRAND_COLORS["accent"])

            # From → To labels
            label_font = _load_font(28)
            draw.text((bar_x, bar_y + 50), f"From: {from_val:.1f}{unit}",
                       fill=BRAND_COLORS["gray"], font=label_font)
            to_text = f"To: {to_val:.1f}{unit}"
            draw.text((bar_x + bar_w, bar_y + 50), to_text,
                       fill=BRAND_COLORS["success"], font=label_font, anchor="ra")

            # Branding
            brand_font = _load_font(24)
            draw.text((self.WIDTH // 2, self.HEIGHT - 60), "CONTENT ENGINE",
                       fill=BRAND_COLORS["gray"], font=brand_font, anchor="mm")

            frames.append(frame)

        # Hold final frame for 2 seconds
        for _ in range(20):
            frames.append(frames[-1].copy())

        return _save_gif(frames)

    def generate_text_reveal(self, lines: list[str], title: str = "") -> str:
        """Text appearing line by line — great for tips, stats, or quotes."""
        frames = []
        title = title or ""
        hold_frames = 15  # frames to hold after each line appears

        for reveal_count in range(1, len(lines) + 1):
            frame = Image.new("RGB", (self.WIDTH, self.HEIGHT), BRAND_COLORS["dark_bg"])
            draw = ImageDraw.Draw(frame)

            # Title
            if title:
                title_font = _load_font(40, bold=True)
                draw.text((self.WIDTH // 2, 100), title, fill=BRAND_COLORS["accent_light"],
                           font=title_font, anchor="mm")

            # Lines
            y_start = 250 if title else 180
            line_font = _load_font(40)
            number_font = _load_font(40, bold=True)

            for idx in range(reveal_count):
                y = y_start + idx * 100
                line = lines[idx]

                # Number bullet
                draw.text((100, y), f"{idx + 1}.", fill=BRAND_COLORS["accent"],
                           font=number_font, anchor="lm")

                # Line text
                draw.text((160, y), line, fill=BRAND_COLORS["white"],
                           font=line_font, anchor="lm")

            # Branding
            brand_font = _load_font(24)
            draw.text((self.WIDTH // 2, self.HEIGHT - 60), "CONTENT ENGINE",
                       fill=BRAND_COLORS["gray"], font=brand_font, anchor="mm")

            for _ in range(hold_frames):
                frames.append(frame.copy())

        # Hold final frame longer
        for _ in range(30):
            frames.append(frames[-1].copy())

        return _save_gif(frames)

    def generate_stat_cards(self, stats: list[dict], title: str = "") -> str:
        """Animated infographic showing 3-4 metric cards appearing one by one.

        stats format: [{"label": "Conversion Rate", "value": "4.7%", "change": "+123%"}, ...]
        """
        frames = []
        title = title or "KEY METRICS"
        card_count = min(len(stats), 4)
        hold_frames = 20

        card_w = 420
        card_h = 200
        gap = 40
        # Grid: 2x2
        positions = [
            ((self.WIDTH // 2 - card_w - gap // 2), 280),
            ((self.WIDTH // 2 + gap // 2), 280),
            ((self.WIDTH // 2 - card_w - gap // 2), 280 + card_h + gap),
            ((self.WIDTH // 2 + gap // 2), 280 + card_h + gap),
        ]

        for reveal in range(1, card_count + 1):
            frame = Image.new("RGB", (self.WIDTH, self.HEIGHT), BRAND_COLORS["dark_bg"])
            draw = ImageDraw.Draw(frame)

            # Title
            title_font = _load_font(40, bold=True)
            draw.text((self.WIDTH // 2, 120), title, fill=BRAND_COLORS["white"],
                       font=title_font, anchor="mm")

            # Subtitle
            sub_font = _load_font(26)
            draw.text((self.WIDTH // 2, 180), "Results after 90 days",
                       fill=BRAND_COLORS["gray"], font=sub_font, anchor="mm")

            for idx in range(reveal):
                stat = stats[idx]
                x, y = positions[idx]

                # Card background
                _draw_rounded_rect(draw, (x, y, x + card_w, y + card_h), 16, BRAND_COLORS["card_bg"])

                # Value
                val_font = _load_font(56, bold=True)
                draw.text((x + card_w // 2, y + 65), stat["value"],
                           fill=BRAND_COLORS["white"], font=val_font, anchor="mm")

                # Label
                label_font = _load_font(24)
                draw.text((x + card_w // 2, y + 120), stat["label"],
                           fill=BRAND_COLORS["gray"], font=label_font, anchor="mm")

                # Change badge
                if stat.get("change"):
                    badge_font = _load_font(22, bold=True)
                    change_color = BRAND_COLORS["success"] if stat["change"].startswith("+") else BRAND_COLORS["warning"]
                    draw.text((x + card_w // 2, y + 160), stat["change"],
                               fill=change_color, font=badge_font, anchor="mm")

            # Branding
            brand_font = _load_font(24)
            draw.text((self.WIDTH // 2, self.HEIGHT - 60), "CONTENT ENGINE",
                       fill=BRAND_COLORS["gray"], font=brand_font, anchor="mm")

            for _ in range(hold_frames):
                frames.append(frame.copy())

        # Hold final frame
        for _ in range(30):
            frames.append(frames[-1].copy())

        return _save_gif(frames)


# ─────────────────────────────────────────────────────────────
# Mode A: Screen Recording → GIF (Playwright)
# ─────────────────────────────────────────────────────────────

class ScreenRecordGifGenerator:
    """Records a website via Playwright and converts to GIF."""

    async def generate_screen_recording(
        self, url: str, actions: list[dict] = None, width: int = 1080, height: int = 1080
    ) -> str:
        """Navigate a URL, perform actions, capture screenshots, assemble GIF.

        Returns the relative web path to the generated GIF.
        """
        if not settings.SCREEN_RECORD_ENABLED:
            raise RuntimeError("Screen recording is disabled in config")

        from utils.netguard import check_public_url
        check_public_url(url)  # raises UnsafeURLError for local/private targets

        from playwright.async_api import async_playwright

        actions = actions or [
            {"type": "wait", "ms": 1000},
            {"type": "scroll", "pixels": 800, "speed": "smooth"},
            {"type": "wait", "ms": 500},
            {"type": "scroll", "pixels": 800, "speed": "smooth"},
        ]

        frames = []
        capture_interval_ms = int(1000 / settings.GIF_FPS)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.PLAYWRIGHT_HEADLESS)
            page = await browser.new_page(viewport={"width": width, "height": height})

            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(500)

            # Capture initial frame
            screenshot = await page.screenshot(type="png")
            frames.append(Image.open(io.BytesIO(screenshot)))

            # Execute actions and capture frames
            for action in actions:
                action_type = action.get("type", "wait")

                if action_type == "wait":
                    ms = action.get("ms", 1000)
                    # Capture frames during wait
                    for _ in range(max(1, ms // capture_interval_ms)):
                        screenshot = await page.screenshot(type="png")
                        frames.append(Image.open(io.BytesIO(screenshot)))
                        await page.wait_for_timeout(capture_interval_ms)

                elif action_type == "scroll":
                    pixels = action.get("pixels", 500)
                    steps = max(1, pixels // 50)
                    for _ in range(steps):
                        await page.evaluate(f"window.scrollBy(0, 50)")
                        await page.wait_for_timeout(capture_interval_ms)
                        screenshot = await page.screenshot(type="png")
                        frames.append(Image.open(io.BytesIO(screenshot)))

                elif action_type == "click":
                    selector = action.get("selector", "body")
                    try:
                        await page.click(selector, timeout=5000)
                        await page.wait_for_timeout(500)
                        screenshot = await page.screenshot(type="png")
                        frames.append(Image.open(io.BytesIO(screenshot)))
                    except Exception as e:
                        logger.warning("Click on %s failed: %s", selector, e)

                elif action_type == "hover":
                    selector = action.get("selector", "body")
                    try:
                        await page.hover(selector, timeout=5000)
                        await page.wait_for_timeout(300)
                        screenshot = await page.screenshot(type="png")
                        frames.append(Image.open(io.BytesIO(screenshot)))
                    except Exception as e:
                        logger.warning("Hover on %s failed: %s", selector, e)

            await browser.close()

        # Enforce max duration
        max_frames = settings.GIF_MAX_DURATION_SECONDS * settings.GIF_FPS
        if len(frames) > max_frames:
            # Sample frames evenly
            step = len(frames) / max_frames
            frames = [frames[int(i * step)] for i in range(max_frames)]

        # Resize to target dimensions
        frames = [f.resize((width, height), Image.Resampling.LANCZOS) for f in frames]

        logger.info("Screen recording captured: %d frames from %s", len(frames), url)
        return _save_gif(frames)


# ─────────────────────────────────────────────────────────────
# Mode C: Manual Upload → GIF Processing
# ─────────────────────────────────────────────────────────────

class UploadGifProcessor:
    """Processes uploaded video files into optimized GIFs."""

    def process_uploaded_video(
        self, file_path: str, max_duration: int = None, target_size: tuple = (1080, 1080)
    ) -> str:
        """Convert an uploaded video/GIF to an optimized GIF.

        Accepts MP4, MOV, WebM, GIF. Trims, resizes, and optimizes.
        Returns the relative web path to the processed GIF.
        """
        max_duration = max_duration or settings.GIF_MAX_DURATION_SECONDS
        src = Path(file_path)

        if not src.exists():
            raise FileNotFoundError(f"Upload not found: {file_path}")

        suffix = src.suffix.lower()

        if suffix == ".gif":
            return self._process_gif(src, max_duration, target_size)
        elif suffix in (".mp4", ".mov", ".webm"):
            return self._process_video(src, max_duration, target_size)
        else:
            raise ValueError(f"Unsupported file format: {suffix}")

    def _process_gif(self, src: Path, max_duration: int, target_size: tuple) -> str:
        """Process an existing GIF — resize and optimize."""
        frames = []
        with Image.open(src) as img:
            try:
                while True:
                    frame = img.copy().convert("RGB").resize(target_size, Image.Resampling.LANCZOS)
                    frames.append(frame)
                    img.seek(img.tell() + 1)
            except EOFError:
                pass

        # Trim to max duration
        max_frames = max_duration * settings.GIF_FPS
        if len(frames) > max_frames:
            step = len(frames) / max_frames
            frames = [frames[int(i * step)] for i in range(max_frames)]

        logger.info("Processed uploaded GIF: %d frames", len(frames))
        return _save_gif(frames)

    def _process_video(self, src: Path, max_duration: int, target_size: tuple) -> str:
        """Convert a video file to GIF using imageio."""
        reader = imageio.get_reader(str(src))
        meta = reader.get_meta_data()
        source_fps = meta.get("fps", 30)

        # Calculate frame sampling to hit target FPS
        sample_every = max(1, int(source_fps / settings.GIF_FPS))
        max_source_frames = int(max_duration * source_fps)

        frames = []
        for i, frame_data in enumerate(reader):
            if i >= max_source_frames:
                break
            if i % sample_every == 0:
                img = Image.fromarray(frame_data).resize(target_size, Image.Resampling.LANCZOS)
                frames.append(img)

        reader.close()

        if not frames:
            raise ValueError("No frames extracted from video")

        logger.info("Processed uploaded video: %d frames from %s", len(frames), src.name)
        return _save_gif(frames)


# ─────────────────────────────────────────────────────────────
# Main GIF Generator (orchestrator)
# ─────────────────────────────────────────────────────────────

class GifGenerator:
    """High-level GIF generator — picks mode, generates, and updates DB."""

    def __init__(self):
        self.programmatic = ProgrammaticGifGenerator()
        self.screen_recorder = ScreenRecordGifGenerator()
        self.upload_processor = UploadGifProcessor()

    def generate_for_post(self, db: Session, post_id: int, mode: str = "auto",
                          gif_params: dict = None) -> dict:
        """Generate a GIF for a queued post.

        mode: "auto", "programmatic", "screen_record", "upload"
        gif_params: mode-specific parameters (gif_type, data, url, actions, etc.)

        Returns dict with 'success', 'video_path' on success.
        """
        post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not post:
            return {"success": False, "error": "Post not found"}

        gif_params = gif_params or {}

        try:
            if mode == "auto":
                # Use AI planner to determine best GIF type from post content
                from content.gif_planner import plan_gif
                plan = plan_gif(post.content, post.topic or "")
                if plan and plan.get("gif_type") and plan["gif_type"] != "none":
                    planned_params = plan.get("params", {})
                    planned_params["gif_type"] = plan["gif_type"]
                    gif_path = self._generate_programmatic(plan["gif_type"], planned_params)
                else:
                    # Fallback: extract key lines from the post for a text_reveal GIF
                    lines = _extract_key_lines(post.content)
                    gif_path = self.programmatic.generate_text_reveal(
                        lines=lines,
                        title=(post.topic or "KEY INSIGHTS")[:50].upper(),
                    )
            elif mode == "programmatic":
                gif_type = gif_params.get("gif_type", "data_counter")
                gif_path = self._generate_programmatic(gif_type, gif_params)
            elif mode == "upload":
                file_path = gif_params.get("file_path")
                if not file_path:
                    return {"success": False, "error": "No file_path provided for upload mode"}
                gif_path = self.upload_processor.process_uploaded_video(file_path)
            else:
                return {"success": False, "error": f"Unknown mode: {mode}"}

            # Clean up old video if exists
            if post.video_path:
                old_file = Path("dashboard" + post.video_path)
                if old_file.exists():
                    old_file.unlink()

            # Update post
            post.video_path = gif_path
            post.has_video = True
            post.media_type = "gif"
            post.video_source = mode
            post.has_image = False  # GIF replaces image
            db.commit()

            logger.info("GIF saved for post #%s: %s (mode=%s)", post_id, gif_path, mode)
            return {"success": True, "video_path": gif_path}

        except Exception as e:
            logger.error("GIF generation failed for post #%s: %s", post_id, e)
            return {"success": False, "error": str(e)}

    async def generate_screen_record_for_post(
        self, db: Session, post_id: int, url: str, actions: list[dict] = None
    ) -> dict:
        """Generate a screen recording GIF for a post (async)."""
        post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not post:
            return {"success": False, "error": "Post not found"}

        try:
            gif_path = await self.screen_recorder.generate_screen_recording(url, actions)

            if post.video_path:
                old_file = Path("dashboard" + post.video_path)
                if old_file.exists():
                    old_file.unlink()

            post.video_path = gif_path
            post.has_video = True
            post.media_type = "gif"
            post.video_source = "screen_record"
            post.has_image = False
            db.commit()

            logger.info("Screen recording GIF saved for post #%s: %s", post_id, gif_path)
            return {"success": True, "video_path": gif_path}

        except Exception as e:
            logger.error("Screen recording failed for post #%s: %s", post_id, e)
            return {"success": False, "error": str(e)}

    def _generate_programmatic(self, gif_type: str, params: dict) -> str:
        """Route to the correct programmatic GIF generator."""
        if gif_type == "data_counter":
            return self.programmatic.generate_data_counter(
                metric=params.get("metric", "Growth"),
                from_val=params.get("from_val", 0),
                to_val=params.get("to_val", 100),
                unit=params.get("unit", "%"),
                title=params.get("title", ""),
            )
        elif gif_type == "before_after":
            return self.programmatic.generate_before_after(
                before_text=params.get("before_text", "Before"),
                after_text=params.get("after_text", "After"),
                metric_label=params.get("metric_label", ""),
                title=params.get("title", ""),
            )
        elif gif_type == "text_reveal":
            return self.programmatic.generate_text_reveal(
                lines=params.get("lines", ["Line 1", "Line 2", "Line 3"]),
                title=params.get("title", ""),
            )
        elif gif_type == "stat_cards":
            return self.programmatic.generate_stat_cards(
                stats=params.get("stats", []),
                title=params.get("title", ""),
            )
        else:
            raise ValueError(f"Unknown programmatic GIF type: {gif_type}")

    def remove_video(self, db: Session, post_id: int) -> bool:
        """Remove the video/GIF from a post."""
        post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not post:
            return False

        if post.video_path:
            old_file = Path("dashboard" + post.video_path)
            if old_file.exists():
                old_file.unlink()

        post.video_path = None
        post.video_prompt = None
        post.has_video = False
        post.media_type = "image" if post.has_image else "none"
        post.video_duration = None
        post.video_source = None
        db.commit()
        return True
