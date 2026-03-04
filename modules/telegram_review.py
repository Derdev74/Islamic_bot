"""
modules/telegram_review.py
==========================
Human-in-the-Loop approval gateway via Telegram.
Sends media for review; waits for /approve or /reject.
NEVER auto-posts Reels or Hadiths without /approve.
"""

import logging
import threading
import time as time_module
from typing import Callable, Optional

import requests

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

TG_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# In-memory pending approvals: {post_token: Event}
_pending: dict[str, threading.Event] = {}
_approved: dict[str, bool] = {}
_listener_thread: Optional[threading.Thread] = None
_last_update_id: int = 0


# ── Telegram messaging ─────────────────────────────────────────────────────────

def _send_message(text: str, parse_mode: str = "HTML") -> None:
    try:
        requests.post(
            f"{TG_BASE}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=15,
        )
    except requests.RequestException as e:
        logger.error("Telegram sendMessage failed: %s", e)


def _send_video(video_path: str, caption: str) -> None:
    try:
        with open(video_path, "rb") as f:
            requests.post(
                f"{TG_BASE}/sendVideo",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]},
                files={"video": f},
                timeout=120,
            )
    except requests.RequestException as e:
        logger.error("Telegram sendVideo failed: %s", e)


def _send_photo(photo_path: str, caption: str) -> None:
    try:
        with open(photo_path, "rb") as f:
            requests.post(
                f"{TG_BASE}/sendPhoto",
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1024]},
                files={"photo": f},
                timeout=60,
            )
    except requests.RequestException as e:
        logger.error("Telegram sendPhoto failed: %s", e)


# ── Update polling ─────────────────────────────────────────────────────────────

def _poll_updates() -> None:
    global _last_update_id
    while True:
        try:
            resp = requests.get(
                f"{TG_BASE}/getUpdates",
                params={"offset": _last_update_id + 1, "timeout": 30, "allowed_updates": ["message"]},
                timeout=45,
            )
            data = resp.json()
            for update in data.get("result", []):
                _last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()

                if chat_id != str(TELEGRAM_CHAT_ID):
                    continue  # ignore messages from other chats

                parts = text.split(maxsplit=1)
                cmd = parts[0].lower() if parts else ""
                token = parts[1].strip() if len(parts) > 1 else ""

                if cmd == "/approve" and token in _pending:
                    _approved[token] = True
                    _pending[token].set()
                    _send_message(f"✅ Approved: <code>{token}</code>")
                    logger.info("Post approved via Telegram: %s", token)

                elif cmd == "/reject" and token in _pending:
                    _approved[token] = False
                    _pending[token].set()
                    _send_message(f"❌ Rejected: <code>{token}</code>")
                    logger.info("Post rejected via Telegram: %s", token)

        except requests.RequestException as e:
            logger.warning("Telegram poll error: %s", e)
            time_module.sleep(5)
        except Exception as e:
            logger.error("Unexpected error in Telegram poll: %s", e)
            time_module.sleep(5)


def start_listener() -> None:
    """Start the background polling thread (call once at bot startup)."""
    global _listener_thread
    if _listener_thread and _listener_thread.is_alive():
        return
    _listener_thread = threading.Thread(target=_poll_updates, daemon=True, name="TelegramListener")
    _listener_thread.start()
    logger.info("Telegram listener started.")


# ── Public review gate ─────────────────────────────────────────────────────────

def send_for_review(
    media_path: str,
    caption: str,
    post_token: str,
    media_type: str = "video",
    timeout_hours: int = 6,
) -> bool:
    """
    Send media to Telegram for human review.
    Blocks until /approve or /reject is received, or timeout expires.

    media_type: 'video' | 'photo'
    post_token: unique string to identify this post in /approve <token>
    Returns True if approved, False if rejected or timed out.
    """
    event = threading.Event()
    _pending[post_token] = event
    _approved[post_token] = False

    instructions = (
        f"🔍 <b>Review Required</b>\n\n"
        f"Token: <code>{post_token}</code>\n\n"
        f"Reply:\n"
        f"  /approve {post_token}\n"
        f"  /reject {post_token}\n\n"
        f"Auto-rejects in {timeout_hours}h."
    )
    _send_message(instructions)

    if media_type == "video":
        _send_video(media_path, caption[:500])
    else:
        _send_photo(media_path, caption[:500])

    _send_message(f"Caption preview:\n{caption[:800]}")

    approved = event.wait(timeout=timeout_hours * 3600)
    if not approved:
        logger.warning("Review timeout for token %s — auto-rejected.", post_token)
        _send_message(f"⏰ Timeout — post <code>{post_token}</code> was auto-rejected.")

    result = _approved.get(post_token, False)
    _pending.pop(post_token, None)
    _approved.pop(post_token, None)
    return result


def send_heartbeat(message: str) -> None:
    """Send a daily heartbeat / status message to Telegram."""
    _send_message(f"💓 <b>Bot Heartbeat</b>\n{message}")


def send_alert(message: str) -> None:
    """Send an urgent alert (e.g., token expiry warning, pipeline failure)."""
    _send_message(f"🚨 <b>ALERT</b>\n{message}")
