"""
main.py
=======
Entry point for the Islamic Instagram Bot.
Initializes logging, validates config, starts database,
Telegram listener, then the APScheduler.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from config.settings import LOGS_DIR, OUTPUT_DIR


def setup_logging():
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log_path = os.path.join(LOGS_DIR, "bot.log")
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    for noisy in ("moviepy", "imageio", "PIL", "boto3", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def check_config(logger: logging.Logger) -> bool:
    """
    Validate credentials loaded from .env.
    Returns False and logs warnings if any required value is missing.
    Does NOT exit — the bot can still run partially (e.g. for testing).
    """
    from config.settings import validate_config
    missing = validate_config()
    if missing:
        logger.warning(
            "⚠️  Missing credentials — bot will fail when these features are used:\n%s\n"
            "   Fill in your .env file and restart.",
            "\n".join(missing),
        )
        return False
    return True


def main():
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("=" * 60)
    logger.info("Islamic Instagram Bot starting up...")
    logger.info("=" * 60)

    config_ok = check_config(logger)
    if config_ok:
        logger.info("Configuration validated — all credentials present.")

    # Initialize database
    from modules.database import initialize_db
    initialize_db()
    logger.info("Database ready.")

    # Start Telegram listener thread
    from modules.telegram_review import start_listener
    start_listener()
    logger.info("Telegram listener started.")

    # Setup and start scheduler
    from scheduler import scheduler, setup_scheduler
    setup_scheduler()
    logger.info("Scheduler configured. Bot is now running. Press Ctrl+C to stop.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical("Scheduler crashed: %s", e, exc_info=True)
        try:
            from modules.telegram_review import send_alert
            send_alert(f"💥 Bot CRASHED: {e}")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
