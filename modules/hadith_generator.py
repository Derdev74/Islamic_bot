"""
modules/hadith_generator.py
============================
Pipeline 5 — Daily Hadith feed image post.
Fetches from HadeethEnc API, renders 1080×1080 image card,
sends via Telegram for approval before posting.
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
    BACKGROUNDS_DIR,
    CAPTIONS_JSON,
    OUTPUT_DIR,
)
from modules import database
from modules.subtitle_engine import build_hadith_image
from modules.video_editor import cleanup_output_folder

logger = logging.getLogger(__name__)

HADEETHENC_BASE = "https://hadeethenc.com/api/v1"


def _fetch_hadith(hadith_id: int) -> dict | None:
    """
    Fetch a hadith from HadeethEnc API.
    Returns dict with 'arabic', 'attribution' keys, or None on failure.
    """
    url = f"{HADEETHENC_BASE}/hadeeths/one/"
    params = {"id": hadith_id, "language": "ar"}
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return {
            "id": hadith_id,
            "arabic": data.get("hadeeth", ""),
            "attribution": data.get("attribution", ""),
            "grade": data.get("grade", ""),
        }
    except requests.RequestException as e:
        logger.error("HadeethEnc API error (id=%d): %s", hadith_id, e)
        return None


def _get_background() -> Image.Image:
    bg_dir = Path(BACKGROUNDS_DIR)
    images = list(bg_dir.glob("*.jpg")) + list(bg_dir.glob("*.png"))
    if images:
        img = Image.open(random.choice(images)).resize((1080, 1080), Image.LANCZOS)
        return img
    return Image.new("RGB", (1080, 1080), (30, 25, 20))


def _build_caption(hadith: dict) -> str:
    try:
        with open(CAPTIONS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        templates = data.get("hadith_captions", [])
        ht_sets = data.get("hashtag_sets", ["#حديث"])
        if templates:
            tpl = random.choice(templates)
            hashtags = random.choice(ht_sets)
            return tpl.format(hashtags=hashtags)
    except Exception:
        pass
    return "📜 حديث شريف\n#حديث #سنة_النبي"


def run_hadith_pipeline() -> bool:
    """Build hadith image, get Telegram approval, then post. Returns True on success."""
    cleanup_output_folder()
    logger.info("Starting Hadith pipeline")

    hadith_id = database.get_last_hadith_id() + 1
    # HadeethEnc IDs are not perfectly sequential; try a few if one fails
    hadith = None
    for candidate_id in range(hadith_id, hadith_id + 5):
        hadith = _fetch_hadith(candidate_id)
        if hadith and hadith["arabic"]:
            break

    if not hadith or not hadith["arabic"]:
        logger.error("Could not fetch valid hadith starting from id %d", hadith_id)
        return False

    # Build image
    bg = _get_background()
    source_text = hadith["attribution"]
    if hadith.get("grade"):
        source_text += f" — {hadith['grade']}"

    img = build_hadith_image(
        hadith_text=hadith["arabic"],
        source_text=source_text,
        watermark=ACCOUNT_HANDLE,
        background=bg,
    )

    output_path = os.path.join(OUTPUT_DIR, f"hadith_{hadith['id']}.jpg")
    img.save(output_path, "JPEG", quality=95)

    caption = _build_caption(hadith)
    post_db_id = database.log_post("hadith", f"hadith_id:{hadith['id']}", status="pending_review")

    # ── Telegram approval gate (mandatory per Claude.md) ──────────────────────
    from modules.telegram_review import send_for_review
    post_token = f"hadith_{hadith['id']}"
    approved = send_for_review(
        media_path=output_path,
        caption=caption,
        post_token=post_token,
        media_type="photo",
        timeout_hours=6,
    )

    if not approved:
        database.update_post_status(post_db_id, "rejected", error_message="Rejected via Telegram")
        cleanup_output_folder()
        return False

    # Post
    from modules.instagram_api import post_image
    result = post_image(output_path, caption, post_db_id)

    database.advance_hadith_id()
    cleanup_output_folder()
    return result is not None
