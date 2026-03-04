"""
modules/audio_fetcher.py
========================
Downloads Quran recitation audio from mp3quran.net
and trims segments using ffmpeg.
"""

import logging
import os
import subprocess
from pathlib import Path

import requests

from config.settings import OUTPUT_DIR

logger = logging.getLogger(__name__)


def _mp3quran_url(server: str, code: str, surah: int) -> str:
    """Build the direct MP3 URL for a full surah."""
    surah_str = f"{surah:03d}"
    return f"https://{server}.mp3quran.net/{code}/{surah_str}.mp3"


def download_surah(server: str, code: str, surah: int, dest_path: str) -> bool:
    """
    Download a full surah MP3 to dest_path.
    Returns True on success.
    """
    url = _mp3quran_url(server, code, surah)
    logger.info("Downloading surah %d from %s", surah, url)
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        logger.info("Saved to %s (%.1f MB)", dest_path,
                    os.path.getsize(dest_path) / 1_048_576)
        return True
    except requests.RequestException as e:
        logger.error("Audio download failed: %s", e)
        return False


def trim_audio(
    input_path: str,
    output_path: str,
    start_sec: float,
    end_sec: float,
    normalize: bool = True,
) -> bool:
    """
    Trim an MP3 to [start_sec, end_sec] using ffmpeg.
    Applies loudnorm filter if normalize=True.
    Returns True on success.
    """
    af_filter = "loudnorm=I=-16:TP=-1.5:LRA=11" if normalize else "anull"
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", str(start_sec),
        "-to", str(end_sec),
        "-af", af_filter,
        "-c:a", "aac",          # re-encode to AAC for Instagram
        "-b:a", "128k",
        output_path,
    ]
    logger.info("Trimming audio: %s → %s (%.1fs – %.1fs)", input_path, output_path,
                start_sec, end_sec)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg trim failed:\n%s", e.stderr)
        return False


def get_audio_duration(path: str) -> float:
    """Return duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        logger.error("ffprobe duration check failed: %s", e)
        return 0.0


def fetch_and_trim_segment(
    reciter: dict,
    surah: int,
    start_sec: float,
    end_sec: float,
) -> str | None:
    """
    High-level helper: downloads the full surah, trims to [start_sec, end_sec].
    Returns path to trimmed audio file, or None on failure.
    """
    full_path = os.path.join(OUTPUT_DIR, f"surah_{surah:03d}_{reciter['id']}_full.mp3")
    trimmed_path = os.path.join(OUTPUT_DIR, f"segment_{surah:03d}_{reciter['id']}.aac")

    if not os.path.exists(full_path):
        ok = download_surah(reciter["server"], reciter["code"], surah, full_path)
        if not ok:
            return None

    if not trim_audio(full_path, trimmed_path, start_sec, end_sec):
        return None

    # Remove the large full surah file to save disk
    try:
        os.remove(full_path)
    except OSError:
        pass

    return trimmed_path
