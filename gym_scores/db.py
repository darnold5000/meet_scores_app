from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine, text


@lru_cache(maxsize=1)
def engine():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=3)


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    with engine().connect() as conn:
        res = conn.execute(text(sql), params or {})
        cols = list(res.keys())
        return [dict(zip(cols, row)) for row in res.fetchall()]


def fetch_one(sql: str, params: dict | None = None) -> dict | None:
    rows = fetch_all(sql, params=params)
    return rows[0] if rows else None

