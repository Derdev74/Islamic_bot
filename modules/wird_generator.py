"""
modules/wird_generator.py
=========================
Pipeline 3 — Daily Quran Page Story.
Posts 1 Mushaf page per day, consecutively 1→604→1.
"""

import json
import logging
import os
import random
from pathlib import Path

import requests
from PIL import Image

from config.settings import (
    ACCOUNT_HANDLE,
    CAPTIONS_JSON,
    OUTPUT_DIR,
    OVERLAYS_DIR,
    QURAN_PAGES_DIR,
)
from modules import database
from modules.subtitle_engine import build_wird_story
from modules.video_editor import cleanup_output_folder, image_to_story_video

logger = logging.getLogger(__name__)

QURAN_CDN_BASE = "https://cdn.islamic.network/quran/images/high-resolution"


def _get_page_image(page: int) -> Image.Image:
    """
    Return the Mushaf page image.
    Uses local cache first, downloads from CDN if not present.
    """
    local_path = os.path.join(QURAN_PAGES_DIR, f"{page:03d}.png")
    if not os.path.exists(local_path):
        url = f"{QURAN_CDN_BASE}/{page}.png"
        logger.info("Downloading page %d from CDN: %s", page, url)
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            os.makedirs(QURAN_PAGES_DIR, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(r.content)
        except requests.RequestException as e:
            logger.error("Failed to download page %d: %s", page, e)
            raise

    return Image.open(local_path)


def _get_overlay() -> Image.Image | None:
    overlay_dir = Path(OVERLAYS_DIR)
    overlays = list(overlay_dir.glob("*.png"))
    if not overlays:
        return None
    return Image.open(random.choice(overlays))


def _build_caption(page: int) -> str:
    try:
        with open(CAPTIONS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        templates = data.get("wird_captions", [])
        if templates:
            tpl = random.choice(templates)
            return tpl.format(page=page)
    except Exception:
        pass
    return f"📖 وردك اليومي — الصفحة {page}\n#القرآن_الكريم #wird"


def run_wird_pipeline() -> bool:
    """Build and post the daily Wird story. Returns True on success."""
    cleanup_output_folder()
    logger.info("Starting Wird pipeline")

    page = database.get_current_wird_page()
    logger.info("Posting Quran page %d/604", page)

    try:
        page_img = _get_page_image(page)
    except Exception as e:
        logger.error("Cannot get page image for page %d: %s", page, e)
        return False

    overlay_img = _get_overlay()
    story_img = build_wird_story(
        page_image=page_img,
        page_number=page,
        watermark=ACCOUNT_HANDLE,
        overlay_img=overlay_img,
    )

    output_path = os.path.join(OUTPUT_DIR, f"wird_page_{page:03d}.mp4")
    image_to_story_video(story_img, duration=12.0, output_path=output_path)

    caption = _build_caption(page)
    post_id = database.log_post("wird", f"page:{page}", status="pending")

    from modules.instagram_api import post_story_video
    result = post_story_video(output_path, post_id)

    # Always advance page, even on failure, to avoid being stuck
    database.advance_wird_page()
    cleanup_output_folder()

    if result:
        logger.info("Wird page %d posted successfully.", page)
        return True
    else:
        logger.warning("Wird page %d failed to post.", page)
        return False
