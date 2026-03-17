"""
MeetScoresOnline (MSO) Scraper — Playwright-based

Copied/adapted from `projects/06_usag_meet_tracker/agents/mso_scraper.py`.

MSO loads scores via JavaScript after page load.
Playwright runs a real browser, dismisses the paywall overlay, iterates
session tabs / dropdown items, and parses the fully rendered score tables.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Dict, List, Optional


logger = logging.getLogger(__name__)

MSO_BASE = "https://www.meetscoresonline.com"
PAGE_LOAD_TIMEOUT = 20000


DISMISS_OVERLAY_JS = """
    ['showmessage_overlay', 'showmessage', 'IGCOfferModal'].forEach(id => {
        var el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    document.querySelectorAll(
        '.modal-backdrop, .modal.show, [id*="overlay"], [id*="modal"]'
    ).forEach(e => e.style.display = 'none');
    document.body.style.overflow = 'auto';
"""


def scrape_mso_meet(mso_url: str) -> List[Dict]:
    """
    Scrape all result rows from a MSO meet page using Playwright.
    Returns unique rows by `record_hash`.
    """
    logger.info("Scraping MSO meet: %s", mso_url)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright not installed.")
        return []

    rows: List[Dict] = []
    meet_key = _extract_meet_key_from_url(mso_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )

        result_urls = _resolve_result_urls(context, mso_url)
        if not result_urls:
            result_urls = [mso_url]

        for result_url in result_urls:
            page_rows = _scrape_result_page(context, result_url, meet_key)
            rows.extend(page_rows)
            logger.info("  %s → %d rows scraped", result_url, len(page_rows))

        browser.close()

    unique = deduplicate_rows(rows)
    logger.info("MSO scraped %d rows → %d unique rows", len(rows), len(unique))
    return unique


def make_record_hash(row: dict) -> str:
    key = (
        str(row.get("athlete_name", "")).strip().lower()
        + "|" + str(row.get("meet_id", ""))
        + "|" + str(row.get("session", ""))
        + "|" + str(row.get("division", ""))
        + "|" + str(row.get("level", ""))
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def deduplicate_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    out: list[dict] = []
    for r in rows:
        h = r.get("record_hash") or make_record_hash(r)
        r["record_hash"] = h
        if h in seen:
            continue
        seen.add(h)
        out.append(r)
    return out


def _dismiss_overlay(page) -> None:
    try:
        page.evaluate(DISMISS_OVERLAY_JS)
        page.wait_for_timeout(400)
    except Exception:
        pass


def _resolve_result_urls(context, slug_url: str) -> List[str]:
    if "/Results/" in slug_url:
        return []
    try:
        page = context.new_page()
        page.goto(slug_url, timeout=PAGE_LOAD_TIMEOUT, wait_until="domcontentloaded")
        _dismiss_overlay(page)

        links = page.eval_on_selector_all(
            "a[href*='/Results/']",
            "els => els.map(e => e.href)",
        )
        page.close()

        seen = set()
        result_urls: list[str] = []
        for link in links:
            m = re.search(r"/Results/(\d+)", link)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                result_urls.append(f"{MSO_BASE}/Results/{m.group(1)}")
        return result_urls
    except Exception as exc:
        logger.warning("Could not resolve result URLs from %s: %s", slug_url, exc)
        return []


def _scrape_result_page(context, result_url: str, meet_key: str) -> List[Dict]:
    rows: list[dict] = []
    seen_keys = set()

    def collect_rows(pg):
        from bs4 import BeautifulSoup

        html = pg.content()
        soup = BeautifulSoup(html, "lxml")
        found = []
        for table in soup.select("table"):
            for row in _parse_result_table(table, meet_key):
                key = f"{row.get('athlete_name')}|{row.get('level')}|{row.get('division')}|{row.get('session')}"
                if key not in seen_keys and row.get("athlete_name"):
                    seen_keys.add(key)
                    found.append(row)
        return found

    try:
        page = context.new_page()
        page.goto(result_url, timeout=PAGE_LOAD_TIMEOUT, wait_until="networkidle")
        _dismiss_overlay(page)

        try:
            page.wait_for_function(
                "() => !document.body.innerText.includes('#{fullname}')",
                timeout=PAGE_LOAD_TIMEOUT,
            )
        except Exception:
            pass

        combined_rows = []
        try:
            _dismiss_overlay(page)
            page.click("a.session.btn", timeout=5000)
            page.wait_for_timeout(800)
            page.click('.session-picker-item:has-text("Combined")', timeout=5000)
            page.wait_for_timeout(3000)
            _dismiss_overlay(page)
            combined_rows = collect_rows(page)
        except Exception:
            pass
        rows.extend(combined_rows)

        session_tabs = []
        try:
            all_links = page.query_selector_all('a, [role="tab"], .nav-link, [class*="session"]')
            for el in all_links:
                try:
                    cls = el.get_attribute("class") or ""
                    if "session" in cls and "btn" in cls:
                        continue
                    text = (el.inner_text() or "").strip()
                    if re.search(r"Session\s*0?\d+\s*\(\d+\)", text, re.IGNORECASE):
                        session_tabs.append(el)
                except Exception:
                    pass
        except Exception:
            pass

        if session_tabs and len(combined_rows) < 30:
            for tab in session_tabs:
                try:
                    _dismiss_overlay(page)
                    tab.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    _dismiss_overlay(page)
                    rows.extend(collect_rows(page))
                except Exception:
                    continue

        if len(rows) < 30:
            try:
                _dismiss_overlay(page)
                page.click("a.session.btn", timeout=5000)
                page.wait_for_timeout(1500)
                picker_items = page.query_selector_all(".session-picker-item")
                item_texts = []
                for item in picker_items:
                    try:
                        item_texts.append((item.inner_text() or "").strip())
                    except Exception:
                        item_texts.append("")

                for i, text in enumerate(item_texts):
                    if "combined" in text.lower():
                        continue
                    try:
                        _dismiss_overlay(page)
                        page.click("a.session.btn", timeout=5000)
                        page.wait_for_timeout(800)
                        fresh_items = page.query_selector_all(".session-picker-item")
                        if i >= len(fresh_items):
                            continue
                        target = fresh_items[i]
                        _dismiss_overlay(page)
                        try:
                            target.click(timeout=5000)
                        except Exception:
                            _dismiss_overlay(page)
                            page.evaluate("el => el.click()", target)
                        page.wait_for_timeout(3000)
                        _dismiss_overlay(page)
                        rows.extend(collect_rows(page))
                    except Exception:
                        continue
            except Exception:
                pass

        page.close()
    except Exception as exc:
        logger.error("Playwright failed on %s: %s", result_url, exc)

    return rows


def _parse_result_table(table, meet_key: str) -> List[Dict]:
    rows: list[dict] = []
    headers: list[str] = []

    for tr in table.select("tr"):
        if tr.select("th"):
            cells = [td.get_text(strip=True) for td in tr.select("th, td")]
            headers = [_normalize_header(c) for c in cells]
            continue

        cells_text = [td.get_text(strip=True) for td in tr.select("td")]
        if any("#{" in c for c in cells_text):
            continue
        if not headers:
            continue
        td_elements = tr.select("td")
        if not td_elements:
            continue

        row_dict = dict(zip(headers, cells_text))

        # places via HTML class / span
        for td in td_elements:
            classes = td.get("class", [])
            class_str = " ".join(classes) if classes else ""

            place_value = None
            m1 = re.search(r"place-(\d+)", class_str)
            if m1:
                place_value = int(m1.group(1))
            place_span = td.select_one("span.small.place, span.small-place, .small.place")
            if place_span:
                txt = place_span.get_text(strip=True)
                m2 = re.match(r"(\d+)", txt)
                if m2:
                    place_value = int(m2.group(1))

            event_match = re.search(r"event-(\d+|AA)", class_str)
            if event_match:
                event_code = event_match.group(1)
                event_map = {"1": "vault", "2": "bars", "3": "beam", "4": "floor", "AA": "aa"}
                field_name = event_map.get(event_code)
                if field_name == "aa":
                    row_dict["AAPlace"] = place_value
                elif field_name:
                    row_dict[f"{field_name}_place"] = place_value

        parsed = _extract_score_row(row_dict, meet_key)
        if parsed:
            rows.extend(parsed)

    return rows


def _extract_score_row(row: Dict, meet_key: str) -> List[Dict]:
    athlete = (row.get("athlete") or row.get("gymnast") or row.get("name") or row.get("athlete_name") or "").strip()
    gym = (row.get("gym") or row.get("club") or row.get("team") or "").strip()
    if not athlete or not gym or len(athlete) < 3 or athlete.lower() in ("totals", "total", "team"):
        return []

    vault = _decode_mso_score(row.get("vault", ""))
    bars = _decode_mso_score(row.get("bars", "") or row.get("uneven_bars", ""))
    beam = _decode_mso_score(row.get("beam", ""))
    floor = _decode_mso_score(row.get("floor", "") or row.get("floor_exercise", ""))
    aa_score = round(sum([s for s in [vault, bars, beam, floor] if s is not None]), 3)

    level_raw = row.get("lvl") or row.get("level") or ""
    div_raw = row.get("div") or row.get("division") or ""
    sess_raw = row.get("sess") or row.get("session") or ""

    aa_place = _normalize_place(row.get("AAPlace") or row.get("aa_place") or row.get("place"))
    vault_place = _normalize_place(row.get("vault_place") or row.get("VTPlace") or row.get("vt_place"))
    bars_place = _normalize_place(row.get("bars_place") or row.get("UBPlace") or row.get("ub_place"))
    beam_place = _normalize_place(row.get("beam_place") or row.get("BBPlace") or row.get("bb_place"))
    floor_place = _normalize_place(row.get("floor_place") or row.get("FXPlace") or row.get("fx_place"))

    result_row = {
        "athlete_name": athlete,
        "gym": gym,
        "level": str(level_raw).strip() or None,
        "division": str(div_raw).strip() or None,
        "session": str(sess_raw).strip() or None,
        "score": aa_score,
        "place": aa_place,
        "vault": vault,
        "vault_place": vault_place,
        "bars": bars,
        "bars_place": bars_place,
        "beam": beam,
        "beam_place": beam_place,
        "floor": floor,
        "floor_place": floor_place,
        "meet_id": meet_key,
        "source": "mso",
        "raw_row": row,
    }
    result_row["record_hash"] = make_record_hash(result_row)
    return [result_row]


def _normalize_place(raw_place) -> Optional[int]:
    if raw_place is None:
        return None
    if isinstance(raw_place, int):
        return raw_place
    if not str(raw_place).strip():
        return None
    m = re.match(r"(\d+)", str(raw_place).strip())
    return int(m.group(1)) if m else None


def _decode_mso_score(raw: str) -> Optional[float]:
    if not raw:
        return None
    clean = re.sub(r"[^0-9]", "", str(raw))
    if len(clean) < 4:
        return None
    score_encoded = clean[-4:]
    score_str = score_encoded[-1] + score_encoded[:-1]
    try:
        val = int(score_str) / 1000.0
        if 0.0 <= val <= 10.0:
            return val
        return None
    except ValueError:
        return None


def _normalize_header(header: str) -> str:
    return header.lower().strip().replace(" ", "_").replace("-", "_").replace("#", "place").replace("/", "_")


def _extract_meet_key_from_url(url: str) -> str:
    match = re.search(r"/Results/(\d+)", url)
    if match:
        return f"MSO-{match.group(1)}"
    match = re.search(r"/R(\d+)", url, re.IGNORECASE)
    if match:
        return f"MSO-{match.group(1)}"
    m = re.search(r"meetscoresonline\.com/(.+)$", url)
    return f"MSO-{m.group(1)}" if m else "MSO-UNKNOWN"

