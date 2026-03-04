"""
modules/recitation_pipeline.py
==============================
Pipeline 4 — Flagship Quran Recitation Reel builder.
Audio from mp3quran.net → word timestamps from Quran.com API v4
→ karaoke subtitles → Reel → Telegram review → Instagram.
"""

import json
import logging
import os
import random
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np
import requests
from moviepy.editor import AudioFileClip, CompositeVideoClip, ImageClip
from PIL import Image

from config.settings import (
    ACCOUNT_HANDLE,
    CAPTIONS_JSON,
    OUTPUT_DIR,
    RECITERS_JSON,
    REEL_MAX_DURATION_SEC,
    REEL_MIN_DURATION_SEC,
)
from modules import database
from modules.audio_fetcher import fetch_and_trim_segment, get_audio_duration
from modules.subtitle_engine import (
    REEL_SIZE,
    composite_subtitles_onto_video,
    render_banner,
    render_karaoke_frame,
)
from modules.video_editor import (
    cleanup_output_folder,
    list_template_files,
    load_template,
    loop_to_duration,
    validate_video,
)

logger = logging.getLogger(__name__)

QURAN_COM_BASE = "https://api.quran.com/api/v4"

# Surah ayah counts (1-indexed, approximate for iteration logic)
SURAH_AYAH_COUNT = [
    7,286,200,176,120,165,206,75,129,109,123,111,43,52,99,128,111,110,98,135,
    112,78,118,64,77,227,93,88,69,60,34,30,73,54,45,83,182,88,75,85,54,53,89,
    59,37,35,38,29,18,45,60,49,62,55,78,96,29,22,24,13,14,11,11,18,12,12,30,
    52,52,44,28,28,20,56,40,31,50,45,42,29,19,36,25,22,17,19,26,30,20,15,21,
    11,8,8,19,5,8,8,11,11,8,3,9,5,4,7,3,6,3,5,4,5,6,
]


def _load_reciters() -> list[dict]:
    with open(RECITERS_JSON, encoding="utf-8") as f:
        return json.load(f)


def _pick_reciter(reciters: list[dict]) -> dict:
    """Weighted random selection."""
    weights = [r.get("weight", 1) for r in reciters]
    return random.choices(reciters, weights=weights, k=1)[0]


def _get_ayah_count(surah: int) -> int:
    if 1 <= surah <= len(SURAH_AYAH_COUNT):
        return SURAH_AYAH_COUNT[surah - 1]
    return 10


def _get_surah_name_arabic(surah: int) -> str:
    """Fetch surah name in Arabic from Quran.com API."""
    try:
        resp = requests.get(
            f"{QURAN_COM_BASE}/chapters/{surah}",
            params={"language": "ar"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["chapter"]["name_arabic"]
    except Exception:
        return f"سورة {surah}"


def _fetch_word_timestamps(recitation_id: int, surah: int) -> list[dict]:
    """
    Fetch word-level timestamps from Quran.com API v4.
    Returns list of {position, text_uthmani, timestamp_from, timestamp_to}
    """
    url = f"{QURAN_COM_BASE}/recitations/{recitation_id}/by_chapter/{surah}"
    try:
        resp = requests.get(url, params={"per_page": 500}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        words = []
        for entry in data.get("audio_files", []):
            for segment in entry.get("segments", []):
                # segment format: [word_position, char_start, char_end, ts_from, ts_to]
                if len(segment) >= 5:
                    words.append({
                        "position": segment[0],
                        "timestamp_from": segment[3],
                        "timestamp_to": segment[4],
                    })
        return words
    except requests.RequestException as e:
        logger.warning("Could not fetch word timestamps: %s", e)
        return []


def _build_subtitle_schedule(
    ayah_words: list[dict],
    ayah_texts: dict[int, str],
    start_ms_offset: int = 0,
) -> list[dict]:
    """
    Build the subtitle schedule from word timestamps.
    Each entry: {start_ms, end_ms, text (full ayah), highlight_word}
    """
    schedule = []
    # Group words by ayah (position // 1000 in Quran.com word positioning)
    for w in ayah_words:
        schedule.append({
            "start_ms": w["timestamp_from"] + start_ms_offset,
            "end_ms": w["timestamp_to"] + start_ms_offset,
            "text": ayah_texts.get(w.get("ayah_num", 1), ""),
            "highlight_word": w.get("text_uthmani", ""),
        })
    return schedule


def _fetch_ayah_texts(surah: int, ayah_start: int, ayah_end: int) -> dict[int, str]:
    """Fetch Arabic ayah texts from alquran.cloud."""
    texts = {}
    try:
        for ayah_num in range(ayah_start, ayah_end + 1):
            resp = requests.get(
                f"https://api.alquran.cloud/v1/ayah/{surah}:{ayah_num}/ar",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            texts[ayah_num] = data["data"]["text"]
    except Exception as e:
        logger.warning("Could not fetch ayah texts: %s", e)
    return texts


def _determine_ayah_range(reciter: dict, surah: int) -> tuple[int, int, float, float]:
    """
    Determine which ayahs to include for a 60–90 second segment.
    Returns (ayah_start, ayah_end, start_sec, end_sec).
    Uses recitation_progress DB to continue from last position.
    """
    progress = database.get_recitation_progress(reciter["id"])
    last_surah = progress["last_surah"]
    last_ayah = progress["last_ayah"]

    if last_surah != surah:
        ayah_start = 1
    else:
        ayah_start = last_ayah + 1

    total_ayahs = _get_ayah_count(surah)
    if ayah_start > total_ayahs:
        # Move to next surah
        surah = (surah % 114) + 1
        ayah_start = 1
        total_ayahs = _get_ayah_count(surah)

    # Estimate: average ~5 seconds per ayah (rough heuristic)
    target_sec = random.randint(REEL_MIN_DURATION_SEC, REEL_MAX_DURATION_SEC)
    estimated_ayahs = max(1, target_sec // 5)
    ayah_end = min(ayah_start + estimated_ayahs - 1, total_ayahs)

    start_sec = 0.0
    end_sec = float(target_sec)

    return surah, ayah_start, ayah_end, start_sec, end_sec


def _build_reel_video(
    template_filename: str,
    audio_path: str,
    subtitle_schedule: list[dict],
    top_text: str,
    output_path: str,
) -> str:
    """Assemble the reel and write to output_path."""
    from moviepy.editor import AudioFileClip, CompositeVideoClip, ImageClip

    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration

    template = load_template(template_filename)
    template = loop_to_duration(template, duration).without_audio()

    layers = [template]

    # Top banner
    top_banner_img = render_banner(top_text, canvas_size=REEL_SIZE, font_size=46, position="top")
    top_arr = np.array(top_banner_img.convert("RGBA"))
    top_clip = ImageClip(top_arr, ismask=False).set_duration(duration).set_position(("center", "top"))
    layers.append(top_clip)

    # Bottom watermark
    from modules.subtitle_engine import render_arabic_text, WHITE_COLOR
    wm_img = render_arabic_text(
        ACCOUNT_HANDLE,
        canvas_size=REEL_SIZE,
        font_size=34,
        color=(200, 200, 200, 160),
        shadow=False,
        y_center_offset=int(REEL_SIZE[1] * 0.44),
    )
    wm_arr = np.array(wm_img.convert("RGBA"))
    wm_clip = ImageClip(wm_arr, ismask=False).set_duration(duration).set_position("center")
    layers.append(wm_clip)

    # Subtitle clips
    for sub in subtitle_schedule:
        if not sub.get("text"):
            continue
        frame_img = render_karaoke_frame(
            ayah_text=sub["text"],
            highlight_word=sub.get("highlight_word"),
        )
        arr = np.array(frame_img.convert("RGBA"))
        sub_duration = max(0.05, (sub["end_ms"] - sub["start_ms"]) / 1000.0)
        clip = (
            ImageClip(arr, ismask=False)
            .set_start(sub["start_ms"] / 1000.0)
            .set_duration(sub_duration)
            .set_position("center")
        )
        layers.append(clip)

    composite = CompositeVideoClip(layers, size=REEL_SIZE)
    composite = composite.set_audio(audio_clip)

    composite.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        ffmpeg_params=["-crf", "23", "-preset", "fast", "-pix_fmt", "yuv420p"],
        logger=None,
    )
    return output_path


def _build_caption(surah_name: str, ayah_start: int, ayah_end: int, reciter: dict) -> str:
    try:
        with open(CAPTIONS_JSON, encoding="utf-8") as f:
            data = json.load(f)
        templates = data.get("reel_captions", [])
        ht_sets = data.get("hashtag_sets", ["#QuranRecitation"])
        if templates:
            tpl = random.choice(templates)
            hashtags = random.choice(ht_sets)
            return tpl.format(
                surah_name=surah_name,
                ayah_start=ayah_start,
                ayah_end=ayah_end,
                reciter_name=reciter.get("name_ar", reciter["id"]),
                hashtags=hashtags,
            )
    except Exception:
        pass
    return f"سورة {surah_name} — بصوت {reciter.get('name_ar', reciter['id'])}\n#القرآن_الكريم"


def run_recitation_pipeline() -> bool:
    """Full reel pipeline. Returns True on success."""
    cleanup_output_folder()
    logger.info("Starting Recitation Reel pipeline")

    reciters = _load_reciters()
    if not reciters:
        logger.error("No reciters configured in reciters.json")
        return False

    reciter = _pick_reciter(reciters)
    logger.info("Selected reciter: %s", reciter.get("name_en", reciter["id"]))

    # Determine segment
    progress = database.get_recitation_progress(reciter["id"])
    surah = progress["last_surah"] if progress["last_surah"] >= 1 else 1
    surah, ayah_start, ayah_end, start_sec, end_sec = _determine_ayah_range(reciter, surah)

    logger.info("Segment: Surah %d, Ayahs %d–%d, %.0fs–%.0fs",
                surah, ayah_start, ayah_end, start_sec, end_sec)

    # Fetch audio
    audio_path = fetch_and_trim_segment(reciter, surah, start_sec, end_sec)
    if not audio_path:
        logger.error("Audio fetch failed")
        return False

    actual_duration = get_audio_duration(audio_path)
    if actual_duration < 5:
        logger.error("Audio too short: %.1fs", actual_duration)
        return False

    # Fetch timestamps — Quran.com API first, ayah-timed fallback if unavailable
    subtitle_schedule: list[dict] = []
    ayah_texts = _fetch_ayah_texts(surah, ayah_start, ayah_end)

    if reciter.get("quran_com_recitation_id"):
        words = _fetch_word_timestamps(reciter["quran_com_recitation_id"], surah)
        if words:
            start_ms = int(start_sec * 1000)
            end_ms = int(end_sec * 1000)
            filtered = [w for w in words if start_ms <= w["timestamp_from"] <= end_ms]
            for w in filtered:
                w["timestamp_from"] -= start_ms
                w["timestamp_to"] -= start_ms
                position = w.get("position", 0)
                estimated_ayah = ayah_start + (position // 10)
                w["ayah_num"] = min(estimated_ayah, ayah_end)
            subtitle_schedule = _build_subtitle_schedule(filtered, ayah_texts)
        else:
            logger.info("No word timestamps from Quran.com — using ayah-timed fallback")
            subtitle_schedule = _ayah_timed_fallback(
                ayah_texts, ayah_start, ayah_end, actual_duration
            )
    else:
        logger.info("Reciter has no Quran.com ID — using ayah-timed fallback")
        subtitle_schedule = _ayah_timed_fallback(
            ayah_texts, ayah_start, ayah_end, actual_duration
        )

    # Build video
    templates = list_template_files()
    if not templates:
        logger.error("No template videos found in assets/templates/")
        return False

    template_name = database.get_next_template(templates)
    surah_name = _get_surah_name_arabic(surah)
    top_text = f"سورة {surah_name} | {reciter.get('name_ar', '')}"

    output_path = os.path.join(OUTPUT_DIR, f"reel_{surah:03d}_{ayah_start}.mp4")

    try:
        _build_reel_video(
            template_filename=template_name,
            audio_path=audio_path,
            subtitle_schedule=subtitle_schedule,
            top_text=top_text,
            output_path=output_path,
        )
    except Exception as e:
        logger.error("Reel build failed: %s", e)
        cleanup_output_folder()
        return False

    # Validate before upload
    valid, reason = validate_video(output_path)
    if not valid:
        logger.error("Video validation failed: %s", reason)
        from modules.telegram_review import send_alert
        send_alert(f"Reel validation failed: {reason}")
        cleanup_output_folder()
        return False

    caption = _build_caption(surah_name, ayah_start, ayah_end, reciter)
    post_db_id = database.log_post(
        "reel", f"{surah}:{ayah_start}-{ayah_end}", status="pending_review"
    )

    # ── Telegram approval gate (mandatory) ────────────────────────────────────
    from modules.telegram_review import send_for_review
    post_token = f"reel_{surah}_{ayah_start}"
    approved = send_for_review(
        media_path=output_path,
        caption=caption,
        post_token=post_token,
        media_type="video",
        timeout_hours=6,
    )

    if not approved:
        database.update_post_status(post_db_id, "rejected", error_message="Rejected via Telegram")
        cleanup_output_folder()
        return False

    # Post
    from modules.instagram_api import post_reel
    result = post_reel(output_path, caption, post_db_id)

    # Update progress
    database.update_recitation_progress(reciter["id"], surah, ayah_end)
    cleanup_output_folder()
    return result is not None


def _ayah_timed_fallback(
    ayah_texts: dict[int, str],
    ayah_start: int,
    ayah_end: int,
    total_duration_sec: float,
) -> list[dict]:
    """
    Ayah-timed subtitle fallback — zero dependencies, no external APIs.

    Distributes the audio duration evenly across the ayahs.
    Each ayah is displayed as a full subtitle block for its time slice.
    No word-level highlighting (highlight_word=None), but the full ayah
    text is shown in white — still looks clean and professional.

    This approach is completely free, offline-capable, and works for ANY reciter.
    """
    ayah_nums = list(range(ayah_start, ayah_end + 1))
    if not ayah_nums or not ayah_texts:
        logger.warning("No ayah texts available for subtitle fallback")
        return []

    # Distribute time evenly — ayahs with more words get slightly more time
    def _word_count(text: str) -> int:
        return max(1, len(text.split()))

    total_words = sum(_word_count(ayah_texts.get(n, "")) for n in ayah_nums)
    total_ms = int(total_duration_sec * 1000)

    schedule = []
    cursor_ms = 0
    for ayah_num in ayah_nums:
        text = ayah_texts.get(ayah_num, "")
        if not text:
            continue
        proportion = _word_count(text) / total_words
        duration_ms = int(total_ms * proportion)
        schedule.append({
            "start_ms": cursor_ms,
            "end_ms": cursor_ms + duration_ms,
            "text": text,
            "highlight_word": None,   # no word-level highlighting in this mode
        })
        cursor_ms += duration_ms

    logger.info("Ayah-timed fallback: %d subtitle blocks for ayahs %d–%d",
                len(schedule), ayah_start, ayah_end)
    return schedule
