// Try an adjustment + Access by atoll, from precomputed model results (engine-data.js).
(function () {
  "use strict";
  const E = window.MANDARIN_ENGINE;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const n = (x) => Number(x).toLocaleString("en");
  // ---- Try an adjustment + Access by atoll (precomputed model results) ----
  const adj = document.getElementById("engine-adjust");
  const acc = document.getElementById("engine-access");
  if (!E || !adj || !acc) return;
  try {
    const scenarios = (E.scenarios || []).map((s) => (Array.isArray(s) ? s[0] : s)).filter(Boolean);
    const names = (window.MANDARIN_DATA && window.MANDARIN_DATA.atolls) || {};
    const atollName = (c) => names[c] || c;
    const CATS = { hospital: { label: "Hospital", ids: ["hospital_child", "hospital_adult", "hospital_elderly"] },
      referral: { label: "Referral", ids: ["referral"] }, school: { label: "School", ids: ["school"] } };
    const state = { scen: null, cat: "hospital", open: {} };

    function agg(rows, key, val, ids) {
      const r = { total: 0, no_data: 0, on_island: 0, travellers: 0, success: 0 };
      for (const x of rows) if (x[key] === val && ids.includes(x.category))
        for (const k in r) r[k] += x[k] || 0;
      return r;
    }
    const rate = (r) => (r.travellers > 0 ? (100 * r.success) / r.travellers : null);
    const pct = (v) => (v == null ? "—" : `${v.toFixed(v >= 99.95 || v === 0 ? 0 : 1)}%`);

    function row(name, base, cur, small) {
      const r = rate(cur), br = rate(base);
      let val = pct(r), sub;
      if (r == null) {
        val = "—";
        sub = cur.on_island > 0 ? "no ferry trips needed" : cur.no_data > 0 ? "no data" : "no ferry trips needed";
        if (cur.on_island === 0 && cur.no_data > 0) val = "no data";
      } else sub = `${n(cur.success)} of ${n(cur.travellers)} residents who need a ferry trip`;
      let delta = "";
      if (state.scen && r != null && br != null && Math.abs(r - br) >= 0.05) {
        const d = r - br;
        delta = ` <span class="delta ${d > 0 ? "good" : "bad"}">${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} pp</span>`;
      }
      return `<span class="row-name">${esc(name)}</span><span class="row-val">${esc(val)}${delta}</span>
        ${r != null ? `<div class="bar"><i style="width:${Math.max(0, Math.min(100, r)).toFixed(1)}%"></i></div>` : ""}
        <span class="row-sub">${esc(sub)}</span>`;
    }

    function renderAdjust() {
      const chip = (id, label) => `<button type="button" class="chip${(state.scen ? state.scen.id : "") === id ? " sel" : ""}" data-scen="${esc(id)}" aria-pressed="${(state.scen ? state.scen.id : "") === id}">${esc(label)}</button>`;
      let detail = "";
      const s = state.scen;
      if (s) {
        const c = s.compare || {};
        const ns = (c.newly_served || []).reduce((t, x) => t + (x.residents || 0), 0);
        detail = `<p class="issue-why">${esc(s.description)}</p>
          <div class="stats">
            <div class="stat"><b class="good">+${n(c.gained || 0)}</b><span>trips start working</span></div>
            <div class="stat"><b class="badtxt">${n(c.lost || 0)}</b><span>trips stop working</span></div>
            ${ns > 0 ? `<div class="stat"><b class="good">+${n(ns)}</b><span>residents newly served by a new stop</span></div>` : ""}
          </div>
          <p class="status-line">The map and timetable keep today's schedule.</p>`;
      }
      adj.innerHTML = `<div class="eyebrow">What if</div><div class="sec-head"><h2>Try an adjustment</h2></div>
        <div class="chips">${chip("", "Today's timetable")}${scenarios.map((x) => chip(x.id, x.label)).join("")}</div>${detail}`;
      adj.hidden = false;
    }

    function renderAccess() {
      const ids = CATS[state.cat].ids;
      const sc = state.scen ? state.scen.scores : null;
      const bAt = E.baseline.atolls, bIs = E.baseline.islands;
      const order = (E.meta.atolls || []).map((a) => ({ a, b: agg(bAt, "atoll", a, ids) }))
        .sort((x, y) => y.b.travellers - x.b.travellers);
      const isl = E.meta.islands || {};
      const html = order.map(({ a, b }) => {
        const cur = sc ? agg(sc.atolls, "atoll", a, ids) : b;
        const open = !!state.open[a];
        let kids = "";
        if (open) {
          const list = Object.keys(isl).filter((id) => isl[id].atoll === a).map((id) => ({ id, b: agg(bIs, "island_id", id, ids) }))
            .filter((x) => x.b.total > 0).sort((x, y) => y.b.travellers - x.b.travellers || String(isl[x.id].name).localeCompare(isl[y.id].name));
          kids = `<div class="rows" style="margin-top:6px">${list.map((x) => {
            const c = sc ? agg(sc.islands, "island_id", x.id, ids) : x.b;
            return `<div class="row" style="padding:6px 9px;font-size:12.5px">${row(isl[x.id].name, x.b, c, true)}</div>`;
          }).join("")}</div>`;
        }
        return `<div><button type="button" class="row" data-atoll="${esc(a)}" aria-expanded="${open}" style="width:100%">${row(atollName(a), b, cur)}</button>${kids}</div>`;
      }).join("");
      const m = E.meta;
      const intro = m.residents ? `<p class="issue-why">${n(m.residents)} synthetic residents on the islands of ${n((m.atolls || []).length)} atolls, ${esc(m.population_source)}. Each has their own hospital, referral and school trips by age and grade, routed on the published ferry timetable.</p>` : "";
      const who = m.rules ? `<details class="more" style="margin-top:12px"><summary>Who travels, and when</summary><div>
        <ul class="issue-list">${m.rules.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div></details>` : "";
      acc.innerHTML = `<div class="eyebrow">Modelled access</div><div class="sec-head"><h2>Access by atoll</h2></div>${intro}
        <div class="chips">${Object.keys(CATS).map((k) => `<button type="button" class="chip${k === state.cat ? " sel" : ""}" data-cat="${k}" aria-pressed="${k === state.cat}">${esc(CATS[k].label)}</button>`).join("")}</div>
        <p class="status-line">Share of residents whose ferry round trip works: arrive on time, attend, and get home the same day. Modelled, not observed.</p>
        <div class="rows">${html}</div>${who}`;
      acc.hidden = false;
    }

    adj.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest("[data-scen]");
      if (!b) return;
      state.scen = scenarios.find((x) => x.id === b.dataset.scen) || null;
      renderAdjust(); renderAccess();
    });
    acc.addEventListener("click", (e) => {
      const c = e.target.closest && e.target.closest("[data-cat]");
      if (c) { state.cat = c.dataset.cat; renderAccess(); return; }
      const r = e.target.closest && e.target.closest("[data-atoll]");
      if (r) { state.open[r.dataset.atoll] = !state.open[r.dataset.atoll]; renderAccess(); }
    });
    renderAdjust(); renderAccess();
  } catch (err) { adj.hidden = true; acc.hidden = true; }
})();
