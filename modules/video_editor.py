"""
modules/video_editor.py
=======================
moviepy + ffmpeg wrapper for building Reels and Story videos.
Includes pre-upload validation via ffprobe.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np
from moviepy.editor import (
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from PIL import Image

from config.settings import OUTPUT_DIR, TEMPLATES_DIR

logger = logging.getLogger(__name__)

INSTAGRAM_REEL_SPEC = {
    "width": 1080,
    "height": 1920,
    "codec": "h264",
    "min_size_bytes": 50_000,
}


# ── Template management ────────────────────────────────────────────────────────

def list_template_files() -> list[str]:
    """Return basenames of all .mp4 files in assets/templates/."""
    templates_path = Path(TEMPLATES_DIR)
    return [f.name for f in templates_path.glob("*.mp4")]


def load_template(filename: str) -> VideoFileClip:
    path = os.path.join(TEMPLATES_DIR, filename)
    return VideoFileClip(path)


def loop_to_duration(clip: VideoFileClip, target_duration: float) -> VideoFileClip:
    """Loop a clip until it reaches target_duration seconds."""
    if clip.duration >= target_duration:
        return clip.subclip(0, target_duration)
    repeats = int(target_duration / clip.duration) + 2
    clips = [clip] * repeats
    looped = concatenate_videoclips(clips)
    return looped.subclip(0, target_duration)


# ── Story video from static image ─────────────────────────────────────────────

def image_to_story_video(
    pil_image: Image.Image,
    duration: float,
    output_path: str,
    audio_path: Optional[str] = None,
    fade_duration: float = 0.5,
) -> str:
    """
    Convert a PIL image to a 1080×1920 MP4 story video.
    Optionally attaches audio. Returns output_path on success.
    """
    arr = np.array(pil_image.convert("RGB"))
    img_clip = ImageClip(arr).set_duration(duration)

    if fade_duration > 0:
        img_clip = img_clip.fadein(fade_duration).fadeout(fade_duration)

    if audio_path and os.path.exists(audio_path):
        audio = AudioFileClip(audio_path).subclip(0, duration)
        img_clip = img_clip.set_audio(audio)

    img_clip.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        ffmpeg_params=["-crf", "23", "-preset", "fast"],
        logger=None,
    )
    return output_path


# ── Reel assembly ──────────────────────────────────────────────────────────────

def build_reel(
    template_filename: str,
    audio_path: str,
    subtitle_clips: list,
    top_banner: Optional[Image.Image],
    bottom_banner: Optional[Image.Image],
    output_path: str,
) -> str:
    """
    Assemble the final Reel:
    1. Load template, loop to audio duration.
    2. Overlay subtitle ImageClips.
    3. Add top/bottom banners as static overlays.
    4. Attach audio.
    5. Export H.264 1080×1920.
    Returns output_path.
    """
    import numpy as np

    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration

    template = load_template(template_filename)
    template = loop_to_duration(template, duration).without_audio()

    layers = [template]

    # Static banners
    for banner_img, pos in [(top_banner, "top"), (bottom_banner, "bottom")]:
        if banner_img is not None:
            arr = np.array(banner_img.convert("RGBA"))
            banner_clip = ImageClip(arr, ismask=False).set_duration(duration)
            if pos == "top":
                banner_clip = banner_clip.set_position(("center", "top"))
            else:
                banner_clip = banner_clip.set_position(("center", "bottom"))
            layers.append(banner_clip)

    layers.extend(subtitle_clips)

    composite = CompositeVideoClip(layers, size=(1080, 1920))
    composite = composite.set_audio(audio_clip)

    composite.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        ffmpeg_params=["-crf", "23", "-preset", "fast", "-pix_fmt", "yuv420p"],
        logger=None,
    )
    logger.info("Reel written to %s", output_path)
    return output_path


# ── ffprobe validation (mandatory before upload) ──────────────────────────────

def validate_video(path: str) -> tuple[bool, str]:
    """
    Use ffprobe to verify the video meets Instagram Reel requirements.
    Returns (is_valid, reason).
    """
    if not os.path.exists(path):
        return False, "File does not exist"

    size = os.path.getsize(path)
    if size < INSTAGRAM_REEL_SPEC["min_size_bytes"]:
        return False, f"File too small: {size} bytes"

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height",
        "-of", "default=noprint_wrappers=1",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = {}
        for line in result.stdout.strip().splitlines():
            k, _, v = line.partition("=")
            info[k.strip()] = v.strip()

        codec = info.get("codec_name", "").lower()
        width = int(info.get("width", 0))
        height = int(info.get("height", 0))

        if codec not in ("h264", "avc"):
            return False, f"Wrong codec: {codec} (expected h264)"
        if width != INSTAGRAM_REEL_SPEC["width"] or height != INSTAGRAM_REEL_SPEC["height"]:
            return False, f"Wrong resolution: {width}×{height} (expected 1080×1920)"

        # Check audio presence
        audio_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        audio_result = subprocess.run(audio_cmd, capture_output=True, text=True, check=True)
        if not audio_result.stdout.strip():
            return False, "No audio stream found"

        logger.info("Video validation passed: %s", path)
        return True, "OK"

    except subprocess.CalledProcessError as e:
        return False, f"ffprobe error: {e.stderr}"
    except ValueError as e:
        return False, f"Parse error: {e}"


# ── Disk safety ────────────────────────────────────────────────────────────────

def cleanup_output_folder() -> None:
    """Delete all files in the output/ folder. Called at pipeline start and end."""
    output_path = Path(OUTPUT_DIR)
    count = 0
    for f in output_path.iterdir():
        if f.is_file():
            try:
                f.unlink()
                count += 1
            except OSError as e:
                logger.warning("Could not delete %s: %s", f, e)
    logger.info("Cleaned %d files from output/", count)
