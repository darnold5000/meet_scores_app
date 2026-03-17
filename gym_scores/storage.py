from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scrape_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  meet_key TEXT NOT NULL,
  source_url TEXT NOT NULL,
  created_at_unix INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS athlete_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
  meet_key TEXT NOT NULL,
  session TEXT,
  level TEXT,
  division TEXT,
  athlete_name TEXT NOT NULL,
  gym TEXT NOT NULL,

  aa_score REAL,
  aa_place INTEGER,

  vault REAL,
  vault_place INTEGER,
  bars REAL,
  bars_place INTEGER,
  beam REAL,
  beam_place INTEGER,
  floor REAL,
  floor_place INTEGER,

  record_hash TEXT NOT NULL,
  raw_json TEXT,
  UNIQUE(run_id, record_hash)
);

CREATE INDEX IF NOT EXISTS idx_scores_meet ON athlete_scores(meet_key);
CREATE INDEX IF NOT EXISTS idx_scores_filters ON athlete_scores(meet_key, session, level, division);
CREATE INDEX IF NOT EXISTS idx_scores_athlete ON athlete_scores(meet_key, athlete_name);
"""


@dataclass(frozen=True)
class LatestRun:
    run_id: int
    meet_key: str
    source_url: str
    created_at_unix: int


def default_db_path(project_dir: Path) -> Path:
    return project_dir / "data" / "gym_scores.sqlite3"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def insert_scrape_run(conn: sqlite3.Connection, meet_key: str, source_url: str) -> int:
    cur = conn.execute(
        "INSERT INTO scrape_runs(meet_key, source_url, created_at_unix) VALUES(?,?,?)",
        (meet_key, source_url, int(time.time())),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_athlete_rows(conn: sqlite3.Connection, run_id: int, meet_key: str, rows: Iterable[dict[str, Any]]) -> int:
    inserted = 0
    for r in rows:
        # expected keys from scraper: athlete_name, gym, level, division, session,
        # score (AA), place (AA), vault/bars/beam/floor + *_place, record_hash, raw_row
        payload = (
            run_id,
            meet_key,
            r.get("session"),
            r.get("level"),
            r.get("division"),
            r.get("athlete_name"),
            r.get("gym"),
            r.get("score"),
            r.get("place"),
            r.get("vault"),
            r.get("vault_place"),
            r.get("bars"),
            r.get("bars_place"),
            r.get("beam"),
            r.get("beam_place"),
            r.get("floor"),
            r.get("floor_place"),
            r.get("record_hash"),
            json.dumps(r.get("raw_row"), ensure_ascii=False) if r.get("raw_row") is not None else None,
        )
        try:
            conn.execute(
                """
                INSERT INTO athlete_scores(
                  run_id, meet_key, session, level, division, athlete_name, gym,
                  aa_score, aa_place,
                  vault, vault_place, bars, bars_place, beam, beam_place, floor, floor_place,
                  record_hash, raw_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                payload,
            )
            inserted += 1
        except sqlite3.IntegrityError:
            # duplicates within a run are ignored via UNIQUE(run_id, record_hash)
            continue
    conn.commit()
    return inserted


def get_latest_run(conn: sqlite3.Connection, meet_key: str) -> Optional[LatestRun]:
    row = conn.execute(
        """
        SELECT id, meet_key, source_url, created_at_unix
        FROM scrape_runs
        WHERE meet_key = ?
        ORDER BY created_at_unix DESC, id DESC
        LIMIT 1
        """,
        (meet_key,),
    ).fetchone()
    if not row:
        return None
    return LatestRun(
        run_id=int(row["id"]),
        meet_key=str(row["meet_key"]),
        source_url=str(row["source_url"]),
        created_at_unix=int(row["created_at_unix"]),
    )


def list_filter_values(conn: sqlite3.Connection, meet_key: str, column: str) -> list[str]:
    if column not in {"session", "level", "division"}:
        raise ValueError("unsupported filter column")
    rows = conn.execute(
        f"""
        SELECT DISTINCT {column} AS v
        FROM athlete_scores
        WHERE meet_key = ? AND {column} IS NOT NULL AND TRIM({column}) != ''
        ORDER BY v
        """,
        (meet_key,),
    ).fetchall()
    return [str(r["v"]) for r in rows if r["v"] is not None]


def query_scores(
    conn: sqlite3.Connection,
    meet_key: str,
    *,
    session: Optional[str] = None,
    level: Optional[str] = None,
    division: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 500,
) -> list[sqlite3.Row]:
    where = ["meet_key = ?", "run_id = (SELECT id FROM scrape_runs WHERE meet_key = ? ORDER BY created_at_unix DESC, id DESC LIMIT 1)"]
    params: list[Any] = [meet_key, meet_key]
    if session and session != "All":
        where.append("session = ?")
        params.append(session)
    if level and level != "All":
        where.append("level = ?")
        params.append(level)
    if division and division != "All":
        where.append("division = ?")
        params.append(division)
    if q:
        where.append("(LOWER(athlete_name) LIKE ? OR LOWER(gym) LIKE ?)")
        like = f"%{q.strip().lower()}%"
        params.extend([like, like])

    sql = f"""
    SELECT
      athlete_name, gym, session, level, division,
      aa_score, aa_place,
      vault, vault_place, bars, bars_place, beam, beam_place, floor, floor_place
    FROM athlete_scores
    WHERE {' AND '.join(where)}
    ORDER BY
      CASE WHEN aa_score IS NULL THEN 1 ELSE 0 END,
      aa_score DESC,
      athlete_name ASC
    LIMIT ?
    """
    params.append(int(limit))
    return conn.execute(sql, params).fetchall()

