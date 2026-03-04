"""
modules/instagram_api.py
========================
Official Meta Graph API calls: Reels, Stories, Feed Images.
Includes proactive token refresh every 50 days.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import boto3
import requests
from botocore.client import Config

from config.settings import (
    INSTAGRAM_TOKEN,
    INSTAGRAM_USER_ID,
    META_BASE_URL,
    R2_ACCESS_KEY_ID,
    R2_ACCOUNT_ID,
    R2_BUCKET_NAME,
    R2_PUBLIC_BASE_URL,
    R2_SECRET_ACCESS_KEY,
    TOKEN_REFRESH_INTERVAL_DAYS,
)
from modules.database import (
    get_token_last_refreshed,
    update_post_status,
    update_token_refresh_time,
)

logger = logging.getLogger(__name__)

# Mutable token — updated in memory on refresh
_current_token = INSTAGRAM_TOKEN


# ── Cloudflare R2 upload ───────────────────────────────────────────────────────

def _get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_to_r2(local_path: str, object_key: str) -> str:
    """
    Upload a file to Cloudflare R2 and return its public URL.
    object_key: e.g. 'reels/reel_20260101.mp4'
    """
    client = _get_r2_client()
    content_type = "video/mp4" if local_path.endswith(".mp4") else "image/jpeg"
    logger.info("Uploading %s → R2 key: %s", local_path, object_key)
    client.upload_file(
        local_path,
        R2_BUCKET_NAME,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )
    public_url = f"{R2_PUBLIC_BASE_URL.rstrip('/')}/{object_key}"
    logger.info("Public URL: %s", public_url)
    return public_url


def delete_from_r2(object_key: str) -> None:
    """Delete a file from R2 after posting."""
    client = _get_r2_client()
    try:
        client.delete_object(Bucket=R2_BUCKET_NAME, Key=object_key)
        logger.info("Deleted R2 object: %s", object_key)
    except Exception as e:
        logger.warning("Failed to delete R2 object %s: %s", object_key, e)


# ── Token management ───────────────────────────────────────────────────────────

def refresh_token_if_needed() -> None:
    """
    Proactively refresh the long-lived Instagram token every 50 days
    (before the 60-day expiry).
    """
    global _current_token
    last = get_token_last_refreshed()
    if datetime.utcnow() - last < timedelta(days=TOKEN_REFRESH_INTERVAL_DAYS):
        return

    logger.info("Token refresh due (last: %s). Refreshing...", last.date())
    url = f"{META_BASE_URL}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": os.getenv("META_APP_ID", ""),
        "client_secret": os.getenv("META_APP_SECRET", ""),
        "fb_exchange_token": _current_token,
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        new_token = data.get("access_token")
        if new_token:
            _current_token = new_token
            update_token_refresh_time()
            logger.info("Token refreshed successfully.")
        else:
            logger.error("Token refresh response missing access_token: %s", data)
    except requests.RequestException as e:
        logger.error("Token refresh request failed: %s", e)


def _token() -> str:
    return _current_token


# ── Media container creation ───────────────────────────────────────────────────

def _wait_for_media_ready(creation_id: str, max_wait: int = 120) -> bool:
    """Poll until Instagram finishes processing the media container."""
    for _ in range(max_wait // 5):
        resp = requests.get(
            f"{META_BASE_URL}/{creation_id}",
            params={"fields": "status_code", "access_token": _token()},
            timeout=15,
        )
        try:
            status = resp.json().get("status_code", "")
        except Exception:
            status = ""

        if status == "FINISHED":
            return True
        if status == "ERROR":
            logger.error("Instagram media container error for id %s", creation_id)
            return False
        time.sleep(5)
    logger.error("Timeout waiting for media container %s", creation_id)
    return False


def _create_media_container(media_type: str, media_url: str, caption: str = "") -> str | None:
    """Create a media container and return its creation_id."""
    params = {
        "media_type": media_type,
        "caption": caption,
        "access_token": _token(),
    }
    if media_type == "IMAGE":
        params["image_url"] = media_url
    else:
        params["video_url"] = media_url

    resp = requests.post(
        f"{META_BASE_URL}/{INSTAGRAM_USER_ID}/media",
        params=params,
        timeout=30,
    )
    data = resp.json()
    if "id" not in data:
        logger.error("Media container creation failed: %s", data)
        return None
    return data["id"]


def _publish_container(creation_id: str) -> str | None:
    """Publish a ready container and return the Instagram post ID."""
    resp = requests.post(
        f"{META_BASE_URL}/{INSTAGRAM_USER_ID}/media_publish",
        params={"creation_id": creation_id, "access_token": _token()},
        timeout=30,
    )
    data = resp.json()
    post_id = data.get("id")
    if not post_id:
        logger.error("Media publish failed: %s", data)
    return post_id


# ── Public posting functions ───────────────────────────────────────────────────

def post_reel(video_local_path: str, caption: str, post_db_id: int) -> str | None:
    """
    Upload video to R2, publish as Reel, delete from R2.
    Returns Instagram post ID or None on failure.
    """
    refresh_token_if_needed()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    r2_key = f"reels/reel_{ts}.mp4"

    public_url = upload_to_r2(video_local_path, r2_key)
    creation_id = _create_media_container("REELS", public_url, caption)
    if not creation_id:
        update_post_status(post_db_id, "failed", error_message="Container creation failed")
        delete_from_r2(r2_key)
        return None

    if not _wait_for_media_ready(creation_id):
        update_post_status(post_db_id, "failed", error_message="Media processing timeout")
        delete_from_r2(r2_key)
        return None

    post_id = _publish_container(creation_id)
    delete_from_r2(r2_key)

    if post_id:
        update_post_status(post_db_id, "success", instagram_post_id=post_id)
        logger.info("Reel posted: %s", post_id)
    else:
        update_post_status(post_db_id, "failed", error_message="Publish failed")
    return post_id


def post_image(image_local_path: str, caption: str, post_db_id: int) -> str | None:
    """
    Upload image to R2, post as feed IMAGE, delete from R2.
    """
    refresh_token_if_needed()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    r2_key = f"images/img_{ts}.jpg"

    public_url = upload_to_r2(image_local_path, r2_key)
    creation_id = _create_media_container("IMAGE", public_url, caption)
    if not creation_id:
        update_post_status(post_db_id, "failed", error_message="Container creation failed")
        delete_from_r2(r2_key)
        return None

    post_id = _publish_container(creation_id)
    delete_from_r2(r2_key)

    if post_id:
        update_post_status(post_db_id, "success", instagram_post_id=post_id)
        logger.info("Image posted: %s", post_id)
    else:
        update_post_status(post_db_id, "failed", error_message="Publish failed")
    return post_id


def post_story_video(video_local_path: str, post_db_id: int) -> str | None:
    """Upload video to R2, post as Story, delete from R2."""
    refresh_token_if_needed()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    r2_key = f"stories/story_{ts}.mp4"

    public_url = upload_to_r2(video_local_path, r2_key)
    creation_id = _create_media_container("STORIES", public_url)
    if not creation_id:
        update_post_status(post_db_id, "failed", error_message="Container creation failed")
        delete_from_r2(r2_key)
        return None

    if not _wait_for_media_ready(creation_id):
        update_post_status(post_db_id, "failed", error_message="Media processing timeout")
        delete_from_r2(r2_key)
        return None

    post_id = _publish_container(creation_id)
    delete_from_r2(r2_key)

    if post_id:
        update_post_status(post_db_id, "success", instagram_post_id=post_id)
        logger.info("Story posted: %s", post_id)
    else:
        update_post_status(post_db_id, "failed", error_message="Publish failed")
    return post_id


def post_story_image(image_local_path: str, post_db_id: int, caption: str = "") -> str | None:
    """
    Upload a JPEG image to R2, post as an Instagram Story (IMAGE type), delete from R2.
    Instagram Stories posted as images display for 24 hours — no video encoding needed.
    """
    refresh_token_if_needed()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    r2_key = f"stories/story_{ts}.jpg"

    public_url = upload_to_r2(image_local_path, r2_key)

    # Stories posted as images use media_type=STORIES with image_url
    params = {
        "media_type": "STORIES",
        "image_url": public_url,
        "access_token": _token(),
    }
    resp = requests.post(
        f"{META_BASE_URL}/{INSTAGRAM_USER_ID}/media",
        params=params,
        timeout=30,
    )
    data = resp.json()
    creation_id = data.get("id")

    if not creation_id:
        logger.error("Story image container creation failed: %s", data)
        update_post_status(post_db_id, "failed", error_message="Container creation failed")
        delete_from_r2(r2_key)
        return None

    post_id = _publish_container(creation_id)
    delete_from_r2(r2_key)

    if post_id:
        update_post_status(post_db_id, "success", instagram_post_id=post_id)
        logger.info("Story image posted: %s", post_id)
    else:
        update_post_status(post_db_id, "failed", error_message="Publish failed")
    return post_id
