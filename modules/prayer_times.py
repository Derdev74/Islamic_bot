"""
modules/prayer_times.py
=======================
Fetches daily Fajr, Asr & Maghrib times from Aladhan.com API.
Note: Adkar al-Masae are recited from Asr until Maghrib (not after Maghrib).
"""

import logging
from datetime import datetime, time
from typing import Optional

import requests

from config.settings import CITY, COUNTRY, LATITUDE, LONGITUDE, PRAYER_METHOD, TIMEZONE

logger = logging.getLogger(__name__)

ALADHAN_BASE = "https://api.aladhan.com/v1"


def _parse_time(time_str: str) -> time:
    """Parse '05:23' into a datetime.time object."""
    h, m = map(int, time_str.split(":")[:2])
    return time(hour=h, minute=m)


def get_todays_times() -> Optional[dict[str, time]]:
    """
    Fetch today's Fajr and Maghrib times.
    Returns dict: {'fajr': datetime.time, 'maghrib': datetime.time}
    Returns None on failure so caller can use fallback times.
    """
    today = datetime.now().strftime("%d-%m-%Y")

    if LATITUDE and LONGITUDE:
        url = f"{ALADHAN_BASE}/timings/{today}"
        params = {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "method": PRAYER_METHOD,
        }
    else:
        url = f"{ALADHAN_BASE}/timingsByCity/{today}"
        params = {
            "city": CITY,
            "country": COUNTRY,
            "method": PRAYER_METHOD,
        }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        timings = data["data"]["timings"]
        return {
            "fajr": _parse_time(timings["Fajr"]),
            "asr": _parse_time(timings["Asr"]),
            "maghrib": _parse_time(timings["Maghrib"]),
        }
    except requests.RequestException as e:
        logger.error("Failed to fetch prayer times: %s", e)
        return None
    except (KeyError, ValueError) as e:
        logger.error("Unexpected Aladhan API response: %s", e)
        return None


def get_todays_times_with_fallback(
    fallback_fajr: tuple[int, int] = (5, 30),
    fallback_asr: tuple[int, int] = (15, 30),
    fallback_maghrib: tuple[int, int] = (18, 30),
) -> dict[str, time]:
    """Wraps get_todays_times with sensible fallback times."""
    result = get_todays_times()
    if result:
        return result
    logger.warning(
        "Using fallback prayer times: Fajr=%s:%s, Asr=%s:%s, Maghrib=%s:%s",
        *fallback_fajr, *fallback_asr, *fallback_maghrib,
    )
    return {
        "fajr": time(*fallback_fajr),
        "asr": time(*fallback_asr),
        "maghrib": time(*fallback_maghrib),
    }
