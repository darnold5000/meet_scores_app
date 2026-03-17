# 08_gym_scores

Mobile-first live meet score viewer for MeetScoresOnline meets (starting with **2026 IN Compulsory State Championships**).

## What this is

- A lightweight web app (FastAPI + Jinja) optimized for phones
- Installable as a **Progressive Web App (PWA)** (Add to Home Screen)
- A Playwright-based scraper that pulls rendered MSO tables and stores them locally (SQLite)

## Quickstart

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

### 1) Ingest the meet into your existing DB (recommended)

```bash
python scripts/ingest_mso_36478_via_06.py
```

### 2) Run the web app

```bash
export DATABASE_URL="(same value you use for 06_usag_meet_tracker)"
uvicorn app.main:app --reload --port 8008
```

Open `http://localhost:8008` on your phone (same Wi‑Fi) or your laptop.

## Notes

- MSO content is rendered client-side; this relies on Playwright to load the page and extract the final HTML.
- Live updating: the UI polls the server for updates (no websockets yet).
- Run scraping/ingest in a regular terminal (outside Cursor sandbox), same as project `06_usag_meet_tracker`.

