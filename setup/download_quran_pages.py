"""
setup/download_quran_pages.py
==============================
One-time setup script: downloads all 604 Mushaf page images.
Run once: python setup/download_quran_pages.py
Takes ~10 minutes. After this, the Wird pipeline is fully offline.
"""

import os
import sys
import time

import requests

BASE_URL = "https://cdn.islamic.network/quran/images/high-resolution"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "quran", "pages")


def download_all_pages(start_page: int = 1, end_page: int = 604):
    os.makedirs(OUT_DIR, exist_ok=True)
    failed = []

    for page in range(start_page, end_page + 1):
        path = os.path.join(OUT_DIR, f"{page:03d}.png")
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            print(f"  [SKIP] Page {page:03d} already cached.")
            continue

        url = f"{BASE_URL}/{page}.png"
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)
            size_kb = len(r.content) // 1024
            print(f"  [OK]   Page {page:03d}/604  ({size_kb} KB)")
        except requests.RequestException as e:
            print(f"  [FAIL] Page {page:03d}: {e}")
            failed.append(page)
            time.sleep(2)  # brief pause before continuing

        # Rate-limit courtesy pause every 50 pages
        if page % 50 == 0:
            time.sleep(1)

    print(f"\nDone. Downloaded {end_page - start_page + 1 - len(failed)} pages.")
    if failed:
        print(f"Failed pages: {failed}")
        print("Re-run this script to retry failed pages.")


if __name__ == "__main__":
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 604
    print(f"Downloading Quran pages {start}–{end} to: {os.path.abspath(OUT_DIR)}")
    download_all_pages(start, end)
