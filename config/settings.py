"""
config/settings.py
==================
Central configuration for the Islamic Instagram Bot.
All secrets are loaded from the .env file (or environment variables).
Do NOT hardcode credentials here.
"""

import os
from pathlib import Path

# Load .env file if present (python-dotenv)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass  # dotenv is optional; fall back to system env vars


def _require(key: str) -> str:
    """Return env var value; raise a clear error if missing."""
    val = os.getenv(key, "")
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set.\n"
            f"Edit your .env file or export the variable before starting the bot."
        )
    return val


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ── Instagram / Meta Graph API ───────────────────────────────────────────────
INSTAGRAM_USER_ID    = _optional("IG_USER_ID",   "PLACEHOLDER_ig_user_id")
INSTAGRAM_TOKEN      = _optional("IG_TOKEN",      "PLACEHOLDER_ig_token")
META_APP_ID          = _optional("META_APP_ID",   "")
META_APP_SECRET      = _optional("META_APP_SECRET", "")
META_API_VERSION     = "v19.0"
META_BASE_URL        = f"https://graph.facebook.com/{META_API_VERSION}"

# ── Cloudflare R2 ─────────────────────────────────────────────────────────────
R2_ACCOUNT_ID        = _optional("R2_ACCOUNT_ID",  "PLACEHOLDER_r2_account")
R2_ACCESS_KEY_ID     = _optional("R2_ACCESS_KEY",  "PLACEHOLDER_r2_key")
R2_SECRET_ACCESS_KEY = _optional("R2_SECRET_KEY",  "PLACEHOLDER_r2_secret")
R2_BUCKET_NAME       = _optional("R2_BUCKET",      "islamic-bot-media")
R2_PUBLIC_BASE_URL   = _optional("R2_PUBLIC_URL",  "PLACEHOLDER_r2_url")

# ── Telegram Bot ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN   = _optional("TELEGRAM_BOT_TOKEN", "PLACEHOLDER_tg_token")
TELEGRAM_CHAT_ID     = _optional("TELEGRAM_CHAT_ID",   "PLACEHOLDER_tg_chat")

# ── Location / Prayer Times ───────────────────────────────────────────────────
CITY          = _optional("CITY",     "Algiers")
COUNTRY       = _optional("COUNTRY",  "Algeria")
TIMEZONE      = _optional("TIMEZONE", "Africa/Algiers")

_lat = _optional("LAT", "")
_lon = _optional("LON", "")
LATITUDE  = float(_lat) if _lat else None
LONGITUDE = float(_lon) if _lon else None

PRAYER_METHOD = int(_optional("PRAYER_METHOD", "3"))

# ── Content Settings ──────────────────────────────────────────────────────────
ACCOUNT_HANDLE  = _optional("ACCOUNT_HANDLE", "@islamic_bot")
POST_LANGUAGE   = "ar"
JITTER_MINUTES  = 30    # ± minutes applied to all scheduled post times

# ── Quran Recitation ──────────────────────────────────────────────────────────
REEL_MIN_DURATION_SEC = 60
REEL_MAX_DURATION_SEC = 90

# ── Token Refresh ─────────────────────────────────────────────────────────────
TOKEN_REFRESH_INTERVAL_DAYS = 50    # proactive refresh before 60-day expiry

# ── File Paths ────────────────────────────────────────────────────────────────
BASE_DIR         = Path(__file__).resolve().parent.parent
ASSETS_DIR       = BASE_DIR / "assets"
FONTS_DIR        = ASSETS_DIR / "fonts"
TEMPLATES_DIR    = ASSETS_DIR / "templates"
BACKGROUNDS_DIR  = ASSETS_DIR / "backgrounds"
OVERLAYS_DIR     = ASSETS_DIR / "overlays"
DATA_DIR         = BASE_DIR / "data"
OUTPUT_DIR       = BASE_DIR / "output"
LOGS_DIR         = BASE_DIR / "logs"
DB_PATH          = BASE_DIR / "bot.db"

# Convert Path objects to strings for libraries that expect str
ASSETS_DIR       = str(ASSETS_DIR)
FONTS_DIR        = str(FONTS_DIR)
TEMPLATES_DIR    = str(TEMPLATES_DIR)
BACKGROUNDS_DIR  = str(BACKGROUNDS_DIR)
OVERLAYS_DIR     = str(OVERLAYS_DIR)
OUTPUT_DIR       = str(OUTPUT_DIR)
LOGS_DIR         = str(LOGS_DIR)
DB_PATH          = str(DB_PATH)

FONT_AMIRI_REGULAR = str(BASE_DIR / "assets" / "fonts" / "Amiri-Regular.ttf")
FONT_AMIRI_BOLD    = str(BASE_DIR / "assets" / "fonts" / "Amiri-Bold.ttf")
FONT_SCHEHERAZADE  = str(BASE_DIR / "assets" / "fonts" / "ScheherazadeNew-Regular.ttf")

ADKAR_SABAH_JSON = str(BASE_DIR / "data" / "adkar" / "sabah.json")
ADKAR_MASAE_JSON = str(BASE_DIR / "data" / "adkar" / "masae.json")
QURAN_PAGES_DIR  = str(BASE_DIR / "data" / "quran" / "pages")
RECITERS_JSON    = str(BASE_DIR / "config" / "reciters.json")
CAPTIONS_JSON    = str(BASE_DIR / "config" / "captions.json")


def validate_config() -> list[str]:
    """
    Check for missing required credentials.
    Returns a list of warning messages (empty = all good).
    """
    warnings = []
    checks = {
        "IG_USER_ID":        INSTAGRAM_USER_ID,
        "IG_TOKEN":          INSTAGRAM_TOKEN,
        "R2_ACCOUNT_ID":     R2_ACCOUNT_ID,
        "R2_ACCESS_KEY":     R2_ACCESS_KEY_ID,
        "R2_SECRET_KEY":     R2_SECRET_ACCESS_KEY,
        "R2_PUBLIC_URL":     R2_PUBLIC_BASE_URL,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID":  TELEGRAM_CHAT_ID,
    }
    for key, val in checks.items():
        if not val or val.startswith("PLACEHOLDER"):
            warnings.append(f"  Missing: {key}")
    return warnings
