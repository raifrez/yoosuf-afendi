// M.A.N.D.A.R.I.N dashboard: the real ferry network on a map with ferries
// moving along their routes, and one rail for the network, same-day hospital
// access, timetable changes and assumptions. Every access number comes from
// simulator output; the journey rule is an editable assumption.

(function () {
  const D = window.MANDARIN_DATA;
  const geo = window.MALDIVES_GEO;
  const M = window.Mandarin;
  const { fmt, fmtDur } = M;

  const $ = (sel) => document.querySelector(sel);
  const n = (v) => Math.round(v).toLocaleString("en-US");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const listNames = (names) => names.length <= 2 ? names.join(" and ") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const atollById = Object.fromEntries(geo.atolls.map((a) => [a.id, a]));
  const stopById = Object.fromEntries(D.stops.map((s) => [s.id, s]));
  const facilityByAtoll = Object.fromEntries(D.facilities.map((f) => [f.atoll, f]));
  const tripMeta = Object.fromEntries(D.trips.map((t) => [t.id, t]));
  const popKnown = D.stops.every((s) => s.population != null);
  const UNIT = popKnown ? ["resident", "residents"] : ["island", "islands"];
  const units = (v) => `${n(v)} ${v === 1 ? UNIT[0] : UNIT[1]}`;
  const sname = (id) => (stopById[id] ? stopById[id].name : id);
  const routeName = (tripId) => `Route ${tripMeta[tripId].route}`;
  const ROUTES = new Set(D.trips.map((t) => t.route));
  const FEED_ATOLLS = [...new Set(D.stops.map((s) => s.atoll))];

  const TRIPS = D.trips.map((t) => ({
    id: t.id, days: "all",
    stops: t.calls.map(([sid, m], k, arr) => ({ island: sid, ...(k > 0 ? { arr: fmt(m) } : {}), ...(k < arr.length - 1 ? { dep: fmt(m) } : {}) })),
  }));
  const tripAtolls = (id) => new Set(tripMeta[id].calls.map(([s]) => stopById[s].atoll));
  const tripsTouching = (atollId) => D.trips.filter((t) => tripAtolls(t.id).has(atollId)).map((t) => t.id);
  const tripsWithin = (atollId) => D.trips.filter((t) => { const a = tripAtolls(t.id); return a.size === 1 && a.has(atollId); }).map((t) => t.id);
  const firstDep = (id) => tripMeta[id].calls[0][1];
  function tripLabel(id) {
    const c = tripMeta[id].calls;
    return `${routeName(id)} · ${sname(c[0][0])} → ${sname(c[c.length - 1][0])}`;
  }
  const stopsIn = (atollId) => D.stops.filter((s) => s.atoll === atollId);

  // Routes serving an atoll, ordered by first departure. Each gets a colour slot
  // (validated categorical palette, max 5; a 6th+ route falls back to neutral).
  function routesIn(atollId) {
    const byRoute = new Map();
    for (const id of tripsTouching(atollId)) {
      const r = tripMeta[id].route;
      if (!byRoute.has(r)) byRoute.set(r, []);
      byRoute.get(r).push(id);
    }
    return [...byRoute.entries()]
      .map(([route, trips]) => ({ route, trips: trips.sort((a, b) => firstDep(a) - firstDep(b)) }))
      .sort((a, b) => firstDep(a.trips[0]) - firstDep(b.trips[0]))
      .map((r, i) => {
        const longest = r.trips.map((id) => tripMeta[id].calls).sort((a, b) => b.length - a.length)[0];
        return { ...r, color: i < 5 ? `var(--r${i + 1})` : "var(--r-other)", stops: longest.map(([sid]) => sid) };
      });
  }
  const routeColor = new Map(); // route id -> colour for the selected atoll
  const settings = { arriveBy: "10:00", activityMin: 120, homeBy: "18:00", buffer: 15 };

  function fxFor(atollId) {
    const f = facilityByAtoll[atollId];
    const stops = stopsIn(atollId);
    if (!f || stops.length < 2) return null;
    return {
      meta: { weekday: "tue", classification: "observed" },
      hub: f.stop, transferBufferMin: settings.buffer, serviceWindow: { start: "05:00", end: "22:00" },
      islands: stops.map((s) => ({
        id: s.id, name: s.name, population: popKnown ? s.population : 1, schoolAge: 0, secondaryStudents: 0, ownSecondary: true,
        harbourToFacilityMin: s.id === f.stop ? f.walkMin : 0,
      })),
      trips: TRIPS,
      rules: [{ id: "health", label: "Hospital appointment", short: "Hospital", eligible: "residents", destination: f.stop,
        earliestStart: "05:00", arriveBy: settings.arriveBy, activityMin: settings.activityMin, homeBy: settings.homeBy }],
    };
  }

  const state = { atoll: null, shifts: {}, editTrip: null, island: null, view: "list", suggestion: null, national: null, busy: false };
  let nets = {};
  let shiftError = null;

  function rebuild() {
    nets = {};
    for (const id of FEED_ATOLLS) {
      const fx = fxFor(id);
      if (fx) nets[id] = { fx, baseline: M.run(fx, null) };
    }
    recompute();
  }
  function recompute() {
    const shifts = Object.fromEntries(Object.entries(state.shifts).filter(([, v]) => v));
    shiftError = null;
    for (const net of Object.values(nets)) {
      net.current = net.baseline; net.comparison = null;
      if (!Object.keys(shifts).length) continue;
      const r = M.run(net.fx, { shifts });
      if (r.error) { shiftError = r.error; continue; }
      net.current = r; net.comparison = M.compare(net.baseline, r);
    }
    if (shiftError) for (const net of Object.values(nets)) { net.current = net.baseline; net.comparison = null; }
  }
  const moved = () => Object.entries(state.shifts).filter(([, v]) => v);
  const active = () => moved().length > 0 && !shiftError;
  const resOf = (run, islandId) => run.results.health.find((r) => r.home_island_id === islandId);

  function totals(which) {
    const t = { eligible: 0, success: 0, failed: 0, by_reason: {}, gained: 0, lost: 0 };
    for (const net of Object.values(nets)) {
      const s = net[which].summary.health;
      t.eligible += s.eligible; t.success += s.success; t.failed += s.failed;
      for (const [k, v] of Object.entries(s.by_reason)) t.by_reason[k] = (t.by_reason[k] || 0) + v;
      if (net.comparison) { t.gained += net.comparison.health.gained; t.lost += net.comparison.health.lost; }
    }
    t.access_pct = t.eligible ? (t.success / t.eligible) * 100 : null;
    return t;
  }
  function scopeSummary(which) {
    if (!state.atoll) return totals(which);
    const net = nets[state.atoll];
    if (!net) return null;
    const s = net[which].summary.health;
    return { ...s, gained: net.comparison ? net.comparison.health.gained : 0, lost: net.comparison ? net.comparison.health.lost : 0 };
  }

  const REASON = {
    late_arrival: "Arrives late", no_return: "Can't get home", missed_connection: "Missed connection",
    no_service: "No ferry today", no_route: "No morning ferry",
  };
  const REASON_COUNT = {
    late_arrival: ["arrives late", "arrive late"], no_return: ["can't get home", "can't get home"],
    missed_connection: ["misses a connection", "miss a connection"], no_service: ["has no ferry", "have no ferry"],
    no_route: ["has no morning ferry", "have no morning ferry"],
  };

  // ---- Map ---------------------------------------------------------------
  const map = window.MandarinMap.createMap($("#mapsvg"), geo, {
    onAtoll: (id) => selectAtoll(id),
    onIsland: (id) => { if (stopById[id] && stopById[id].atoll === state.atoll && nets[state.atoll]) showJourney(id); },
  });
  const P = Object.fromEntries(D.stops.map((s) => [s.id, map.project(s.lon, s.lat)]));

  function selectAtoll(id) {
    state.atoll = id || null;
    state.view = "list";
    state.suggestion = null;
    const trips = state.atoll ? tripsTouching(state.atoll) : [];
    state.editTrip = trips.includes(state.editTrip) ? state.editTrip : trips[0] || null;
    const net = nets[state.atoll];
    state.island = net ? net.baseline.results.health[0]?.home_island_id : null;
    routeColor.clear();
    if (state.atoll) for (const r of routesIn(state.atoll)) routeColor.set(r.route, r.color);
    map.zoomTo(state.atoll, true, state.atoll ? stopsIn(state.atoll).map((x) => P[x.id]) : null);
    $("#atoll").value = state.atoll || "";
    if (state.atoll && trips.length && !boatsAt(anim.t).some((b) => tripAtolls(b.id).has(state.atoll))) {
      // Nothing sailing here right now: jump to the next departure in this atoll.
      const deps = trips.map(firstDep).sort((a, b) => a - b);
      anim.t = deps.find((d) => d >= anim.t) ?? deps[0];
    }
    buildTripOptions();
    render();
    $("#rail-scroll").scrollTop = 0;
  }

  function stopStatus(id) {
    const s = stopById[id];
    const net = nets[s.atoll];
    if (!net) return "none";
    if (net.fx.hub === id) return "hub";
    const r = resOf(net.current, id);
    return r ? (r.success ? "ok" : "bad") : "none";
  }

  function renderMap() {
    const status = {}, notes = {};
    for (const a of geo.atolls) {
      const net = nets[a.id];
      if (FEED_ATOLLS.includes(a.id)) {
        // Labels carry the serious issues: people cut off from the hospital trip,
        // and residents of islands that aren't on the ferry schedule.
        const iss = issuesFor(a.id);
        const parts = [];
        if (iss.hospital.w > 0) parts.push(`${n(iss.hospital.w)} cut off`);
        if (iss.nostop.w > 0) parts.push(`${n(iss.nostop.w)} off schedule`);
        status[a.id] = parts.length ? "bad" : net ? "ok" : "none";
        notes[a.id] = parts.join(" · ");
      } else {
        status[a.id] = "none";
        notes[a.id] = "";
      }
    }
    map.setState({ atollId: state.atoll, status, notes });
    const editedIds = new Set(active() ? moved().map(([id]) => id) : []);
    const pairs = new Map();
    const inAtoll = state.atoll ? new Set(tripsTouching(state.atoll)) : new Set();
    for (const t of D.trips) {
      if (inAtoll.has(t.id)) continue;
      for (let i = 0; i < t.calls.length - 1; i++) {
        const a = t.calls[i][0], b = t.calls[i + 1][0];
        const key = [a, b].sort().join("|");
        const p = pairs.get(key) || { a, b, edited: false };
        if (editedIds.has(t.id)) p.edited = true;
        pairs.set(key, p);
      }
    }
    const routes = [...pairs.values()].map((p) => ({ x1: P[p.a][0], y1: P[p.a][1], x2: P[p.b][0], y2: P[p.b][1], kind: p.edited ? "edited" : "today" }));
    const nodes = D.stops.map((s) => {
      const st = stopStatus(s.id);
      const net = nets[s.atoll];
      const full = state.atoll && s.atoll === state.atoll;
      let caption = "";
      if (full) {
        if (st === "hub") caption = facilityByAtoll[s.atoll].classification === "observed" ? "Hospital" : "Hospital (assumed)";
        else if (st === "bad") caption = REASON[resOf(net.current, s.id).failure_reason];
      }
      return {
        id: s.id, x: P[s.id][0], y: P[s.id][1], mini: !full, hub: st === "hub",
        r: st === "hub" ? 10 : !popKnown ? 7 : s.population ? Math.round(6 + Math.sqrt(s.population) / 7) : 5,
        status: st, label: s.name, caption, selected: full && state.view === "journey" && s.id === state.island,
      };
    });
    const bubbles = [];
    const routeLines = state.atoll ? routesIn(state.atoll).map((r) => {
      const pts = r.stops.map((sid) => P[sid]);
      let best = 0, bi = 0;
      for (let i = 0; i < pts.length - 1; i++) { const d = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]); if (d > best) { best = d; bi = i; } }
      return {
        id: r.route, label: r.route, color: r.color, stops: r.stops, points: pts,
        labelAt: [(pts[bi][0] + pts[bi + 1][0]) / 2, (pts[bi][1] + pts[bi + 1][1]) / 2],
        edited: active() && r.trips.some((id) => state.shifts[id]),
      };
    }) : [];
    map.setNetwork({ nodes, routes, bubbles, routeLines });
    drawBoats();
  }

  // ---- Ferry animation ---------------------------------------------------
  // Ferries loop through the day in the atoll view (6 schedule minutes per second).
  const anim = { t: 6 * 60 + 30, playing: !reduced, speed: 6, last: performance.now() };

  function boatsAt(t) {
    const out = [];
    for (const trip of D.trips) {
      const shift = active() ? state.shifts[trip.id] || 0 : 0;
      const c = trip.calls;
      if (t < c[0][1] + shift || t > c[c.length - 1][1] + shift) continue;
      for (let i = 0; i < c.length - 1; i++) {
        const m0 = c[i][1] + shift, m1 = c[i + 1][1] + shift;
        if (t < m0 || t > m1) continue;
        const k = m1 > m0 ? (t - m0) / (m1 - m0) : 0;
        const [x0, y0] = P[c[i][0]], [x1, y1] = P[c[i + 1][0]];
        const near = k < 0.5 ? c[i][0] : c[i + 1][0];
        const atolls = tripAtolls(trip.id);
        out.push({
          id: trip.id, x: x0 + (x1 - x0) * k, y: y0 + (y1 - y0) * k,
          angle: (Math.atan2(y1 - y0, x1 - x0) * 180) / Math.PI,
          cls: `${shift ? "moved" : ""} ${state.atoll && !atolls.has(state.atoll) ? "away" : ""}`,
          color: routeColor.get(trip.route) || "", route: trip.route,
          title: `${routeName(trip.id)} · ${k < 0.5 ? "leaving" : "approaching"} ${sname(near)}`,
        });
        break;
      }
    }
    return out;
  }
  function drawBoats() {
    const national = !state.atoll;
    $(".mapbox").classList.toggle("national", national);
    $("#clock-chip").hidden = national;
    $("#map-back").hidden = national;
    if (national) { map.setBoats([]); return; }
    const boats = boatsAt(anim.t);
    map.setBoats(boats);
    $("#clock").textContent = fmt(Math.floor(anim.t));
    const inScope = boats.filter((b) => tripAtolls(b.id).has(state.atoll)).length;
    $("#clock-sub").textContent = `${inScope} ${inScope === 1 ? "ferry" : "ferries"} sailing`;
  }
  // Time-based (not frame-based) so the clock stays right in throttled panes.
  setInterval(() => {
    const now = performance.now();
    const dt = Math.min(5, (now - anim.last) / 1000);
    anim.last = now;
    if (!anim.playing || !state.atoll) return;
    anim.t += dt * anim.speed;
    if (anim.t > 20 * 60) anim.t = 5 * 60;
    drawBoats();
  }, 50);

  // ---- Rail: overview ----------------------------------------------------
  function renderOverview() {
    const el = $("#r-overview");
    el.hidden = !state.atoll;
    if (!state.atoll) { el.innerHTML = ""; return; }
    const a = atollById[state.atoll];
    const stops = stopsIn(state.atoll);
    const trips = tripsTouching(state.atoll);
    if (!stops.length) {
      el.innerHTML = `<div class="eyebrow">Atoll</div><h2>${esc(a.name)} <span class="muted" style="font-size:14px;font-weight:500">${esc(a.alt)}</span></h2>
        <p>No ferry sailings for this atoll in the published schedule yet. To include it, add its sailings to <span class="mono">data/ferry_schedules.csv</span> and its hospital island to <span class="mono">data/facilities.csv</span>.</p>`;
      return;
    }
    const first = Math.min(...trips.map((id) => tripMeta[id].calls[0][1]));
    const last = Math.max(...trips.map((id) => { const c = tripMeta[id].calls; return c[c.length - 1][1]; }));
    const links = [...new Set(trips.flatMap((id) => [...tripAtolls(id)]))].filter((x) => x !== state.atoll);
    el.innerHTML = `
      <h3>Ferries in ${esc(a.name)}</h3>
      <div class="stats">
        <div class="stat"><b>${stops.length}</b><span>islands with a ferry stop</span></div>
        <div class="stat"><b>${trips.length}</b><span>sailings a day</span></div>
        <div class="stat"><b class="mono" style="font-size:19px">${fmt(first)}</b><span>first departure</span></div>
        <div class="stat"><b class="mono" style="font-size:19px">${fmt(last)}</b><span>last arrival</span></div>
      </div>
      ${links.length ? `<p class="status-line">Sailings also reach ${esc(listNames(links.map((x) => atollById[x].name)))}.</p>` : ""}
      <div class="eyebrow">Routes</div>
      <div class="routes">${routesIn(state.atoll).map((r) => `
        <button type="button" class="route-row" data-route-row="${r.route}">
          <span class="swatch" style="background:${r.color}"></span>
          <span class="route-main"><b>Route ${esc(r.route)}</b><span>${esc(r.stops.map(sname).join(" → "))}</span></span>
          <span class="route-times mono">${r.trips.map((id) => { const c = tripMeta[id].calls; const sh = active() ? state.shifts[id] || 0 : 0; return `<span class="${sh ? "moved-time" : ""}">${fmt(c[0][1] + sh)}–${fmt(c[c.length - 1][1] + sh)}</span>`; }).join("")}</span>
        </button>`).join("")}</div>
      <p class="status-line">Hover a route to pick it out on the map; click to jump to its next sailing.</p>`;
  }

  // ---- Rail: same-day hospital access -------------------------------------
  // ---- Issues ----------------------------------------------------------
  // Each issue is backed by data: the simulator (hospital trip, waits, long
  // days) or the Census ↔ ferry-stop coverage (islands not on the schedule).
  const LONG_WAIT = 120, LONG_DAY = 10 * 60;
  const ISSUE = {
    hospital: { title: "Can't make a same-day hospital trip", tone: "bad",
      why: () => `Can't arrive by ${settings.arriveBy} and be home by ${settings.homeBy} on the scheduled ferries.` },
    nostop: { title: "Not on the ferry schedule", tone: "bad",
      why: () => "Inhabited islands with no stop in the published schedule. They may rely on other boats; check before treating them as cut off." },
    wait: { title: "Long wait at the hospital", tone: "warn",
      why: () => `The trip works, but the ferry gets them there ${fmtDur(LONG_WAIT)} or more before a ${settings.arriveBy} appointment.` },
    longday: { title: "Very long day for one appointment", tone: "warn",
      why: () => `The trip works, but leaving home to getting back takes ${fmtDur(LONG_DAY)} or more.` },
  };
  const ISSUE_ORDER = ["hospital", "nostop", "wait", "longday"];
  const islandPop = (id) => (popKnown ? stopById[id].population : 1);

  function issuesFor(atollId) {
    const out = Object.fromEntries(ISSUE_ORDER.map((k) => [k, { w: 0, items: [] }]));
    const add = (k, w, item) => { out[k].w += w; out[k].items.push(item); };
    const net = nets[atollId];
    if (net) {
      for (const r of net.current.results.health) {
        if (!r.success) { add("hospital", r.population_weight, { id: r.home_island_id, r }); continue; }
        if (r.wait_before_minutes >= LONG_WAIT) add("wait", r.population_weight, { id: r.home_island_id, r, detail: `waits ${fmtDur(r.wait_before_minutes)}` });
        const day = r.home_arrival - r.legs[0].dep;
        if (day >= LONG_DAY) add("longday", r.population_weight, { id: r.home_island_id, r, detail: `${fmtDur(day)}, ${fmt(r.legs[0].dep)}–${fmt(r.home_arrival)}` });
      }
    }
    if (FEED_ATOLLS.includes(atollId)) {
      for (const isl of D.islands || []) {
        if (isl.atoll !== atollId || isl.status !== "no_route_in_data" || isl.roadLinkedTo) continue;
        add("nostop", popKnown ? isl.population : 1, { name: isl.name, detail: popKnown ? `${n(isl.population)} residents` : "" });
      }
    }
    for (const k of ISSUE_ORDER) out[k].items.sort((a, b) => (b.r ? b.r.population_weight : 0) - (a.r ? a.r.population_weight : 0));
    return out;
  }

  function issueHead(k, w, extra = "") {
    const it = ISSUE[k];
    return `<div class="issue-head"><span class="issue-dot ${it.tone}" aria-hidden="true"></span><h3>${esc(it.title)}</h3><span class="issue-n ${it.tone}">${esc(units(w))}</span></div>
      <p class="issue-why">${esc(it.why())}${extra}</p>`;
  }

  function renderAccess() {
    const el = $("#r-access");
    el.hidden = false;
    if (state.atoll && state.view === "journey" && nets[state.atoll]) { el.innerHTML = journeyHtml(); return; }
    const scopeName = state.atoll ? atollById[state.atoll].name : "All of the Maldives";
    const head = `<div class="eyebrow">${esc(scopeName)}</div><div class="sec-head"><h2>Current issues</h2><span class="tag assumed">rule assumed</span></div>`;

    if (!state.atoll) {
      const per = Object.fromEntries(FEED_ATOLLS.map((id) => [id, issuesFor(id)]));
      const cards = ISSUE_ORDER.map((k) => {
        const rows = FEED_ATOLLS.map((id) => ({ id, w: per[id][k].w, count: per[id][k].items.length })).filter((x) => x.count && (!popKnown || x.w > 0)).sort((a, b) => b.w - a.w);
        const w = rows.reduce((s, x) => s + x.w, 0);
        if (!rows.length) return null;
        let extra = "";
        if (k === "hospital") {
          const t = totals("current"), b = totals("baseline");
          const pp = active() ? t.access_pct - b.access_pct : 0;
          extra = ` ${t.access_pct.toFixed(0)}% of ${units(t.eligible)} served by ferry can.${active() && Math.abs(pp) >= 0.05 ? ` <b class="${pp > 0 ? "good" : "badtxt"}">${pp > 0 ? "+" : "−"}${Math.abs(pp).toFixed(1)} pp with your changes.</b>` : ""}`;
        }
        return { k, w, html: `<div class="issue ${ISSUE[k].tone}">${issueHead(k, w, extra)}
          <div class="issue-atolls">${rows.map((x) => `<button type="button" class="issue-atoll" data-go-atoll="${x.id}"><span>${esc(atollById[x.id].name)}</span><b>${n(x.w)}</b></button>`).join("")}</div></div>` };
      }).filter(Boolean);
      const noData = geo.atolls.filter((a) => !FEED_ATOLLS.includes(a.id));
      el.innerHTML = head + (cards.length ? `<div class="issues">${cards.map((c) => c.html).join("")}</div>` : `<p class="empty">No issues found under this rule.</p>`) +
        `<p class="status-line">Not checked: ${noData.length} atolls have no ferry data yet (${esc(noData.map((a) => a.name).join(", "))}).</p>`;
      return;
    }

    const iss = issuesFor(state.atoll);
    const net = nets[state.atoll];
    const parts = [];
    for (const k of ISSUE_ORDER) {
      const x = iss[k];
      if (!x.items.length && !(k === "hospital" && net && active())) continue;
      if (k === "hospital") {
        const cur = net.current.summary.health;
        parts.push(`<div class="issue bad">${issueHead(k, x.w, ` ${cur.access_pct.toFixed(0)}% of ${units(cur.eligible)} served by ferry can.`)}${barriersHtml()}</div>`);
      } else {
        parts.push(`<div class="issue ${ISSUE[k].tone}">${issueHead(k, x.w)}
          <ul class="issue-list">${x.items.map((it) => it.id
            ? `<li><button type="button" class="link" data-inspect="${it.id}">${esc(sname(it.id))}</button><span>${esc(it.detail || "")}</span></li>`
            : `<li><span class="li-name">${esc(it.name)}</span><span>${esc(it.detail || "")}</span></li>`).join("")}</ul></div>`);
      }
    }
    if (!net) {
      parts.push(`<p class="empty">${FEED_ATOLLS.includes(state.atoll) ? "Only one island of this atoll is in the ferry schedule, so there's no ferry journey to the hospital to model." : "No ferry schedule for this atoll yet, so its issues can't be checked."}</p>`);
    }
    const islands = net ? `<div class="eyebrow">Islands</div><div class="chips">${net.current.results.health.map((r) => `<button type="button" class="chip" data-inspect="${r.home_island_id}" style="${r.success ? "" : "color:var(--bad);font-weight:600"}">${r.success ? "" : "✕ "}${esc(sname(r.home_island_id))}</button>`).join("")}</div>` : "";
    el.innerHTML = head + (parts.length ? `<div class="issues">${parts.join("")}</div>` : `<p class="empty">No issues found in ${esc(atollById[state.atoll].name)} under this rule.</p>`) + islands;
  }

  function groupKey(r) {
    switch (r.failure_reason) {
      case "late_arrival": return `late|${r.legs[r.legs.length - 1].trip_id}`;
      case "missed_connection": return `missed|${r.evidence.at}|${r.evidence.departs}`;
      case "no_return": return `noret|${r.evidence.last_workable_departure}|${r.evidence.late_home_departure}`;
      default: return r.failure_reason;
    }
  }

  function describeGroup(rs) {
    const r = rs[0];
    const net = nets[state.atoll];
    const f = facilityByAtoll[state.atoll];
    const hub = sname(net.fx.hub);
    const names = listNames(rs.map((x) => sname(x.home_island_id)));
    const plural = rs.length > 1;
    switch (r.failure_reason) {
      case "late_arrival": {
        const leg = r.legs[r.legs.length - 1];
        return { head: `${names} ${plural ? "reach" : "reaches"} the hospital ${fmtDur(r.minutes_late)} late`,
          detail: `${routeName(leg.trip_id)} docks at ${hub} at ${fmt(leg.arr)}. With ${r.walk_minutes} min to ${f.name.startsWith("Atoll hospital") ? "the hospital" : f.name}, that's ${fmt(r.facility_arrival)} for a ${settings.arriveBy} appointment.` };
      }
      case "no_return": {
        const e = r.evidence;
        let detail = `A ${settings.arriveBy} appointment ends at ${fmt(r.activity_end)}.`;
        if (e.late_home_departure != null) detail += ` The next ferry home leaves ${hub} at ${fmt(e.late_home_departure)} and arrives at ${fmt(e.late_home_arrival)}, after ${settings.homeBy}.`;
        else if (e.last_workable_departure != null) detail += ` The last ferry that gets home in time leaves at ${fmt(e.last_workable_departure)}.`;
        else detail += " No ferry goes home after it.";
        return { head: `${names} can't get home the same day`, detail };
      }
      case "missed_connection": {
        const e = r.evidence;
        return { head: `${names} ${plural ? "miss" : "misses"} the connection at ${sname(e.at)}`,
          detail: `The ferry docks at ${sname(e.at)} at ${fmt(e.arrived)}; the onward ferry leaves at ${fmt(e.departs)}, ${e.gap} min later. Changing boats needs ${e.needed} min.` };
      }
      case "no_service":
        return { head: `${names} ${plural ? "have" : "has"} no ferry today`, detail: "No sailing in the schedule serves this island." };
      default:
        return { head: `${names} ${plural ? "have" : "has"} no morning ferry to ${hub}`,
          detail: `No combination of scheduled sailings reaches ${hub} by ${settings.arriveBy}. The island is only served at other times of day.` };
    }
  }

  function barriersHtml() {
    const net = nets[state.atoll];
    const groups = new Map(), fixed = [];
    for (const r of net.current.results.health) {
      const b = resOf(net.baseline, r.home_island_id);
      if (!r.success) {
        const key = (active() && b.success ? "new|" : "") + groupKey(r);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(r);
      } else if (active() && !b.success) fixed.push([r, b]);
    }
    const parts = [];
    for (const [r, b] of fixed) {
      parts.push(`<div class="barrier good"><div class="barrier-top"><span class="pill good">Fixed by your change</span></div>
        <div class="barrier-head">${esc(sname(r.home_island_id))} can now get there and back</div>
        <div class="barrier-detail">At the hospital by ${fmt(r.facility_arrival)}, home by ${fmt(r.home_arrival)}. Before: ${esc(REASON[b.failure_reason].toLowerCase())}.</div>
        <button type="button" class="link" data-inspect="${r.home_island_id}">See the journey →</button></div>`);
    }
    for (const [key, rs] of [...groups].sort((a, b) => b[1].length - a[1].length)) {
      const d = describeGroup(rs);
      const w = rs.reduce((s, x) => s + x.population_weight, 0);
      parts.push(`<div class="barrier"><div class="barrier-top"><span class="pill bad">${esc(key.startsWith("new|") ? "New problem from your change" : REASON[rs[0].failure_reason])}</span><span class="barrier-n">${esc(w || !popKnown ? units(w) : "no Census residents")}</span></div>
        <div class="barrier-head">${esc(d.head)}</div>
        <div class="barrier-detail">${esc(d.detail)}</div>
        <button type="button" class="link" data-inspect="${rs[0].home_island_id}">See the journey →</button></div>`);
    }
    return parts.length ? `<div class="rows">${parts.join("")}</div>` : `<p class="empty">Every ferry-served island can get there and back under this rule.</p>`;
  }

  function timeline(r) {
    const steps = [];
    const ride = (l) => steps.push({ kind: "ride", t: fmt(l.dep), title: `${routeName(l.trip_id)}: ${sname(l.from)} → ${sname(l.to)}`, text: `Arrives ${fmt(l.arr)} · ${fmtDur(l.arr - l.dep)} on board` });
    const rideAll = (legs) => legs.forEach((l, i) => {
      if (i > 0) steps.push({ kind: "wait", t: fmt(legs[i - 1].arr), title: `Change boats at ${sname(l.from)}`, text: `${fmtDur(l.dep - legs[i - 1].arr)} between ferries` });
      ride(l);
    });
    if (r.failure_reason === "no_service" || r.failure_reason === "no_route") {
      steps.push({ kind: "fail", t: "—", title: REASON[r.failure_reason], text: describeGroup([r]).detail });
      return steps;
    }
    if (r.failure_reason === "missed_connection") {
      const e = r.evidence;
      const idx = r.legs.findIndex((l) => l.from === e.at && l.dep === e.departs);
      r.legs.slice(0, idx).forEach(ride);
      steps.push({ kind: "fail", t: fmt(e.arrived), title: `Missed connection at ${sname(e.at)}`, text: describeGroup([r]).detail });
      return steps;
    }
    rideAll(r.legs);
    steps.push({ kind: "walk", t: fmt(r.legs[r.legs.length - 1].arr), title: "To the hospital", text: `${r.walk_minutes} min from the harbour` });
    if (r.failure_reason === "late_arrival") {
      steps.push({ kind: "fail", t: fmt(r.facility_arrival), title: `Arrives ${fmtDur(r.minutes_late)} late`, text: `The appointment starts at ${settings.arriveBy}.` });
      return steps;
    }
    const waitBefore = r.arrive_by - r.facility_arrival;
    if (waitBefore > 0) steps.push({ kind: "wait", t: fmt(r.facility_arrival), title: "Wait", text: `${fmtDur(waitBefore)} before the appointment` });
    steps.push({ kind: "activity", t: settings.arriveBy, title: "Hospital appointment", text: `Until ${fmt(r.activity_end)} (assumed length)` });
    steps.push({ kind: "walk", t: fmt(r.activity_end), title: "Back to the harbour", text: `${r.walk_minutes} min` });
    if (r.failure_reason === "no_return") {
      steps.push({ kind: "fail", t: fmt(r.evidence.return_ready), title: "No ferry home in time", text: describeGroup([r]).detail.replace(/^A [^.]+\. /, "") });
      return steps;
    }
    const waitAfter = r.return_legs[0].dep - (r.activity_end + r.walk_minutes);
    if (waitAfter > 0) steps.push({ kind: "wait", t: fmt(r.activity_end + r.walk_minutes), title: "Wait for the ferry home", text: fmtDur(waitAfter) });
    rideAll(r.return_legs);
    steps.push({ kind: "home", t: fmt(r.home_arrival), title: `Home on ${sname(r.home_island_id)}`, text: `Whole trip ${fmtDur(r.home_arrival - r.legs[0].dep)}` });
    return steps;
  }

  function journeyHtml() {
    const net = nets[state.atoll];
    const r = resOf(net.current, state.island);
    const b = resOf(net.baseline, state.island);
    const s = stopById[state.island];
    const changed = active() && b.success !== r.success;
    return `
      <button type="button" class="link" id="back">← All of ${esc(atollById[state.atoll].name)}</button>
      <div class="sec-head"><h3>${esc(s.name)} → ${esc(sname(net.fx.hub))}</h3>${r.success ? `<span class="pill good">Can make it</span>` : `<span class="pill bad">${esc(REASON[r.failure_reason])}</span>`}</div>
      <p class="status-line">${s.dv ? `<span lang="dv">${esc(s.dv)}</span> · ` : ""}${!popKnown ? "Population unknown" : s.population ? units(r.population_weight) : `No Census residents${s.populationNote ? ` · ${esc(s.populationNote.replace(/;.*$/, ""))}` : ""}`}${s.approx ? " · position approximate" : ""}${changed ? ` · <b class="${r.success ? "good" : "badtxt"}">${r.success ? "fixed by your change" : "new problem from your change"}</b>` : ""}</p>
      <ol class="timeline">${timeline(r).map((st) => `<li class="step ${st.kind}"><span class="t mono">${st.t}</span><span class="dot" aria-hidden="true"></span><div><div class="st">${esc(st.title)}</div>${st.text ? `<div class="sx">${esc(st.text)}</div>` : ""}</div></li>`).join("")}</ol>
      ${r.success ? `<div class="stats"><div class="stat"><b>${fmtDur(r.travel_minutes)}</b><span>on boats</span></div><div class="stat"><b>${fmtDur(r.wait_minutes)}</b><span>waiting</span></div></div>` : ""}`;
  }

  function showJourney(islandId) {
    state.island = islandId;
    state.view = "journey";
    render();
    // Scroll only the rail, never the page.
    const rail = $("#rail-scroll"), sec = $("#r-access");
    rail.scrollTop = sec.offsetTop;
  }

  // ---- Rail: controls ----------------------------------------------------
  function buildTripOptions() {
    const sel = $("#trip");
    const ids = state.atoll ? tripsTouching(state.atoll).sort((a, b) => firstDep(a) - firstDep(b)) : [];
    sel.innerHTML = ids.map((id) => `<option value="${id}" data-sub="Departs ${fmt(firstDep(id))}${tripAtolls(id).size > 1 ? " · crosses atolls" : ""}">${esc(tripLabel(id))}</option>`).join("");
    if (state.editTrip) sel.value = state.editTrip;
  }

  function setupControls() {
    $("#atoll").innerHTML = `<option value="" data-sub="${FEED_ATOLLS.length} atolls in the ferry schedule">All of the Maldives</option>` + geo.atolls
      .map((a) => `<option value="${a.id}" data-sub="${esc(a.alt)}"${FEED_ATOLLS.includes(a.id) ? ' data-badge="Ferries"' : ""}>${esc(a.name)}</option>`).join("");
    $("#atoll").addEventListener("change", (e) => selectAtoll(e.target.value));
    $("#to-national").addEventListener("click", () => selectAtoll(null));
    $("#trip").addEventListener("change", (e) => { state.editTrip = e.target.value; syncControls(); });
    $("#shift").addEventListener("input", (e) => setShift(Number(e.target.value)));
    $("#earlier").addEventListener("click", () => setShift((state.shifts[state.editTrip] || 0) - 15));
    $("#later").addEventListener("click", () => setShift((state.shifts[state.editTrip] || 0) + 15));
    $("#reset").addEventListener("click", () => { state.shifts = {}; recompute(); render(); });
    $("#moved").addEventListener("click", (e) => {
      const rm = e.target.closest("[data-unmove]");
      if (rm) { delete state.shifts[rm.dataset.unmove]; recompute(); render(); }
    });

    const times = (from, to, step) => { const o = []; for (let m = from; m <= to; m += step) o.push(m); return o; };
    $("#rule-arrive").innerHTML = times(7 * 60, 14 * 60, 30).map((m) => `<option value="${fmt(m)}">${fmt(m)}</option>`).join("");
    $("#rule-duration").innerHTML = [30, 60, 90, 120, 180, 240].map((m) => `<option value="${m}">${fmtDur(m)}</option>`).join("");
    $("#rule-home").innerHTML = times(15 * 60, 21 * 60, 30).map((m) => `<option value="${fmt(m)}">${fmt(m)}</option>`).join("");
    $("#rule-buffer").innerHTML = [5, 10, 15, 20, 30].map((m) => `<option value="${m}">${m} min</option>`).join("");
    $("#rule-arrive").value = settings.arriveBy; $("#rule-duration").value = String(settings.activityMin);
    $("#rule-home").value = settings.homeBy; $("#rule-buffer").value = String(settings.buffer);
    const onRule = () => {
      settings.arriveBy = $("#rule-arrive").value; settings.activityMin = Number($("#rule-duration").value);
      settings.homeBy = $("#rule-home").value; settings.buffer = Number($("#rule-buffer").value);
      state.suggestion = null; state.national = null;
      rebuild(); render();
    };
    for (const id of ["#rule-arrive", "#rule-duration", "#rule-home", "#rule-buffer"]) { $(id).addEventListener("change", onRule); window.Dropdown.enhance($(id)); }

    $("#optimize").addEventListener("click", () => {
      if (!nets[state.atoll] || state.busy) return;
      const atoll = state.atoll;
      searchAtolls([atoll], $("#suggestion"), $("#optimize"), (per) => {
        state.suggestion = { atoll, ...per[0].o };
        renderControls();
      });
    });
    $("#optimize-all").addEventListener("click", optimizeAll);
    $(".rail").addEventListener("click", (e) => {
      if (e.target.closest("#apply-suggestion")) applyWithEffect(state.suggestion.shifts, $("#suggestion"), () => { state.suggestion = null; });
      else if (e.target.closest("#dismiss-suggestion")) { state.suggestion = null; renderControls(); }
      else if (e.target.closest("#apply-national")) applyWithEffect(state.national.shifts, $("#national-suggestion"), () => { state.national = null; });
      else if (e.target.closest("#dismiss-national")) { state.national = null; renderControls(); }
    });
    window.Dropdown.enhance($("#atoll"));
    window.Dropdown.enhance($("#trip"));
  }

  function applyShifts(shifts) {
    state.shifts = { ...state.shifts, ...shifts };
    const first = Object.keys(shifts)[0];
    if (first && state.atoll && tripsTouching(state.atoll).includes(first)) state.editTrip = first;
    recompute();
  }

  // Run the optimizer step by step so the search is visible: an indeterminate
  // loader with live counts in the rail, and on the map the sailing being tried
  // (atoll view) or the atoll being checked (national view).
  const STEP_MS = reduced ? 0 : 70;
  function loaderHtml(text) {
    return `<div class="loader" role="progressbar" aria-label="Searching timetables"><i></i></div><p class="loader-text" aria-live="polite">${text}</p>`;
  }
  function searchAtolls(ids, box, btn, done) {
    state.busy = true;
    const label = btn.textContent;
    btn.disabled = true;
    box.hidden = false;
    map.setSearching(true);
    const per = [];
    let evaluated = 0, ai = 0, it = null;
    (function tick() {
      if (!it) {
        if (ai >= ids.length) {
          map.setSearching(false); map.markAtoll(null); map.highlightRoute(null);
          state.busy = false; btn.disabled = false; btn.textContent = label;
          done(per, evaluated);
          return;
        }
        it = M.optimizeSteps(nets[ids[ai]].fx, { candidates: tripsWithin(ids[ai]) });
        if (ids.length > 1) map.markAtoll(ids[ai]);
      }
      const r = it.next();
      const id = ids[ai];
      if (r.done) {
        evaluated += r.value.evaluated;
        per.push({ id, o: r.value });
        it = null; ai++;
      } else {
        const route = tripMeta[r.value.tripId].route;
        if (ids.length === 1) map.highlightRoute(route);
        btn.textContent = ids.length > 1 ? `Checking ${atollById[id].name} (${ai + 1} of ${ids.length})…` : "Searching…";
        box.innerHTML = loaderHtml(`Trying new times for <b>Route ${esc(route)}</b>${ids.length > 1 ? ` in ${esc(atollById[id].name)}` : ""} · ${n(evaluated + r.value.evaluated)} timetables checked`);
      }
      setTimeout(tick, STEP_MS);
    })();
  }

  function optimizeAll() {
    if (state.busy) return;
    searchAtolls(Object.keys(nets), $("#national-suggestion"), $("#optimize-all"), (per, evaluated) => {
      const shifts = {};
      for (const x of per) Object.assign(shifts, x.o.shifts);
      state.national = { shifts, perAtoll: per, evaluated };
      renderControls();
    });
  }

  // Apply with a short "applying" state, then let the moved routes glow and
  // jump the clock to just before the first moved sailing so it can be watched.
  function applyWithEffect(shifts, box, clear) {
    if (state.busy) return;
    state.busy = true;
    box.innerHTML = loaderHtml(`Applying ${Object.keys(shifts).length} new departure time${Object.keys(shifts).length === 1 ? "" : "s"}…`);
    map.setSearching(true);
    setTimeout(() => {
      map.setSearching(false);
      applyShifts(shifts);
      clear();
      state.busy = false;
      const local = Object.keys(shifts).filter((id) => !state.atoll || tripsTouching(state.atoll).includes(id));
      if (state.atoll && local.length) {
        const first = Math.min(...local.map((id) => firstDep(id) + shifts[id]));
        anim.t = first - 3;
      }
      render();
      map.flashEdited();
    }, reduced ? 0 : 900);
  }

  function setShift(v) {
    if (!state.editTrip) return;
    state.shifts = { ...state.shifts, [state.editTrip]: Math.max(-240, Math.min(240, v)) };
    if (!state.shifts[state.editTrip]) delete state.shifts[state.editTrip];
    recompute(); render();
  }

  function syncControls() {
    if (state.editTrip) {
      const shift = state.shifts[state.editTrip] || 0;
      $("#trip").value = state.editTrip;
      $("#shift").value = shift;
      const from = firstDep(state.editTrip), to = from + shift;
      $("#shift-readout").innerHTML = shift === 0
        ? `Departs <b class="mono">${fmt(from)}</b> <span class="muted">as scheduled</span>`
        : `<span class="mono strike">${fmt(from)}</span> → <b class="mono">${to >= 0 && to <= 1439 ? fmt(to) : "--:--"}</b> <span class="muted">${shift > 0 ? "+" : "−"}${Math.abs(shift)} min at every stop</span>`;
    }
    const list = moved();
    $("#r-moved").hidden = !list.length && !shiftError;
    $("#moved").innerHTML = list.map(([id, s]) => `<li><span class="moved-edit"><span>${esc(tripLabel(id))}</span><span class="mono">${fmt(firstDep(id))} → ${fmt(firstDep(id) + s)}</span></span><button type="button" class="x" data-unmove="${id}" aria-label="Put ${esc(tripLabel(id))} back">×</button></li>`).join("");
    const st = $("#scenario-status");
    if (shiftError) { st.className = "status-line error"; st.textContent = `${shiftError} Showing the published schedule instead.`; }
    else {
      const t = totals("current");
      st.className = "status-line";
      st.innerHTML = `Across all atolls: <b class="good">+${units(t.gained)}</b> gain same-day access${t.lost ? `, <b class="badtxt">${units(t.lost)}</b> lose it` : ", nobody loses it"}.`;
    }
    window.Dropdown.syncAll();
  }

  function suggestionHtml(o, scopeName) {
    const changes = Object.entries(o.shifts);
    const h = o.comparison.health;
    const unresolved = o.unresolved.filter((r) => r.journey_rule_id === "health");
    return `
      <div class="sug-head">${changes.length ? `${changes.length} change${changes.length === 1 ? "" : "s"} for ${esc(scopeName)}` : `No better timetable for ${esc(scopeName)}`}</div>
      ${changes.length ? `<ol class="sug-list">${changes.map(([id, v]) => `<li><span>${esc(tripLabel(id))}</span><span class="mono"><span class="strike">${fmt(firstDep(id))}</span> → <b>${fmt(firstDep(id) + v)}</b></span></li>`).join("")}</ol>` : ""}
      <dl class="sug-result"><div><dt>Gain same-day access</dt><dd class="good"><b>+${units(h.gained)}</b></dd></div><div><dt>Lose access</dt><dd>${n(h.lost)} <span class="muted">(not allowed)</span></dd></div></dl>
      ${unresolved.length ? `<div class="sug-unres"><b>Still not fixed:</b> ${unresolved.map((r) => `${esc(sname(r.home_island_id))} (${esc(REASON[r.failure_reason].toLowerCase())})`).join("; ")}. These need a new sailing or a cross-atoll change.</div>` : ""}
      <div class="sug-actions">${changes.length ? `<button type="button" class="btn primary" id="apply-suggestion">Apply</button>` : ""}<button type="button" class="btn" id="dismiss-suggestion">Dismiss</button></div>
      <p class="sug-note">Checked ${n(o.evaluated)} timetables. Moves sailings inside this atoll in 15-min steps. Doesn't check boats, crews or cost.</p>`;
  }

  function renderControls() {
    const net = nets[state.atoll];
    $("#to-national").hidden = !state.atoll;
    $("#r-move").hidden = !net;
    $("#r-suggest-all").hidden = !!state.atoll;
    if (net) {
      const box = $("#suggestion");
      if (state.suggestion && state.suggestion.atoll === state.atoll) { box.hidden = false; box.innerHTML = suggestionHtml(state.suggestion, atollById[state.atoll].name); }
      else box.hidden = true;
    }
    if (!state.atoll) {
      const box = $("#national-suggestion");
      if (state.national) {
        const changes = Object.entries(state.national.shifts);
        const gained = state.national.perAtoll.reduce((s, x) => s + x.o.comparison.health.gained, 0);
        const unres = state.national.perAtoll.reduce((s, x) => s + x.o.unresolved.filter((r) => r.journey_rule_id === "health").reduce((t, r) => t + r.population_weight, 0), 0);
        box.hidden = false;
        box.innerHTML = `
          <div class="sug-head">${changes.length} sailing${changes.length === 1 ? "" : "s"} to move</div>
          <ol class="sug-list">${state.national.perAtoll.filter((x) => Object.keys(x.o.shifts).length).map((x) => `<li><span><b>${esc(atollById[x.id].name)}</b>: ${Object.entries(x.o.shifts).map(([id, v]) => `${routeName(id)} ${fmt(firstDep(id))} → ${fmt(firstDep(id) + v)}`).join(", ")}</span><span class="good">+${units(x.o.comparison.health.gained)}</span></li>`).join("") || "<li>Nothing to move under this rule.</li>"}</ol>
          <dl class="sug-result"><div><dt>Gain same-day access</dt><dd class="good"><b>+${units(gained)}</b></dd></div><div><dt>Lose access</dt><dd>0 <span class="muted">(not allowed)</span></dd></div><div><dt>Still cut off</dt><dd>${units(unres)}</dd></div></dl>
          <div class="sug-actions">${changes.length ? `<button type="button" class="btn primary" id="apply-national">Apply</button>` : ""}<button type="button" class="btn" id="dismiss-national">Dismiss</button></div>
          <p class="sug-note">Checked ${n(state.national.evaluated)} timetables across ${state.national.perAtoll.length} atolls. Only sailings inside one atoll are moved.</p>`;
      } else box.hidden = true;
    }
  }

  function renderSources() {
    const obs = D.facilities.filter((f) => f.classification === "observed").length;
    const rows = [
      ["Ferry schedules", `data/ferry_schedules.csv → GTFS: ${ROUTES.size} routes, ${D.trips.length} daily sailings`, "observed"],
      ["Operating days", "Not in the source; every route assumed to run daily", "assumed"],
      ["Island positions", `OpenStreetMap, ${D.stops.filter((s) => s.approx).length} approximate`, "observed"],
      ["Hospitals", `data/facilities.csv: ${obs} from OpenStreetMap, ${D.facilities.length - obs} assumed at the atoll capital`, "mixed"],
      popKnown
        ? ["Population", `${D.meta.population.source}: people enumerated per island, linked to all ${D.stops.length} stops by data/export/stop_islands.csv. ${D.stops.filter((s) => !s.population).length} stops (airports, industrial islands) have no Census residents.${D.meta.population.overrides ? ` ${D.meta.population.overrides} set by hand in data/island_population.csv.` : ""}`, "observed"]
        : ["Population", "Not loaded. Each island counts once", "missing"],
      ["Map outlines", "OpenStreetMap coastline and reefs, simplified", "observed"],
    ];
    $("#sources").innerHTML = rows.map(([a, b, c]) => `<div class="src"><b>${a}</b><span class="tag ${c}">${c}</span><span class="d">${esc(b)}</span></div>`).join("") +
      `<ul class="assume">${[
        ...(D.meta.assumptions || []),
        "Ferry positions between stops are drawn on straight lines, not the real sailing path.",
        "Residents go to their own atoll's hospital and can leave home from 05:00.",
        "Suggested timetables move existing sailings inside one atoll (15-min steps, up to 4 h, 05:00–22:00) and never cost anyone access.",
      ].map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`;
  }

  function render() {
    renderMap();
    renderOverview();
    renderAccess();
    renderControls();
    syncControls();
  }

  $("#r-overview").addEventListener("mouseover", (e) => { const r = e.target.closest("[data-route-row]"); map.highlightRoute(r ? r.dataset.routeRow : null); drawBoats(); });
  $("#r-overview").addEventListener("mouseleave", () => { map.highlightRoute(null); drawBoats(); });
  $("#mapsvg").addEventListener("mouseover", (e) => {
    const r = e.target.closest("#mapsvg [data-route]");
    map.highlightRoute(r ? r.dataset.route : null);
  });
  document.addEventListener("click", (e) => {
    const rr = e.target.closest("[data-route-row]");
    if (rr) {
      const ids = D.trips.filter((t) => t.route === rr.dataset.routeRow).map((t) => t.id);
      const deps = ids.map((id) => firstDep(id) + (active() ? state.shifts[id] || 0 : 0)).sort((a, b) => a - b);
      anim.t = (deps.find((d) => d > anim.t + 1) ?? deps[0]) - 2;
      anim.last = performance.now(); drawBoats();
      return;
    }
    const insp = e.target.closest("[data-inspect]");
    if (insp) { showJourney(insp.dataset.inspect); return; }
    if (e.target.closest("#back")) { state.view = "list"; render(); return; }
    const go = e.target.closest("[data-go-atoll]");
    if (go && !go.closest("#mapsvg")) selectAtoll(go.dataset.goAtoll);
  });

  $("#map-back").addEventListener("click", () => selectAtoll(null));
  $("#zoom-in").addEventListener("click", () => map.zoomBy(0.6));
  $("#zoom-out").addEventListener("click", () => map.zoomBy(1 / 0.6));
  $("#zoom-fit").addEventListener("click", () => map.refit());

  rebuild();
  setupControls();
  renderSources();
  buildTripOptions();
  render();
})();
