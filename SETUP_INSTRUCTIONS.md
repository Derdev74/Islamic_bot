# Islamic Instagram Bot — Setup Instructions

## Overview

The code is complete. This document lists every action required from you before the bot can run in production. Nothing in the code needs to be edited — all configuration is done through the `.env` file.

---

## Quick Start (5-step summary)

```
1. pip install -r requirements.txt
2. cp .env  →  fill in credentials
3. Add fonts to assets/fonts/
4. Add template videos to assets/templates/
5. python setup/download_quran_pages.py  (one time, ~10 min)
6. python main.py
```

---

## Step 1 — Install Dependencies

```bash
pip install -r requirements.txt
```

**Also install ffmpeg system-wide (not via pip):**

| OS | Command |
|---|---|
| Windows | Download from ffmpeg.org → add `bin/` folder to PATH |
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| macOS | `brew install ffmpeg` |

Verify: `ffmpeg -version` and `ffprobe -version` should both work in terminal.

---

## Step 2 — Fill in Your .env File

Open `.env` and fill in every value:

```env
# Instagram
IG_USER_ID=123456789012345        ← numeric ID, not your username
IG_TOKEN=EAAxxxxxxxxxxxxx          ← long-lived token (60 days)
META_APP_ID=your_app_id
META_APP_SECRET=your_app_secret

# Cloudflare R2
R2_ACCOUNT_ID=abc123def456
R2_ACCESS_KEY=your_access_key
R2_SECRET_KEY=your_secret_key
R2_BUCKET=islamic-bot-media
R2_PUBLIC_URL=https://pub-xxxx.r2.dev

# Telegram
TELEGRAM_BOT_TOKEN=1234567890:AAxxxxxx
TELEGRAM_CHAT_ID=987654321

# Location
CITY=Algiers
COUNTRY=Algeria
TIMEZONE=Africa/Algiers

# Your account watermark
ACCOUNT_HANDLE=@your_handle
```

**Never commit `.env` to git — it is listed in `.gitignore`.**

---

## Step 3 — Get Your API Credentials

### A. Meta / Instagram Graph API

1. Go to **developers.facebook.com** → Create App → Business type
2. Add the **Instagram Graph API** product
3. Connect your **Professional Instagram account** (Business or Creator) to a Facebook Page
4. In the Graph API Explorer, request a **User Access Token** with:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_read_engagement`
5. Exchange it for a **Long-Lived Token** (valid 60 days):
   ```
   GET https://graph.facebook.com/oauth/access_token
     ?grant_type=fb_exchange_token
     &client_id=APP_ID
     &client_secret=APP_SECRET
     &fb_exchange_token=SHORT_LIVED_TOKEN
   ```
6. Find your **Instagram User ID**:
   ```
   GET https://graph.facebook.com/me/accounts?access_token=TOKEN
   ```
   Then: `GET /{page_id}?fields=instagram_business_account&access_token=TOKEN`

The bot refreshes the token automatically every 50 days via the Token Refresh job.

### B. Cloudflare R2

1. Sign up at **cloudflare.com** (free)
2. Go to **R2 Object Storage** → Create bucket: `islamic-bot-media`
3. **Manage R2 API Tokens** → Create token with **Object Read & Write**
4. Copy: Account ID, Access Key ID, Secret Access Key
5. Bucket **Settings → Enable Public Access** → copy the `pub-xxxx.r2.dev` URL

### C. Telegram Bot

1. Message **@BotFather** on Telegram → `/newbot` → follow steps
2. Copy the **Bot Token** (`1234567890:AAxxxx...`)
3. Start a chat with your new bot, then visit:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   Your **Chat ID** is the `"id"` inside `"chat"` in the response.

---

## Step 4 — Download Fonts

Download these **free Google Fonts** and place the `.ttf` files in `assets/fonts/`:

| Font | Files needed | Download |
|---|---|---|
| **Amiri** | `Amiri-Regular.ttf`, `Amiri-Bold.ttf` | fonts.google.com/specimen/Amiri |
| **Scheherazade New** | `ScheherazadeNew-Regular.ttf` | fonts.google.com/specimen/Scheherazade+New |

Both fonts support full tashkeel (harakat). The bot will not render Arabic correctly without them.

---

## Step 5 — Add Template Videos

Template videos are the background loops used for Reels and Adkar stories.

**Requirements:** portrait MP4, 1080×1920, H.264, no audio (bot adds its own audio)

**Option A — Run the download script:**
```bash
python setup/download_templates.py
```
This fetches 3 free nature videos from Pexels and converts them to portrait format.

**Option B — Add your own:**
- Place `.mp4` files in `assets/templates/`
- Update `config/templates.json` with the filenames
- Free sources: pexels.com/videos (search: nature, clouds, water, mosque)
- For Kaaba/Madinah: search pexels.com/search/videos/mecca/ or use yt-dlp with the official Haramain Sharifain YouTube channel

---

## Step 6 — Add Your Custom Adkar Photos (Optional but recommended)

Instead of auto-generated text images, you can provide your own beautiful adkar designs:

| Folder | Used for |
|---|---|
| `assets/adkar_sabah/` | Morning adkar photos |
| `assets/adkar_masae/` | Evening adkar photos |

- Format: JPG or PNG, any size (bot resizes to 1080×1920)
- Name them anything: `01.jpg`, `adkar_morning_1.jpg`, etc.
- The bot rotates through them in alphabetical order, synced with the adkar list
- If a folder is empty, the bot auto-generates a text image instead

---

## Step 7 — Add Background Images

Used for Hadith cards and auto-generated Adkar images (when no custom photos are provided):

- Folder: `assets/backgrounds/`
- Format: JPG or PNG
- Recommended: Islamic calligraphy, geometric patterns, nature scenes, 1080×1920 or 1080×1080

---

## Step 8 — Verify Reciter URLs

Open `config/reciters.json`. Each reciter has a `_verify_url` field.
Paste each URL in your browser and confirm it plays audio:

| Reciter | URL |
|---|---|
| Abdul Basit | `server7.mp3quran.net/AbdAlBaset/001.mp3` |
| Al-Minshawi | `server10.mp3quran.net/Minshawy/001.mp3` |
| Al-Shuraim | `server7.mp3quran.net/Shuraym/001.mp3` |
| Al-Dossary | `server11.mp3quran.net/Dussary/001.mp3` |
| **Lohaidan** | `server9.mp3quran.net/Lhidan/001.mp3` ← verify this one |

If any URL returns 404, browse mp3quran.net to find the correct server/code and update the JSON.

**Subtitle notes:**
- Abdul Basit & Al-Minshawi → word-by-word karaoke highlighting (Quran.com timestamps)
- Al-Shuraim → word-by-word highlighting (Quran.com ID: 3)
- Al-Dossary & Lohaidan → full ayah display, timed by word count (no extra tools needed)

---

## Step 9 — Download Quran Pages (One Time)

```bash
python setup/download_quran_pages.py
```

Downloads all 604 Medina Mushaf page images (~10 minutes, ~500MB).
After this the Wird pipeline is fully offline and never needs the internet for pages again.

---

## Step 10 — Run the Bot

```bash
python main.py
```

The bot will:
1. Load `.env` credentials
2. Validate all settings and warn about any missing values
3. Initialize the SQLite database
4. Connect to Telegram (approval gateway)
5. Fetch today's Fajr, Asr, and Maghrib times from Aladhan API
6. Schedule all 5 pipelines with jitter
7. Run indefinitely (Ctrl+C to stop)

---

## Daily Schedule

| Time | Pipeline | Format | Approval needed? |
|---|---|---|---|
| 00:01 | Refresh prayer times | Internal | No |
| 00:05 | Heartbeat → Telegram | Internal | No |
| Fajr + 5 min ± 30 | Adkar al-Sabah | Instagram Story (image) | No |
| 07:00 ± 30 min | Wird — Quran page N | Instagram Story (image) | No |
| 09:00 ± 30 min | Daily Hadith | Instagram Feed Image | **Yes — /approve** |
| 10:00 ± 30 min | Quran Recitation Reel | Instagram Reel | **Yes — /approve** |
| Asr + 5 min ± 30 | Adkar al-Masae | Instagram Story (image) | No |

---

## Telegram Commands

When a Reel or Hadith is ready, you receive it on Telegram with a token:

```
/approve reel_2_1       ← publish to Instagram
/reject  reel_2_1       ← discard this post
```

Posts auto-reject after 6 hours if no response (configurable in `telegram_review.py`).

---

## Git & Security Notes

The following are in `.gitignore` and will **never** be committed:

| Item | Why |
|---|---|
| `.env` | Contains all your API keys |
| `.claude/` | Claude AI session data |
| `bot.db` | Contains post history (back up manually) |
| `output/` | Temp files auto-deleted by bot |
| `logs/` | Runtime logs |
| `data/quran/pages/` | 604 PNG files, ~500MB |
| `assets/templates/*.mp4` | Large video files |
| `Plan/` | Design documents |

---

## What Is Complete (Code Status)

| File | Status |
|---|---|
| `main.py` | Production-ready entry point |
| `scheduler.py` | APScheduler with prayer-time jitter |
| `config/settings.py` | Loads from .env via python-dotenv |
| `modules/database.py` | All SQLite operations |
| `modules/subtitle_engine.py` | Arabic RTL rendering with tashkeel |
| `modules/prayer_times.py` | Aladhan API — returns Fajr, Asr, Maghrib |
| `modules/audio_fetcher.py` | mp3quran.net download + ffmpeg trim + loudnorm |
| `modules/video_editor.py` | moviepy assembly + ffprobe validation |
| `modules/instagram_api.py` | Reels, Feed Images, Story Images + token refresh |
| `modules/telegram_review.py` | Approval gateway |
| `modules/adkar_generator.py` | Pipelines 1 & 2 — posts as image story |
| `modules/wird_generator.py` | Pipeline 3 — daily Quran page |
| `modules/hadith_generator.py` | Pipeline 5 — daily Hadith |
| `modules/recitation_pipeline.py` | Pipeline 4 — flagship Reel builder |
| `data/adkar/sabah.json` | 18 Adkar al-Sabah entries |
| `data/adkar/masae.json` | 18 Adkar al-Masae entries |
| `config/reciters.json` | 5 reciters configured |
| `config/captions.json` | Arabic caption templates |
| `.env` | Template — fill in your values |
| `.gitignore` | Protects secrets and large files |

---

## What You Still Need to Provide

- [ ] Fill in `.env` with your real credentials (Meta, R2, Telegram)
- [ ] Add `Amiri-Regular.ttf`, `Amiri-Bold.ttf`, `ScheherazadeNew-Regular.ttf` → `assets/fonts/`
- [ ] Add template videos → `assets/templates/` (or run `setup/download_templates.py`)
- [ ] Add background images → `assets/backgrounds/`
- [ ] Send your custom adkar photos → `assets/adkar_sabah/` and `assets/adkar_masae/`
- [ ] Verify the 5 reciter URLs in `config/reciters.json`
- [ ] Run `python setup/download_quran_pages.py` once
