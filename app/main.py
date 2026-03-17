from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Query, Request
from fastapi import HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

PROJECT_DIR = Path(__file__).resolve().parents[1]
# Ensure `gym_scores/` is importable in environments that don't add the repo root
# to PYTHONPATH (e.g. Streamlit Community Cloud running this as an ASGI app).
sys.path.insert(0, str(PROJECT_DIR))

from gym_scores.db import fetch_all, fetch_one  # noqa: E402
# One-meet MVP (easy to extend later). This is the `meets.meet_id` value in the `06` DB.
DEFAULT_MEET_KEY = os.getenv("GYM_SCORES_MEET_KEY", "MSO-36478")


app = FastAPI(title="Gym Scores")

static_dir = PROJECT_DIR / "app" / "static"
templates = Jinja2Templates(directory=str(PROJECT_DIR / "app" / "templates"))
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    try:
        meet = _get_meet(DEFAULT_MEET_KEY)
    except RuntimeError as exc:
        return HTMLResponse(f"Database not configured: {exc}", status_code=503)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "meet_key": DEFAULT_MEET_KEY,
            "latest": None,
            "meet": meet,
        },
    )


@app.get("/meet/{meet_key}", response_class=HTMLResponse)
def meet_view(
    request: Request,
    meet_key: str,
    level: str = Query("All"),
    division: str = Query("All"),
    q: str = Query(""),
):
    try:
        meet = _get_meet(meet_key)
    except RuntimeError as exc:
        return HTMLResponse(f"Database not configured: {exc}", status_code=503)
    if not meet:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "meet_key": meet_key, "latest": None, "meet": None},
            status_code=404,
        )

    levels = ["All"] + _list_distinct(meet_id=int(meet["id"]), column="level")
    divisions = ["All"] + _list_distinct(meet_id=int(meet["id"]), column="division")

    data = _load_meet_rows(meet_id=int(meet["id"]), level=level, division=division, q=q, limit=800)
    return templates.TemplateResponse(
        "meet.html",
        {
            "request": request,
            "meet_key": meet_key,
            "levels": levels,
            "divisions": divisions,
            "sessions": ["All"],  # sessions aren't persisted in `scores` yet
            "selected": {"session": "All", "level": level, "division": division, "q": q},
            "initial_data": data,
        },
    )


@app.get("/api/meet/{meet_key}/scores", response_class=JSONResponse)
def api_scores(
    meet_key: str,
    level: str = Query("All"),
    division: str = Query("All"),
    q: str = Query(""),
    limit: int = Query(500, ge=1, le=2000),
):
    try:
        meet = _get_meet(meet_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Database not configured: {exc}") from exc
    if not meet:
        return JSONResponse({"error": "meet_not_found", "meet_key": meet_key}, status_code=404)
    rows = _load_meet_rows(meet_id=int(meet["id"]), level=level, division=division, q=q, limit=limit)
    return {
        "meet_key": meet_key,
        "latest": None,
        "count": len(rows),
        "rows": rows,
    }


@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse(
        {
            "name": "Gym Scores",
            "short_name": "GymScores",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#0f1d3a",
            "theme_color": "#0f1d3a",
            "icons": [
                {"src": "/static/icons/icon.svg", "sizes": "any", "type": "image/svg+xml"},
            ],
        }
    )


@app.get("/sw.js")
def service_worker():
    # served from root for PWA scope
    sw_path = static_dir / "sw.js"
    return HTMLResponse(sw_path.read_text(encoding="utf-8"), media_type="application/javascript")


def _get_meet(meet_key: str) -> dict | None:
    return fetch_one(
        """
        SELECT id, meet_id, name, location, state, start_date, end_date, mso_url
        FROM meets
        WHERE meet_id = :meet_id
        """,
        {"meet_id": meet_key},
    )


def _list_distinct(meet_id: int, column: str) -> list[str]:
    if column not in {"level", "division"}:
        raise ValueError("unsupported column")
    rows = fetch_all(
        f"""
        SELECT DISTINCT {column} AS v
        FROM scores
        WHERE meet_id = :meet_id AND {column} IS NOT NULL AND TRIM({column}) != ''
        ORDER BY v
        """,
        {"meet_id": meet_id},
    )
    return [str(r["v"]) for r in rows if r.get("v")]


def _load_meet_rows(meet_id: int, *, level: str, division: str, q: str, limit: int) -> list[dict[str, Any]]:
    where = ["s.meet_id = :meet_id", "s.event IN ('AA','VT','UB','BB','FX')"]
    # `limit` is the number of athlete cards. Fetch more underlying score rows so we
    # can assemble complete VT/UB/BB/FX cards even when limit is small.
    raw_limit = max(int(limit) * 8, 5000)
    params: dict[str, Any] = {"meet_id": meet_id, "limit": raw_limit}
    if level and level != "All":
        where.append("s.level = :level")
        params["level"] = level
    if division and division != "All":
        where.append("s.division = :division")
        params["division"] = division
    if q and q.strip():
        where.append("(LOWER(a.canonical_name) LIKE :q OR LOWER(g.canonical_name) LIKE :q)")
        params["q"] = f"%{q.strip().lower()}%"

    rows = fetch_all(
        f"""
        SELECT
          a.id AS athlete_id,
          a.canonical_name AS athlete,
          COALESCE(g.canonical_name, '') AS gym,
          s.level AS level,
          s.division AS division,
          s.event AS event,
          s.score AS score,
          s.place AS place
        FROM scores s
        JOIN athletes a ON a.id = s.athlete_id
        LEFT JOIN gyms g ON g.id = a.gym_id
        WHERE {' AND '.join(where)}
        ORDER BY s.score DESC
        LIMIT :limit
        """,
        params,
    )

    # Pivot into the mobile card shape (one row per athlete+level+division)
    by_key: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        key = (r["athlete_id"], r.get("level") or "", r.get("division") or "")
        if key not in by_key:
            by_key[key] = {
                "athlete": r["athlete"],
                "gym": r["gym"],
                "session": "",
                "level": r.get("level") or "",
                "division": r.get("division") or "",
                "aa": {"score": None, "place": None},
                "vt": {"score": None, "place": None},
                "ub": {"score": None, "place": None},
                "bb": {"score": None, "place": None},
                "fx": {"score": None, "place": None},
            }

        ev = str(r["event"] or "").upper()
        target = None
        if ev == "AA":
            target = "aa"
        elif ev == "VT":
            target = "vt"
        elif ev == "UB":
            target = "ub"
        elif ev == "BB":
            target = "bb"
        elif ev == "FX":
            target = "fx"
        if not target:
            continue

        cur = by_key[key][target]
        score = float(r["score"]) if r["score"] is not None else None
        place = int(r["place"]) if r.get("place") is not None else None

        # Keep best score per event (and its place)
        if cur["score"] is None or (score is not None and score > cur["score"]):
            cur["score"] = score
            cur["place"] = place

    out = list(by_key.values())
    out.sort(key=lambda x: (x["aa"]["score"] is None, -(x["aa"]["score"] or 0.0), x["athlete"]))
    return out[: int(limit)]

