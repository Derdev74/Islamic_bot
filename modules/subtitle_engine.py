"""
modules/subtitle_engine.py
==========================
The "Heart" of the bot — all RTL Arabic text rendering with tashkeel support.
Uses arabic_reshaper + python-bidi + Pillow (Amiri font).
"""

import logging
import textwrap
from pathlib import Path
from typing import Optional

import arabic_reshaper
import numpy as np
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from moviepy.editor import CompositeVideoClip, ImageClip, VideoClip

from config.settings import FONT_AMIRI_BOLD, FONT_AMIRI_REGULAR, FONT_SCHEHERAZADE

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
REEL_SIZE   = (1080, 1920)
POST_SIZE   = (1080, 1080)
STORY_SIZE  = (1080, 1920)
GOLD_COLOR  = (255, 215, 0, 255)
WHITE_COLOR = (255, 255, 255, 255)
SHADOW_COLOR = (0, 0, 0, 180)


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        logger.warning("Font not found: %s — falling back to Scheherazade", path)
        try:
            return ImageFont.truetype(FONT_SCHEHERAZADE, size=size)
        except OSError:
            logger.error("No Arabic font found. Text may render incorrectly.")
            return ImageFont.load_default()


def prepare_arabic(text: str) -> str:
    """
    Reshape Arabic letters and apply BiDi algorithm.
    MUST be called on every Arabic string before rendering.
    """
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def _wrap_arabic(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap Arabic text so each line fits within max_width pixels."""
    words = text.split()
    lines = []
    current_line: list[str] = []

    for word in words:
        test_line = " ".join(current_line + [word])
        # Measure using a temp draw
        tmp = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(tmp)
        bbox = draw.textbbox((0, 0), test_line, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))
    return lines


def render_arabic_text(
    text: str,
    canvas_size: tuple[int, int] = REEL_SIZE,
    font_size: int = 72,
    color: tuple = WHITE_COLOR,
    shadow: bool = True,
    bold: bool = False,
    y_center_offset: int = 0,
    max_width_ratio: float = 0.85,
) -> Image.Image:
    """
    Render Arabic text (with tashkeel) onto a transparent RGBA canvas.
    Returns a PIL Image ready to be composited.
    """
    font_path = FONT_AMIRI_BOLD if bold else FONT_AMIRI_REGULAR
    font = _load_font(font_path, font_size)

    img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    max_width = int(canvas_size[0] * max_width_ratio)
    display_text = prepare_arabic(text)
    lines = _wrap_arabic(display_text, font, max_width)

    # Measure total block height
    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])

    line_spacing = int(font_size * 0.35)
    total_height = sum(line_heights) + line_spacing * (len(lines) - 1)
    cx = canvas_size[0] // 2
    cy = canvas_size[1] // 2 + y_center_offset
    start_y = cy - total_height // 2

    for i, line in enumerate(lines):
        y = start_y + sum(line_heights[:i]) + line_spacing * i
        if shadow:
            draw.text((cx + 2, y + 2), line, font=font, fill=SHADOW_COLOR, anchor="mt")
        draw.text((cx, y), line, font=font, fill=color, anchor="mt")

    return img


def render_karaoke_frame(
    ayah_text: str,
    highlight_word: Optional[str],
    canvas_size: tuple[int, int] = REEL_SIZE,
    font_size: int = 68,
    y_center_offset: int = 200,
) -> Image.Image:
    """
    Render a full ayah with one word highlighted in gold (karaoke style).
    highlight_word: the exact word string to highlight (must appear in ayah_text).
    """
    font_path = FONT_AMIRI_BOLD
    font = _load_font(font_path, font_size)
    img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    max_width = int(canvas_size[0] * 0.88)
    display_text = prepare_arabic(ayah_text)
    lines = _wrap_arabic(display_text, font, max_width)

    line_spacing = int(font_size * 0.4)
    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + line_spacing * max(0, len(lines) - 1)
    cx = canvas_size[0] // 2
    cy = canvas_size[1] // 2 + y_center_offset
    start_y = cy - total_height // 2

    highlight_prepared = prepare_arabic(highlight_word) if highlight_word else None

    for i, line in enumerate(lines):
        y = start_y + sum(line_heights[:i]) + line_spacing * i

        # If this line contains the highlighted word, do per-word coloring
        if highlight_prepared and highlight_prepared in line:
            words_in_line = line.split()
            # Measure full line width to calculate starting x
            bbox = draw.textbbox((0, 0), line, font=font)
            line_w = bbox[2] - bbox[0]
            x = cx - line_w // 2

            for w in words_in_line:
                w_bbox = draw.textbbox((0, 0), w + " ", font=font)
                w_width = w_bbox[2] - w_bbox[0]
                color = GOLD_COLOR if w == highlight_prepared else WHITE_COLOR
                # Shadow
                draw.text((x + 2, y + 2), w, font=font, fill=SHADOW_COLOR, anchor="lt")
                draw.text((x, y), w, font=font, fill=color, anchor="lt")
                x += w_width
        else:
            draw.text((cx + 2, y + 2), line, font=font, fill=SHADOW_COLOR, anchor="mt")
            draw.text((cx, y), line, font=font, fill=WHITE_COLOR, anchor="mt")

    return img


def render_banner(
    text: str,
    canvas_size: tuple[int, int] = REEL_SIZE,
    font_size: int = 48,
    position: str = "top",
    bg_alpha: int = 160,
) -> Image.Image:
    """
    Render a translucent banner (top or bottom) with Arabic text.
    position: 'top' | 'bottom'
    """
    font = _load_font(FONT_AMIRI_BOLD, font_size)
    banner_h = int(font_size * 2.5)
    img = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if position == "top":
        banner_rect = [(0, 0), (canvas_size[0], banner_h)]
        text_y = banner_h // 2
    else:
        banner_rect = [(0, canvas_size[1] - banner_h), (canvas_size[0], canvas_size[1])]
        text_y = canvas_size[1] - banner_h // 2

    draw.rectangle(banner_rect, fill=(0, 0, 0, bg_alpha))
    display_text = prepare_arabic(text)
    draw.text((canvas_size[0] // 2, text_y), display_text, font=font,
              fill=WHITE_COLOR, anchor="mm")
    return img


def composite_subtitles_onto_video(
    video_clip: VideoClip,
    subtitle_schedule: list[dict],
) -> CompositeVideoClip:
    """
    Overlay subtitle frames onto a video clip.

    subtitle_schedule: list of dicts with keys:
        - start_ms  (int)
        - end_ms    (int)
        - text      (str) — full ayah Arabic text
        - highlight_word (str | None)
    """
    subtitle_clips = []
    for sub in subtitle_schedule:
        frame_img = render_karaoke_frame(
            ayah_text=sub["text"],
            highlight_word=sub.get("highlight_word"),
        )
        arr = np.array(frame_img)
        duration = (sub["end_ms"] - sub["start_ms"]) / 1000.0
        if duration <= 0:
            continue
        clip = (
            ImageClip(arr, ismask=False)
            .set_start(sub["start_ms"] / 1000.0)
            .set_duration(duration)
            .set_position("center")
        )
        subtitle_clips.append(clip)

    return CompositeVideoClip([video_clip] + subtitle_clips)


def build_hadith_image(
    hadith_text: str,
    source_text: str,
    watermark: str,
    background: Image.Image,
    size: tuple[int, int] = POST_SIZE,
) -> Image.Image:
    """
    Compose a finished hadith image card (1080×1080).
    background: a PIL Image already resized to `size`.
    """
    canvas = background.copy().convert("RGBA")

    # Dark overlay for readability
    overlay = Image.new("RGBA", size, (0, 0, 0, 120))
    canvas = Image.alpha_composite(canvas, overlay)

    # Hadith text — large, centered
    hadith_layer = render_arabic_text(
        hadith_text,
        canvas_size=size,
        font_size=58,
        bold=False,
        y_center_offset=-60,
    )
    canvas = Image.alpha_composite(canvas, hadith_layer)

    # Source line — smaller, below center
    source_layer = render_arabic_text(
        source_text,
        canvas_size=size,
        font_size=40,
        bold=True,
        color=GOLD_COLOR,
        shadow=True,
        y_center_offset=220,
    )
    canvas = Image.alpha_composite(canvas, source_layer)

    # Watermark — bottom right, small and subtle
    wm_layer = render_arabic_text(
        watermark,
        canvas_size=size,
        font_size=30,
        color=(200, 200, 200, 150),
        shadow=False,
        y_center_offset=int(size[1] * 0.42),
    )
    canvas = Image.alpha_composite(canvas, wm_layer)

    return canvas.convert("RGB")


def build_wird_story(
    page_image: Image.Image,
    page_number: int,
    watermark: str,
    overlay_img: Optional[Image.Image] = None,
    size: tuple[int, int] = STORY_SIZE,
) -> Image.Image:
    """
    Compose the daily Wird story (1080×1920).
    The Mushaf page is centered; top/bottom banners added.
    """
    canvas = Image.new("RGBA", size, (20, 20, 20, 255))

    # Center the page image
    page_ratio = min(size[0] * 0.92 / page_image.width, size[1] * 0.78 / page_image.height)
    new_w = int(page_image.width * page_ratio)
    new_h = int(page_image.height * page_ratio)
    page_resized = page_image.resize((new_w, new_h), Image.LANCZOS)

    x_off = (size[0] - new_w) // 2
    y_off = (size[1] - new_h) // 2 + 30
    canvas.paste(page_resized.convert("RGBA"), (x_off, y_off))

    # Optional decorative overlay
    if overlay_img:
        overlay_resized = overlay_img.resize(size, Image.LANCZOS).convert("RGBA")
        canvas = Image.alpha_composite(canvas, overlay_resized)

    # Top banner
    page_arabic = f"الصفحة {page_number} — وردك اليومي"
    top_banner = render_banner(page_arabic, canvas_size=size, font_size=52, position="top")
    canvas = Image.alpha_composite(canvas, top_banner)

    # Bottom watermark banner
    bottom_banner = render_banner(watermark, canvas_size=size, font_size=36, position="bottom", bg_alpha=100)
    canvas = Image.alpha_composite(canvas, bottom_banner)

    return canvas.convert("RGB")
