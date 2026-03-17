from __future__ import annotations

import os
from datetime import datetime

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from gym_scores.db import fetch_all, fetch_one


MEET_KEY = os.getenv("GYM_SCORES_MEET_KEY", "MSO-36478")


def _get_db_url() -> str:
    # Streamlit Cloud: prefer secrets, then env var
    if "DATABASE_URL" in st.secrets:
        return str(st.secrets["DATABASE_URL"])
    return os.getenv("DATABASE_URL", "")


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


def _load_cards(meet_id: int, *, level: str, division: str, q: str, limit: int = 400) -> list[dict]:
    where = ["s.meet_id = :meet_id", "s.event IN ('AA','VT','UB','BB','FX')"]
    params: dict = {"meet_id": meet_id, "limit": max(limit * 8, 5000)}
    if level != "All":
        where.append("s.level = :level")
        params["level"] = level
    if division != "All":
        where.append("s.division = :division")
        params["division"] = division
    if q.strip():
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

    by_key: dict[tuple, dict] = {}
    for r in rows:
        key = (r["athlete_id"], r.get("level") or "", r.get("division") or "")
        if key not in by_key:
            by_key[key] = {
                "athlete": r["athlete"],
                "gym": r["gym"],
                "level": r.get("level") or "",
                "division": r.get("division") or "",
                "AA": {"score": None, "place": None},
                "VT": {"score": None, "place": None},
                "UB": {"score": None, "place": None},
                "BB": {"score": None, "place": None},
                "FX": {"score": None, "place": None},
            }
        ev = str(r.get("event") or "").upper()
        if ev not in {"AA", "VT", "UB", "BB", "FX"}:
            continue
        score = float(r["score"]) if r.get("score") is not None else None
        place = int(r["place"]) if r.get("place") is not None else None
        cur = by_key[key][ev]
        if cur["score"] is None or (score is not None and score > cur["score"]):
            cur["score"] = score
            cur["place"] = place

    out = list(by_key.values())
    out.sort(key=lambda x: (x["AA"]["score"] is None, -(x["AA"]["score"] or 0.0), x["athlete"]))
    return out[:limit]


def _fmt_score(x) -> str:
    return "—" if x is None else f"{x:.3f}"


def _fmt_place(p) -> str:
    return "" if p is None else f"#{p}"


st.set_page_config(page_title="Gym Scores", layout="wide")

db_url = _get_db_url()
if not db_url:
    st.error("DATABASE_URL is not set. Add it in Streamlit Secrets as `DATABASE_URL`.")
    st.stop()

st.title("Gym Scores")
st.caption(f"Meet: `{MEET_KEY}` · updated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

meet = _get_meet(MEET_KEY)
if not meet:
    st.error(f"Meet `{MEET_KEY}` not found in the database.")
    st.stop()

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    q = st.text_input("Search athlete or gym", value="")
with col2:
    levels = ["All"] + _list_distinct(int(meet["id"]), "level")
    level = st.selectbox("Level", levels, index=0)
with col3:
    divisions = ["All"] + _list_distinct(int(meet["id"]), "division")
    division = st.selectbox("Division", divisions, index=0)

auto = st.checkbox("Auto-refresh (20s)", value=True)
if auto:
    st_autorefresh(interval=20_000, key="auto_refresh_20s")

cards = _load_cards(int(meet["id"]), level=level, division=division, q=q, limit=300)
st.caption(f"{len(cards)} athletes")

for c in cards:
    aa = c["AA"]
    with st.container():
        top = st.columns([3, 1])
        with top[0]:
            st.markdown(f"**{c['athlete']}**  \n{c['gym']}  \n`{c['level']}` · `{c['division']}`")
        with top[1]:
            st.markdown(f"**AA {_fmt_score(aa['score'])}**  \n{_fmt_place(aa['place'])}")
        g = st.columns(4)
        for i, ev in enumerate(["VT", "UB", "BB", "FX"]):
            e = c[ev]
            g[i].markdown(f"**{ev}**  \n{_fmt_score(e['score'])} { _fmt_place(e['place']) }")

