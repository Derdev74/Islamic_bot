"""
modules/adkar_generator.py
==========================
Builds Adkar Sabah / Masae story images (Pipeline 1 & 2).

Posting logic:
  - If you place pre-made adkar images in assets/adkar_sabah/ or assets/adkar_masae/,
    the bot posts those directly (your custom photos take priority).
  - Otherwise, the bot auto-generates a 1080×1920 image with the dhikr text
    overlaid on a background from assets/backgrounds/.

Timing:
  - Adkar Sabah: Fajr + 5 min
  - Adkar Masae: Asr + 5 min  ← (recited from Asr until Maghrib)
"""

import json
import logging
import os
import random
from pathlib import Path

from PIL import Image

from config.settings import (
    ACCOUNT_HANDLE,
    ADKAR_MASAE_JSON,
    ADKAR_SABAH_JSON,
    ASSETS_DIR,
    BACKGROUNDS_DIR,
    CAPTIONS_JSON,
    OUTPUT_DIR,
)
from modules import database
from modules.video_editor import cleanup_output_folder

logger = logging.getLogger(__name__)

# Folders where you can drop your own pre-made adkar photos
CUSTOM_ADKAR_DIRS = {
    "sabah": os.path.join(ASSETS_DIR, "adkar_sabah"),
    "masae": os.path.join(ASSETS_DIR, "adkar_masae"),
}


def _load_adkar(json_path: str) -> list[dict]:
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def _list_custom_photos(adkar_type: str) -> list[Path]:
    """Return sorted list of user-provided adkar images (JPG/PNG)."""
    folder = Path(CUSTOM_ADKAR_DIRS[adkar_type])
    if not folder.exists():
        return []
    photos = sorted(
        list(folder.glob("*.jpg")) + list(folder.glob("*.jpeg")) + list(folder.glob("*.png"))
    )
    return photos


def _load_background() -> Image.Image:
    """Pick a random background image from assets/backgrounds/."""
    bg_dir = Path(BACKGROUNDS_DIR)
    images = list(bg_dir.glob("*.jpg")) + list(bg_dir.glob("*.png"))
    if images:
        img = Image.open(random.choice(images)).resize((1080, 1920), Image.LANCZOS)
        return img
    return Image.new("RGB", (1080, 1920), (18, 18, 35))


def _build_generated_image(dhikr: dict, adkar_type: str) -> Image.Image:
    """
    Auto-generate a 1080×1920 adkar story image with the dhikr text
    rendered on a background. Used when no custom photos are provided.
    """
    from PIL import Image as PILImage
    from modules.subtitle_engine import (
        GOLD_COLOR, STORY_SIZE, WHITE_COLOR, render_arabic_text, render_banner,
    )

    size = STORY_SIZE
    bg = _load_background().convert("RGBA")

    # Semi-transparent dark overlay for text readability
    overlay = PILImage.new("RGBA", size, (0, 0, 0, 155))
    canvas = PILImage.alpha_composite(bg, overlay)

    # Top header banner
    header = "أذكار الصباح" if adkar_type == "sabah" else "أذكار المساء"
    top_banner = render_banner(header, canvas_size=size, font_size=62, position="top", bg_alpha=190)
    canvas = PILImage.alpha_composite(canvas, top_banner)

    # Decorative separator line below header (drawn via a thin banner with no text)
    sep = PILImage.new("RGBA", size, (0, 0, 0, 0))
    from PIL import ImageDraw
    sep_draw = ImageDraw.Draw(sep)
    sep_draw.rectangle([(80, 185), (1000, 188)], fill=(212, 175, 55, 180))  # gold line
    canvas = PILImage.alpha_composite(canvas, sep)

    # Main dhikr text — centered
    arabic_text = dhikr.get("arabic", "")
    text_layer = render_arabic_text(
        arabic_text,
        canvas_size=size,
        font_size=62,
        color=WHITE_COLOR,
        bold=False,
        shadow=True,
        y_center_offset=-50,
        max_width_ratio=0.88,
    )
    canvas = PILImage.alpha_composite(canvas, text_layer)

    # Source + count
    source = dhikr.get("source", "")
    count = dhikr.get("count", 1)
    count_label = f"× {count}" if count > 1 else ""
    source_str = f"{source}  {count_label}".strip()
    if source_str:
        source_layer = render_arabic_text(
            source_str,
            canvas_size=size,
            font_size=40,
            color=GOLD_COLOR,
            bold=True,
            shadow=True,
            y_center_offset=240,
        )
        canvas = PILImage.alpha_composite(canvas, source_layer)

    # Watermark
    wm_layer = render_arabic_text(
        ACCOUNT_HANDLE,
        canvas_size=size,
        font_size=32,
        color=(200, 200, 200, 120),
        shadow=False,
        y_center_offset=int(size[1] * 0.43),
    )
    canvas = PILImage.alpha_composite(canvas, wm_layer)

    return canvas.convert("RGB")


def _load_caption(adkar_type: str) -> str:
    try:
        with open(CAPTIONS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        templates = data.get(f"adkar_{adkar_type}_captions", [])
        if templates:
            return random.choice(templates)
    except Exception:
        pass
    return "أذكار الصباح 🌅" if adkar_type == "sabah" else "أذكار المساء 🌙"


def run_adkar_pipeline(adkar_type: str) -> bool:
    """
    adkar_type: 'sabah' | 'masae'
    Posts as an Instagram Story image (not video).
    Returns True on success.
    """
    cleanup_output_folder()
    logger.info("Starting Adkar %s pipeline", adkar_type)

    json_path = ADKAR_SABAH_JSON if adkar_type == "sabah" else ADKAR_MASAE_JSON
    adkar_list = _load_adkar(json_path)
    if not adkar_list:
        logger.error("Adkar list is empty: %s", json_path)
        return False

    idx = database.get_adkar_index(adkar_type)
    dhikr = adkar_list[idx % len(adkar_list)]
    logger.info("Adkar %s index %d (id=%s)", adkar_type, idx, dhikr.get("id"))

    output_path = os.path.join(OUTPUT_DIR, f"adkar_{adkar_type}.jpg")

    # ── Prefer user-provided custom photos ────────────────────────────────────
    custom_photos = _list_custom_photos(adkar_type)
    if custom_photos:
        # Rotate through custom photos in the same order as adkar rotation
        photo_path = custom_photos[idx % len(custom_photos)]
        logger.info("Using custom adkar photo: %s", photo_path.name)
        # Resize to story dimensions and save to output
        img = Image.open(photo_path).convert("RGB")
        img = img.resize((1080, 1920), Image.LANCZOS)
        img.save(output_path, "JPEG", quality=95)
    else:
        # Auto-generate image
        logger.info("No custom photos found — auto-generating adkar image")
        img = _build_generated_image(dhikr, adkar_type)
        img.save(output_path, "JPEG", quality=95)

    # Log to DB
    content_ref = f"{adkar_type}:{dhikr.get('id', idx)}"
    post_db_id = database.log_post(f"adkar_{adkar_type}", content_ref, status="pending")

    # Post as Story image
    from modules.instagram_api import post_story_image
    caption = _load_caption(adkar_type)
    result = post_story_image(output_path, post_db_id, caption=caption)

    # Always advance index to avoid repeating the same dhikr
    database.advance_adkar_index(adkar_type, len(adkar_list))

    cleanup_output_folder()
    return result is not None
