from __future__ import annotations

import os
from datetime import datetime
from textwrap import dedent

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from gym_scores.db import fetch_all, fetch_one


MEET_KEY = os.getenv("GYM_SCORES_MEET_KEY", "MSO-36478")
EVENTS = ["VT", "UB", "BB", "FX", "AA"]


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


st.set_page_config(page_title="Gym Scores", layout="centered")

st.markdown(
    """
<style>
  :root{
    --bg: #f4f6f9;
    --card: #ffffff;
    --text: #0f172a;
    --muted: #64748b;
    --brand: #0b2a4a; /* navy */
    --accent: #e11d2e; /* red */
    --border: rgba(15, 23, 42, 0.08);
    --shadow: 0 10px 24px rgba(2,6,23,0.10);
    --radius: 16px;
  }

  /* tighten Streamlit chrome */
  header[data-testid="stHeader"] { display: none; }
  footer { display: none; }
  #MainMenu { visibility: hidden; }

  /* mobile-ish centered content */
  .block-container{
    padding-top: 0.75rem;
    padding-bottom: 5.5rem; /* room above Streamlit watermark / mobile browser bars */
    max-width: 460px;
  }

  html, body, [data-testid="stAppViewContainer"]{
    background: var(--bg);
  }

  /* Title/header bar */
  .gs-header{
    background: linear-gradient(180deg, rgba(11,42,74,1) 0%, rgba(11,42,74,0.95) 100%);
    color: white;
    border-radius: var(--radius);
    padding: 14px 16px;
    box-shadow: var(--shadow);
    margin-bottom: 14px;
  }
  .gs-header-top{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap: 10px;
  }
  .gs-brand{
    display:flex;
    align-items:center;
    gap: 10px;
    font-weight: 800;
    letter-spacing: 0.6px;
  }
  .gs-dot{
    width: 10px;
    height: 10px;
    border-radius: 999px;
    background: var(--accent);
    box-shadow: 0 0 0 4px rgba(225,29,46,0.18);
  }
  .gs-sub{
    margin-top: 6px;
    color: rgba(255,255,255,0.85);
    font-size: 0.88rem;
    line-height: 1.2rem;
  }

  /* Controls row */
  .gs-controls{
    background: rgba(255,255,255,0.14);
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 14px;
    padding: 10px;
    margin-top: 10px;
  }

  /* Streamlit input styling */
  [data-testid="stTextInput"] input{
    border-radius: 999px !important;
    border: 1px solid var(--border) !important;
    padding: 12px 14px !important;
  }
  [data-testid="stSelectbox"] > div{
    border-radius: 999px !important;
  }

  /* Radio -> pills */
  div[role="radiogroup"]{
    display:flex;
    gap: 10px;
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 4px;
  }
  div[role="radiogroup"] > label{
    margin-right: 0 !important;
  }
  div[role="radiogroup"] input{ display:none; }
  div[role="radiogroup"] span{
    display:inline-block;
    padding: 7px 14px;
    border-radius: 999px;
    border: 1px solid rgba(255,255,255,0.30);
    background: rgba(255,255,255,0.08);
    color: white;
    font-weight: 700;
    font-size: 0.9rem;
    white-space: nowrap;
  }
  div[role="radiogroup"] label:has(input:checked) span{
    background: var(--accent);
    border-color: rgba(225,29,46,0.85);
    box-shadow: 0 10px 20px rgba(225,29,46,0.20);
  }

  /* Athlete cards */
  .gs-card{
    background: var(--card);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    box-shadow: 0 12px 30px rgba(2,6,23,0.06);
    padding: 10px 10px 8px 10px;
    margin: 8px 0;
  }
  .gs-card-top{
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap: 10px;
  }
  .gs-ident{
    display:flex;
    align-items:flex-start;
    gap: 10px;
    min-width: 0;
  }
  .gs-rank{
    width: 24px;
    height: 24px;
    border-radius: 999px;
    background: var(--accent);
    color: white;
    display:flex;
    align-items:center;
    justify-content:center;
    font-weight: 900;
    font-size: 0.78rem;
    flex: 0 0 auto;
  }
  .gs-name{
    font-weight: 900;
    color: var(--text);
    line-height: 1.1rem;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .gs-gym{
    color: var(--accent);
    font-weight: 800;
    font-size: 0.85rem;
    margin-top: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .gs-meta{
    display:flex;
    gap: 8px;
    margin-top: 5px;
    flex-wrap: wrap;
  }
  .gs-chip{
    font-size: 0.78rem;
    color: var(--muted);
    background: rgba(148,163,184,0.18);
    border: 1px solid rgba(148,163,184,0.22);
    border-radius: 999px;
    padding: 4px 10px;
    font-weight: 700;
  }
  .gs-total{
    text-align:right;
    flex: 0 0 auto;
  }
  .gs-total-score{
    font-weight: 950;
    font-size: 1.0rem;
    color: var(--text);
    line-height: 1.0rem;
  }
  .gs-total-place{
    color: var(--muted);
    font-weight: 700;
    font-size: 0.82rem;
    margin-top: 4px;
  }
  .gs-scores{
    display:flex;
    gap: 8px;
    margin-top: 8px;
    justify-content:space-between;
  }
  .gs-pill{
    flex: 1 1 0;
    border-radius: 14px;
    border: 1px solid var(--border);
    background: rgba(2,6,23,0.02);
    padding: 7px 6px;
    text-align:center;
    min-width: 0;
  }
  .gs-pill.sel{
    border-color: rgba(225,29,46,0.55);
    background: rgba(225,29,46,0.08);
  }
  .gs-pill-ev{
    font-weight: 900;
    font-size: 0.78rem;
    color: var(--muted);
    letter-spacing: 0.4px;
  }
  .gs-pill-score{
    font-weight: 950;
    color: var(--text);
    margin-top: 2px;
    font-size: 0.92rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .gs-pill-place{
    font-weight: 800;
    color: var(--muted);
    font-size: 0.78rem;
    margin-top: 2px;
  }

  /* Small caption */
  .gs-caption{
    color: var(--muted);
    font-weight: 700;
    font-size: 0.88rem;
    margin: 2px 0 8px 0;
  }

  /* List/table view (HTML, no Arrow) */
  .gs-list{
    display:flex;
    flex-direction: column;
    gap: 8px;
  }
  .gs-row{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 10px 24px rgba(2,6,23,0.06);
    padding: 10px 10px;
  }
  .gs-row-top{
    display:flex;
    align-items:flex-start;
    justify-content: space-between;
    gap: 10px;
  }
  .gs-row-left{
    display:flex;
    align-items:flex-start;
    gap: 10px;
    min-width: 0;
  }
  .gs-rank-s{
    width: 24px;
    height: 24px;
    border-radius: 999px;
    background: rgba(225,29,46,0.14);
    border: 1px solid rgba(225,29,46,0.35);
    color: var(--accent);
    display:flex;
    align-items:center;
    justify-content:center;
    font-weight: 950;
    font-size: 0.78rem;
    flex: 0 0 auto;
  }
  .gs-row-name{
    font-weight: 950;
    color: var(--text);
    line-height: 1.05rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 260px;
  }
  .gs-row-gym{
    color: var(--accent);
    font-weight: 850;
    font-size: 0.85rem;
    margin-top: 3px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 260px;
  }
  .gs-row-meta{
    display:flex;
    gap: 8px;
    margin-top: 6px;
    flex-wrap: wrap;
  }
  .gs-row-right{
    text-align:right;
    flex: 0 0 auto;
  }
  .gs-row-score{
    font-weight: 950;
    color: var(--text);
    font-size: 1.0rem;
    line-height: 1.0rem;
    font-variant-numeric: tabular-nums;
  }
  .gs-row-place{
    color: var(--muted);
    font-weight: 800;
    font-size: 0.82rem;
    margin-top: 4px;
  }
  .gs-row-events{
    display:flex;
    gap: 8px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .gs-evchip{
    border-radius: 999px;
    border: 1px solid rgba(148,163,184,0.22);
    background: rgba(148,163,184,0.12);
    padding: 5px 10px;
    font-weight: 850;
    font-size: 0.82rem;
    color: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .gs-evchip strong{ color: var(--muted); font-weight: 900; margin-right: 6px; }
</style>
""",
    unsafe_allow_html=True,
)

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

st.markdown(
    f"""
<div class="gs-header">
  <div class="gs-header-top">
    <div class="gs-brand"><span class="gs-dot"></span><span>GYM SCORES</span></div>
    <div style="opacity:0.9;font-weight:800;">LIVE</div>
  </div>
  <div class="gs-sub">
    <div style="font-weight:900;font-size:1.05rem;line-height:1.2rem;">{meet.get('name','')}</div>
    <div>{meet.get('location','')}{(', ' + meet.get('state','')) if meet.get('state') else ''}</div>
  </div>
  <div class="gs-controls">
""",
    unsafe_allow_html=True,
)

q = st.text_input("Search athletes or gyms", value="", label_visibility="collapsed", placeholder="Search athletes or gyms…")

levels = ["All"] + _list_distinct(int(meet["id"]), "level")
divisions = ["All"] + _list_distinct(int(meet["id"]), "division")
f1, f2 = st.columns(2)
with f1:
    level = st.selectbox("Level", levels, index=0)
with f2:
    division = st.selectbox("Division", divisions, index=0)

event = st.radio("Event", EVENTS, index=EVENTS.index("AA"), horizontal=True, label_visibility="collapsed")

view = st.radio("View", ["Cards", "List"], index=0, horizontal=True, label_visibility="collapsed")

st.markdown("</div></div>", unsafe_allow_html=True)

auto = st.checkbox("Auto-refresh (20s)", value=True)
if auto:
    st_autorefresh(interval=20_000, key="auto_refresh_20s")

cards = _load_cards(int(meet["id"]), level=level, division=division, q=q, limit=300)
st.markdown(f'<div class="gs-caption">{len(cards)} athletes</div>', unsafe_allow_html=True)

def _event_sort_key(c: dict) -> tuple:
    e = c[event]
    score = e.get("score")
    return (score is None, -(score or 0.0), c["athlete"])

cards_sorted = sorted(cards, key=_event_sort_key)

if view == "List":
    # Render as HTML to avoid Arrow serialization issues on some Streamlit Cloud frontends.
    def _cell(text: str) -> str:
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    show_all = st.toggle("Show all events", value=False)

    html = '<div class="gs-list">'
    for idx, c in enumerate(cards_sorted, start=1):
        e_sel = c[event]
        score = _fmt_score(e_sel.get("score"))
        place = _fmt_place(e_sel.get("place"))
        html += '<div class="gs-row"><div class="gs-row-top">'
        html += '<div class="gs-row-left">'
        html += f'<div class="gs-rank-s">{idx}</div>'
        html += '<div style="min-width:0;">'
        html += f'<div class="gs-row-name">{_cell(c["athlete"])}</div>'
        html += f'<div class="gs-row-gym">{_cell(c["gym"])}</div>'
        html += '<div class="gs-row-meta">'
        html += f'<span class="gs-chip">{_cell(c["level"] or "—")}</span>'
        html += f'<span class="gs-chip">{_cell(c["division"] or "—")}</span>'
        html += "</div></div></div>"
        html += '<div class="gs-row-right">'
        html += f'<div class="gs-row-score">{event} {_cell(score)}</div>'
        html += f'<div class="gs-row-place">{_cell(place)}</div>'
        html += "</div></div>"

        if show_all:
            html += '<div class="gs-row-events">'
            for ev in EVENTS:
                e = c[ev]
                s = _fmt_score(e.get("score"))
                p = _fmt_place(e.get("place"))
                val = f"{s} {p}".strip()
                html += f'<span class="gs-evchip"><strong>{ev}</strong>{_cell(val)}</span>'
            html += "</div>"

        html += "</div>"
    html += "</div>"

    st.markdown(html, unsafe_allow_html=True)
else:
    for idx, c in enumerate(cards_sorted, start=1):
        e_sel = c[event]
        html = f"""
<div class="gs-card">
  <div class="gs-card-top">
    <div class="gs-ident">
      <div class="gs-rank">{idx}</div>
      <div style="min-width:0;">
        <div class="gs-name">{c["athlete"]}</div>
        <div class="gs-gym">{c["gym"]}</div>
        <div class="gs-meta">
          <span class="gs-chip">{c["level"] or "—"}</span>
          <span class="gs-chip">{c["division"] or "—"}</span>
        </div>
      </div>
    </div>
    <div class="gs-total">
      <div class="gs-total-score">{event} {_fmt_score(e_sel.get("score"))}</div>
      <div class="gs-total-place">{_fmt_place(e_sel.get("place"))}</div>
    </div>
  </div>
  <div class="gs-scores">
"""
        for ev in EVENTS:
            e = c[ev]
            sel = " sel" if ev == event else ""
            html += f"""
<div class="gs-pill{sel}">
  <div class="gs-pill-ev">{ev}</div>
  <div class="gs-pill-score">{_fmt_score(e.get("score"))}</div>
  <div class="gs-pill-place">{_fmt_place(e.get("place"))}</div>
</div>
"""
        html += """
  </div>
</div>
"""
        st.markdown(dedent(html).strip(), unsafe_allow_html=True)

