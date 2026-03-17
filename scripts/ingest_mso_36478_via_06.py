from __future__ import annotations

"""
Ingest MSO-36478 using the proven `06_usag_meet_tracker` pipeline.

Run this OUTSIDE Cursor's sandbox in a real terminal.
It relies on `projects/06_usag_meet_tracker/.env` for DATABASE_URL.
"""

import os
import sys
import argparse
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest MSO-36478 via the 06 pipeline.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-scrape even if scores already exist in DB",
    )
    args = parser.parse_args()

    proj08 = Path(__file__).resolve().parents[1]
    proj06 = proj08.parent / "06_usag_meet_tracker"

    # Load the same env the 06 project uses (DATABASE_URL, LOG_LEVEL, etc.)
    load_dotenv(proj06 / ".env")

    # Ensure 06 imports work
    sys.path.insert(0, str(proj06))

    from ingest import save_meets, save_scores  # noqa: WPS433
    from agents.mso_api_scraper import scrape_mso_meet_api  # noqa: WPS433
    from agents.mso_scraper import scrape_mso_meet  # noqa: WPS433
    from core.normalizer import normalize_mso_api_record, normalize_mso_record  # noqa: WPS433
    from db.database import SessionLocal  # noqa: WPS433
    from db.models import Meet, Score  # noqa: WPS433

    meet = {
        "meet_id": "MSO-36478",
        "name": "2026 IN Compulsory State Championships",
        "mso_url": "https://www.meetscoresonline.com/R36478",
        "source": "mso",
        "state": "IN",
        "start_date": "2026-03-13",
        "location": "Crown Point, IN",
    }

    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is not set (check projects/06_usag_meet_tracker/.env)")

    save_meets([meet])

    # If we've already ingested this meet, avoid re-scraping unless --force.
    if not args.force:
        db = SessionLocal()
        try:
            m = db.query(Meet).filter(Meet.meet_id == meet["meet_id"]).first()
            if m:
                existing = db.query(Score).filter(Score.meet_id == m.id).count()
                if existing > 0:
                    print(f"Meet {meet['meet_id']} already has {existing} score rows in DB. Skipping scrape (use --force to refresh).")
                    return 0
        finally:
            db.close()

    # Prefer API scraper (more reliable for placement); fallback to HTML scraper.
    raw_rows = scrape_mso_meet_api(meet["mso_url"])
    normalized = []
    if raw_rows:
        for r in raw_rows:
            normalized.extend(normalize_mso_api_record(r))
    else:
        raw_rows = scrape_mso_meet(meet["mso_url"])
        for r in raw_rows:
            normalized.extend(normalize_mso_record(r))

    saved, skipped = save_scores(normalized, meet["meet_id"])
    print(f"Saved {saved} score rows (skipped {skipped} dupes).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

