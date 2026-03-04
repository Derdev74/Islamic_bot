"""
scheduler.py
============
Master APScheduler logic — schedules all 5 daily pipelines.
Fajr/Asr/Maghrib times are recalculated at midnight.
Adkar al-Masae fires at Asr time (traditional scholarly position).
All posting times include a ±30-min jitter.
"""

import logging
import random
from datetime import datetime, time, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import JITTER_MINUTES, TIMEZONE
from modules.prayer_times import get_todays_times_with_fallback

logger = logging.getLogger(__name__)

scheduler = BlockingScheduler(timezone=TIMEZONE)


# ── Jitter helper ──────────────────────────────────────────────────────────────

def _jittered_time(base_hour: int, base_minute: int) -> tuple[int, int]:
    """Apply ±JITTER_MINUTES random offset and return (hour, minute)."""
    offset = random.randint(-JITTER_MINUTES, JITTER_MINUTES)
    base_dt = datetime.now().replace(hour=base_hour, minute=base_minute,
                                     second=0, microsecond=0)
    jittered = base_dt + timedelta(minutes=offset)
    return jittered.hour, jittered.minute


# ── Pipeline wrappers ──────────────────────────────────────────────────────────

def _job_adkar_sabah():
    try:
        from modules.adkar_generator import run_adkar_pipeline
        run_adkar_pipeline("sabah")
    except Exception as e:
        logger.error("Adkar Sabah pipeline crashed: %s", e, exc_info=True)
        _alert(f"Adkar Sabah crashed: {e}")


def _job_adkar_masae():
    try:
        from modules.adkar_generator import run_adkar_pipeline
        run_adkar_pipeline("masae")
    except Exception as e:
        logger.error("Adkar Masae pipeline crashed: %s", e, exc_info=True)
        _alert(f"Adkar Masae crashed: {e}")


def _job_wird():
    try:
        from modules.wird_generator import run_wird_pipeline
        run_wird_pipeline()
    except Exception as e:
        logger.error("Wird pipeline crashed: %s", e, exc_info=True)
        _alert(f"Wird pipeline crashed: {e}")


def _job_hadith():
    try:
        from modules.hadith_generator import run_hadith_pipeline
        run_hadith_pipeline()
    except Exception as e:
        logger.error("Hadith pipeline crashed: %s", e, exc_info=True)
        _alert(f"Hadith pipeline crashed: {e}")


def _job_reel():
    try:
        from modules.recitation_pipeline import run_recitation_pipeline
        run_recitation_pipeline()
    except Exception as e:
        logger.error("Recitation Reel pipeline crashed: %s", e, exc_info=True)
        _alert(f"Reel pipeline crashed: {e}")


def _alert(msg: str):
    try:
        from modules.telegram_review import send_alert
        send_alert(msg)
    except Exception:
        pass


def _heartbeat():
    """Daily heartbeat — confirms bot is alive via Telegram."""
    try:
        from modules.telegram_review import send_heartbeat
        from modules.database import get_current_wird_page
        page = get_current_wird_page()
        msg = (
            f"Bot is alive ✅\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Next Wird page: {page}"
        )
        send_heartbeat(msg)
    except Exception as e:
        logger.warning("Heartbeat failed: %s", e)


# ── Dynamic job rescheduler (called at midnight) ───────────────────────────────

def refresh_daily_jobs():
    """
    Called at 00:01 every day.
    Recalculates Fajr & Maghrib times and reschedules prayer-dependent jobs.
    Also recalculates jitter for static jobs.
    """
    logger.info("Refreshing daily job schedule...")
    times = get_todays_times_with_fallback()
    fajr: time = times["fajr"]
    asr: time = times["asr"]

    # Adkar Sabah: Fajr + 5 min + jitter
    sabah_h, sabah_m = _jittered_time(fajr.hour, fajr.minute + 5)
    scheduler.reschedule_job(
        "adkar_sabah",
        trigger=CronTrigger(hour=sabah_h, minute=sabah_m, timezone=TIMEZONE),
    )

    # Adkar Masae: Asr + 5 min + jitter
    # (Adkar al-masae are recited from Asr until Maghrib, not after Maghrib)
    masae_h, masae_m = _jittered_time(asr.hour, asr.minute + 5)
    scheduler.reschedule_job(
        "adkar_masae",
        trigger=CronTrigger(hour=masae_h, minute=masae_m, timezone=TIMEZONE),
    )

    # Re-jitter static jobs
    wird_h, wird_m = _jittered_time(7, 0)
    scheduler.reschedule_job(
        "wird",
        trigger=CronTrigger(hour=wird_h, minute=wird_m, timezone=TIMEZONE),
    )

    hadith_h, hadith_m = _jittered_time(9, 0)
    scheduler.reschedule_job(
        "hadith",
        trigger=CronTrigger(hour=hadith_h, minute=hadith_m, timezone=TIMEZONE),
    )

    reel_h, reel_m = _jittered_time(10, 0)
    scheduler.reschedule_job(
        "reel",
        trigger=CronTrigger(hour=reel_h, minute=reel_m, timezone=TIMEZONE),
    )

    logger.info(
        "Schedule refreshed — Sabah(Fajr+5) %02d:%02d | Masae(Asr+5) %02d:%02d | "
        "Wird %02d:%02d | Hadith %02d:%02d | Reel %02d:%02d",
        sabah_h, sabah_m, masae_h, masae_m,
        wird_h, wird_m, hadith_h, hadith_m, reel_h, reel_m,
    )


# ── Scheduler setup ────────────────────────────────────────────────────────────

def setup_scheduler():
    """Register all jobs with initial times. Call once before scheduler.start()."""

    # ── Fixed-time jobs (will be re-jittered at midnight) ─────────────────────
    scheduler.add_job(
        _job_wird, "cron", id="wird",
        hour=7, minute=0, timezone=TIMEZONE,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        _job_hadith, "cron", id="hadith",
        hour=9, minute=0, timezone=TIMEZONE,
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        _job_reel, "cron", id="reel",
        hour=10, minute=0, timezone=TIMEZONE,
        misfire_grace_time=1800,
    )

    # ── Prayer-time jobs (placeholder times, overwritten at midnight) ──────────
    scheduler.add_job(
        _job_adkar_sabah, "cron", id="adkar_sabah",
        hour=5, minute=35, timezone=TIMEZONE,   # placeholder
        misfire_grace_time=1800,
    )
    scheduler.add_job(
        _job_adkar_masae, "cron", id="adkar_masae",
        hour=15, minute=35, timezone=TIMEZONE,  # placeholder (Asr), overwritten at midnight
        misfire_grace_time=1800,
    )

    # ── Midnight refresh ───────────────────────────────────────────────────────
    scheduler.add_job(
        refresh_daily_jobs, "cron", id="refresh",
        hour=0, minute=1, timezone=TIMEZONE,
    )

    # ── Daily heartbeat ────────────────────────────────────────────────────────
    scheduler.add_job(
        _heartbeat, "cron", id="heartbeat",
        hour=0, minute=5, timezone=TIMEZONE,
    )

    # ── Retry failed posts every 30 minutes ───────────────────────────────────
    scheduler.add_job(
        _retry_failed_posts, "interval", id="retry",
        minutes=30,
    )

    # Run refresh immediately on startup to set correct prayer times
    refresh_daily_jobs()


def _retry_failed_posts():
    """Retry posts that failed and haven't exceeded max retries."""
    try:
        from modules.database import get_pending_retry_posts, update_post_status
        failed = get_pending_retry_posts(max_retries=3)
        if not failed:
            return
        logger.info("Retrying %d failed posts...", len(failed))
        for post in failed:
            logger.info("Retrying post id=%d type=%s", post["id"], post["type"])
            # Mark as retrying
            update_post_status(post["id"], "retrying")
            # Re-run appropriate pipeline
            post_type = post["type"]
            if post_type == "reel":
                _job_reel()
            elif post_type == "hadith":
                _job_hadith()
            elif post_type == "wird":
                _job_wird()
    except Exception as e:
        logger.error("Retry job failed: %s", e)
