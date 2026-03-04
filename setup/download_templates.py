"""
setup/download_templates.py
============================
Downloads free Islamic background videos from Pexels (free, no sign-up for these links).
Run once: python setup/download_templates.py

Videos are saved to assets/templates/ as portrait (1080×1920) MP4 files.
ffmpeg is used to re-encode them to the correct portrait format.

All videos are royalty-free for commercial/non-commercial use.
"""

import os
import subprocess
import sys
import urllib.request

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "templates")

# ── Free Islamic & nature video sources ───────────────────────────────────────
#
# These are direct download links from Pexels (free, no login needed).
# If any link fails, replace it — go to pexels.com/videos and search for:
#   "Kaaba", "Madinah", "mosque", "nature", "water", "clouds", "forest"
# Download the HD version, rename, and place in assets/templates/.
#
# Format needed: portrait MP4, 1080×1920, H.264
# The script below converts landscape videos to portrait by cropping the center.
# ──────────────────────────────────────────────────────────────────────────────

VIDEOS = [
    {
        "filename": "template_nature_1.mp4",
        "url": "https://www.pexels.com/video/8636600/download/?fps=25.0&h=1920&w=1080",
        "description": "Peaceful forest stream — nature",
    },
    {
        "filename": "template_nature_2.mp4",
        "url": "https://www.pexels.com/video/3045163/download/?fps=25.0&h=1920&w=1080",
        "description": "Ocean waves at sunset",
    },
    {
        "filename": "template_sky.mp4",
        "url": "https://www.pexels.com/video/3576378/download/?fps=25.0&h=1920&w=1080",
        "description": "Clouds moving slowly",
    },
]

# ── IMPORTANT: Kaaba/Madinah videos ──────────────────────────────────────────
#
# Authentic Kaaba and Masjid Al-Nabawi footage is available on:
#   • YouTube (use yt-dlp to download, then convert):
#       yt-dlp -f "bestvideo[ext=mp4]" "URL" -o assets/templates/template_kaaba.mp4
#   • The official Haramain Sharifain YouTube channel
#   • Archive.org Islamic video collections
#
# Or search Pexels: https://www.pexels.com/search/videos/mecca/
# ─────────────────────────────────────────────────────────────────────────────


def _convert_to_portrait(src: str, dst: str) -> bool:
    """
    Convert any video to 1080×1920 portrait using ffmpeg.
    Crops center of landscape video if needed.
    """
    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:v", "libx264", "-crf", "23", "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-an",          # remove audio — templates are silent (audio comes from Quran recitation)
        dst,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [WARN] ffmpeg conversion failed: {result.stderr[-300:]}")
        return False
    return True


def download_templates():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)

    for video in VIDEOS:
        dest = os.path.join(TEMPLATES_DIR, video["filename"])
        if os.path.exists(dest) and os.path.getsize(dest) > 100_000:
            print(f"  [SKIP] {video['filename']} already exists.")
            continue

        print(f"  [DL]   {video['filename']} — {video['description']}")
        tmp = dest + ".tmp.mp4"
        try:
            urllib.request.urlretrieve(video["url"], tmp)
        except Exception as e:
            print(f"  [FAIL] Download failed: {e}")
            print(f"         → Go to pexels.com/videos and download a portrait video manually.")
            print(f"         → Save it as: {dest}")
            if os.path.exists(tmp):
                os.remove(tmp)
            continue

        print(f"  [CONV] Converting to 1080×1920 portrait...")
        ok = _convert_to_portrait(tmp, dest)
        if ok:
            print(f"  [OK]   Saved: {dest}")
        else:
            # Keep the raw file, user can convert manually
            os.rename(tmp, dest)
            print(f"  [WARN] Saved raw (may need manual portrait conversion): {dest}")

        if os.path.exists(tmp):
            os.remove(tmp)

    print("\n── Manual step required for Islamic venue videos ──────────────────")
    print("Add Kaaba/Madinah videos manually to assets/templates/")
    print("Suggested sources:")
    print("  • pexels.com/search/videos/mecca/")
    print("  • pexels.com/search/videos/mosque/")
    print("  • yt-dlp + Haramain YouTube channel (educational/non-commercial use)")
    print("")
    print("After adding videos, update config/templates.json with the filenames.")


if __name__ == "__main__":
    print(f"Downloading templates to: {os.path.abspath(TEMPLATES_DIR)}")
    download_templates()
