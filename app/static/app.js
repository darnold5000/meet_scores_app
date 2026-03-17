(function () {
  async function registerSW() {
    if (!("serviceWorker" in navigator)) return;
    try {
      await navigator.serviceWorker.register("/sw.js");
    } catch (_) {}
  }

  function fmtScore(x) {
    if (x === null || x === undefined) return "—";
    const n = Number(x);
    if (Number.isNaN(n)) return "—";
    return n.toFixed(3);
  }

  function fmtPlace(p) {
    if (p === null || p === undefined) return "";
    const n = Number(p);
    if (!Number.isFinite(n) || n <= 0) return "";
    return "#" + String(Math.trunc(n));
  }

  function rowHtml(r) {
    const tagParts = [];
    if (r.session) tagParts.push(r.session);
    if (r.level) tagParts.push(r.level);
    if (r.division) tagParts.push(r.division);
    const tag = tagParts.length ? `<span class="tag">${tagParts.join(" · ")}</span>` : "";
    const aaScore = fmtScore(r.aa?.score);
    const aaPlace = fmtPlace(r.aa?.place);
    const place = aaPlace ? `<span class="place">${aaPlace}</span>` : "";
    return `
      <article class="row">
        <div class="row-top">
          <div class="who">
            <div class="athlete" title="${escapeHtml(r.athlete)}">${escapeHtml(r.athlete)}</div>
            <div class="gym" title="${escapeHtml(r.gym)}">${escapeHtml(r.gym)}</div>
          </div>
          <div class="meta2">
            ${tag}
            <div class="aa">${place}<span>${aaScore}</span></div>
          </div>
        </div>
        <div class="grid">
          ${evHtml("VT", r.vt)}
          ${evHtml("UB", r.ub)}
          ${evHtml("BB", r.bb)}
          ${evHtml("FX", r.fx)}
        </div>
      </article>
    `;
  }

  function evHtml(label, ev) {
    const score = fmtScore(ev?.score);
    const place = fmtPlace(ev?.place);
    const pl = place ? `<div class="pl">${place}</div>` : `<div class="pl">&nbsp;</div>`;
    return `
      <div class="ev">
        <div class="lab">${label}</div>
        <div class="val">${score}</div>
        ${pl}
      </div>
    `;
  }

  function escapeHtml(s) {
    return String(s || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function renderList(rows) {
    const list = document.getElementById("scoreList");
    if (!list) return;
    if (!rows || !rows.length) {
      list.innerHTML = `<div class="card"><div class="muted">No scores match these filters yet.</div></div>`;
      return;
    }
    list.innerHTML = rows.map(rowHtml).join("");
  }

  function qs() {
    const session = document.getElementById("sessionSel")?.value || "All";
    const level = document.getElementById("levelSel")?.value || "All";
    const division = document.getElementById("divisionSel")?.value || "All";
    const q = document.getElementById("qInput")?.value || "";
    const p = new URLSearchParams();
    p.set("session", session);
    p.set("level", level);
    p.set("division", division);
    if (q.trim()) p.set("q", q.trim());
    return p.toString();
  }

  async function refreshOnce() {
    const meetKey = window.__MEET_KEY__;
    if (!meetKey) return;
    const status = document.getElementById("statusText");
    const count = document.getElementById("countText");
    try {
      if (status) status.textContent = "Updating…";
      const res = await fetch(`/api/meet/${encodeURIComponent(meetKey)}/scores?` + qs(), {
        headers: { "accept": "application/json" },
      });
      const data = await res.json();
      renderList(data.rows || []);
      if (count) count.textContent = `${data.count || 0} rows`;
      if (status) {
        if (data.latest?.run_id) status.textContent = `Last scrape run #${data.latest.run_id}`;
        else status.textContent = "No local data yet";
      }
    } catch (e) {
      if (status) status.textContent = "Update failed (server offline?)";
    }
  }

  function debounce(fn, ms) {
    let t = null;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms);
    };
  }

  async function initMeetPage() {
    const meetKey = window.__MEET_KEY__;
    if (!meetKey) return;

    renderList(window.__INITIAL_DATA__ || []);
    const count = document.getElementById("countText");
    if (count) count.textContent = `${(window.__INITIAL_DATA__ || []).length} rows`;

    const debouncedRefresh = debounce(refreshOnce, 250);
    ["sessionSel", "levelSel", "divisionSel"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("change", () => refreshOnce());
    });
    const q = document.getElementById("qInput");
    if (q) q.addEventListener("input", () => debouncedRefresh());

    const btn = document.getElementById("refreshBtn");
    if (btn) btn.addEventListener("click", () => refreshOnce());

    const auto = document.getElementById("autoToggle");
    let timer = null;
    function setTimer() {
      if (timer) clearInterval(timer);
      timer = null;
      if (auto && auto.checked) {
        timer = setInterval(refreshOnce, 20000);
      }
    }
    if (auto) auto.addEventListener("change", setTimer);
    setTimer();
  }

  registerSW();
  initMeetPage();
})();

