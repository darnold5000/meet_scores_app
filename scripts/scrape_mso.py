from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from gym_scores.mso_scraper import scrape_mso_meet
from gym_scores.storage import connect, default_db_path, init_db, insert_athlete_rows, insert_scrape_run


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape a MeetScoresOnline meet into SQLite.")
    parser.add_argument("--url", required=True, help="MSO meet URL (e.g. https://www.meetscoresonline.com/R36478)")
    parser.add_argument("--db", default=None, help="Optional path to sqlite db")
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve() if args.db else default_db_path(PROJECT_DIR)

    rows = scrape_mso_meet(args.url)
    meet_key = rows[0]["meet_id"] if rows else "MSO-UNKNOWN"

    conn = connect(db_path)
    init_db(conn)
    run_id = insert_scrape_run(conn, meet_key=meet_key, source_url=args.url)
    inserted = insert_athlete_rows(conn, run_id=run_id, meet_key=meet_key, rows=rows)
    logging.info("Inserted %d rows into %s (run_id=%s, meet_key=%s)", inserted, db_path, run_id, meet_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

