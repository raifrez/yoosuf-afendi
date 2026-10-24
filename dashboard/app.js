// M.A.N.D.A.R.I.N dashboard. Real ferry schedules (network-data.js, built from
// data/) run through the simulator per atoll. Every number on screen comes from
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

  const atollById = Object.fromEntries(geo.atolls.map((a) => [a.id, a]));
  const stopById = Object.fromEntries(D.stops.map((s) => [s.id, s]));
  const facilityByAtoll = Object.fromEntries(D.facilities.map((f) => [f.atoll, f]));
  const tripMeta = Object.fromEntries(D.trips.map((t) => [t.id, t]));
  const popKnown = D.stops.every((s) => s.population != null);
  const UNIT = popKnown ? ["resident", "residents"] : ["island", "islands"];
  const units = (v) => `${n(v)} ${v === 1 ? UNIT[0] : UNIT[1]}`;
  const sname = (id) => (stopById[id] ? stopById[id].name : id);
  const routeName = (tripId) => `Route ${tripMeta[tripId].route}`;

  // Simulator-shaped trips: one time per stop in the source, so arr = dep.
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

  const FEED_ATOLLS = [...new Set(D.stops.map((s) => s.atoll))];
  const state = { atoll: null, shifts: {}, editTrip: null, island: null, leftView: "cards", suggestion: null, national: null, busy: false };
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
      if (which === "current" && net.comparison) { t.gained += net.comparison.health.gained; t.lost += net.comparison.health.lost; }
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

  // ---- Map ---------------------------------------------------------------
  const map = window.MandarinMap.createMap($("#mapsvg"), geo, {
    onAtoll: (id) => selectAtoll(id),
    onIsland: (id) => { if (stopById[id] && stopById[id].atoll === state.atoll) showJourney(id); },
  });

  function selectAtoll(id) {
    state.atoll = id || null;
    state.leftView = "cards";
    state.suggestion = null;
    const trips = state.atoll ? tripsTouching(state.atoll) : [];
    state.editTrip = trips.includes(state.editTrip) ? state.editTrip : trips[0] || null;
    const net = nets[state.atoll];
    state.island = net ? net.baseline.results.health[0]?.home_island_id : null;
    map.zoomTo(state.atoll);
    $("#atoll").value = state.atoll || "";
    buildTripOptions();
    render();
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
      if (net) {
        const s = net.current.summary.health;
        status[a.id] = s.failed ? "bad" : "ok";
        notes[a.id] = s.failed ? `${s.failed} of ${s.eligible} cut off` : "all can make it";
      } else {
        status[a.id] = "none";
        notes[a.id] = FEED_ATOLLS.includes(a.id) ? "one island in feed" : "no ferry data";
      }
    }
    map.setState({ atollId: state.atoll, status, notes });
    $("#map-hint").hidden = !!state.atoll;

    const editedIds = new Set(active() ? moved().map(([id]) => id) : []);
    const P = Object.fromEntries(D.stops.map((s) => [s.id, map.project(s.lon, s.lat)]));
    const pairs = new Map();
    for (const t of D.trips) {
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
        r: st === "hub" ? 11 : popKnown && s.population ? Math.round(6 + Math.sqrt(s.population) / 7) : 7,
        status: st, label: s.name, caption, selected: full && s.id === state.island,
      };
    });

    const bubbles = state.atoll ? [] : Object.entries(nets).map(([id, net]) => {
      const s = net.current.summary.health;
      const [x, y] = map.centreOf(id);
      return { atoll: id, x, y, r: s.failed ? Math.round(10 + Math.sqrt(s.failed) * (popKnown ? 0.25 : 3.5)) : 8, text: s.failed ? n(s.failed) : "✓", status: s.failed ? "bad" : "ok" };
    });
    map.setNetwork({ nodes, routes, bubbles });
  }

  // ---- KPIs --------------------------------------------------------------
  function delta(value, goodWhenUp, unit) {
    if (!active()) return "";
    if (value == null || Math.abs(value) < 0.05) return `<span class="delta flat">No change</span>`;
    const up = value > 0, good = up === goodWhenUp;
    const txt = unit === "pp" ? `${up ? "+" : "−"}${Math.abs(value).toFixed(1)} pp` : `${up ? "+" : "−"}${n(Math.abs(value))}`;
    return `<span class="delta ${good ? "good" : "bad"}">${up ? "▲" : "▼"} ${txt} vs timetable</span>`;
  }

  function renderKpis() {
    const cur = scopeSummary("current"), base = scopeSummary("baseline");
    const intro = $("#kpi-scope");
    if (!cur) {
      intro.textContent = atollById[state.atoll].name;
      $("#kpi-note").textContent = "No ferry schedule for this atoll yet.";
      $("#kpis").innerHTML = `<div class="kpi empty-kpi"><div class="kpi-label">Nothing to model here yet</div><div class="kpi-sub">Add this atoll's ferries to data/ferry_schedules.csv and its hospital to data/facilities.csv.</div></div>`;
      return;
    }
    intro.textContent = state.atoll ? atollById[state.atoll].name : "All of the Maldives";
    $("#kpi-note").textContent = state.atoll
      ? `${units(cur.eligible)} served by ferry, going to ${facilityByAtoll[state.atoll].name}`
      : `${Object.keys(nets).length} atolls with ferry schedules · ${units(cur.eligible)} modeled`;
    const late = (cur.by_reason.late_arrival || 0) + (cur.by_reason.missed_connection || 0);
    const lateB = (base.by_reason.late_arrival || 0) + (base.by_reason.missed_connection || 0);
    const noRet = cur.by_reason.no_return || 0, noRetB = base.by_reason.no_return || 0;
    const tiles = [
      { label: "Same-day hospital access", value: cur.access_pct == null ? "n/a" : `${cur.access_pct.toFixed(0)}%`,
        sub: `${n(cur.success)} of ${units(cur.eligible)}`, d: delta(cur.access_pct - base.access_pct, true, "pp"), tone: "lead" },
      { label: `${UNIT[1][0].toUpperCase()}${UNIT[1].slice(1)} cut off from same-day care`, value: n(cur.failed),
        sub: `Can't arrive by ${settings.arriveBy} and be home by ${settings.homeBy}`, d: delta(cur.failed - base.failed, false), tone: cur.failed ? "bad" : "good" },
      { label: "Arrive after the appointment starts", value: n(late),
        sub: "Late ferry or a missed connection", d: delta(late - lateB, false), tone: late ? "bad" : "good" },
      { label: "Reach the hospital but can't get home", value: n(noRet),
        sub: `No ferry home by ${settings.homeBy}`, d: delta(noRet - noRetB, false), tone: noRet ? "bad" : "good" },
    ];
    $("#kpis").innerHTML = tiles.map((t) => `<div class="kpi ${t.tone}"><div class="kpi-label">${t.label}</div><div class="kpi-value">${t.value}</div><div class="kpi-sub">${t.sub}</div>${t.d}</div>`).join("");
  }

  // ---- Left column -------------------------------------------------------
  const REASON = {
    late_arrival: "Arrives late",
    no_return: "Can't get home",
    missed_connection: "Missed connection",
    no_service: "No ferry today",
    no_route: "No ferry route",
  };

  // How a count of islands reads in a sentence ("2 can't get home").
  const REASON_COUNT = {
    late_arrival: ["arrives late", "arrive late"],
    no_return: ["can't get home", "can't get home"],
    missed_connection: ["misses a connection", "miss a connection"],
    no_service: ["has no ferry", "have no ferry"],
    no_route: ["has no morning ferry", "have no morning ferry"],
  };

  function renderLeft() {
    $("#left-national").hidden = !!state.atoll;
    $("#left-cards").hidden = !state.atoll || state.leftView !== "cards";
    $("#inspector").hidden = !state.atoll || state.leftView !== "journey";
    if (!state.atoll) renderAtollRanking();
    else if (state.leftView === "cards") renderCards();
    else renderInspector();
  }

  function renderAtollRanking() {
    const rows = Object.entries(nets).map(([id, net]) => ({ id, net, s: net.current.summary.health }))
      .sort((a, b) => b.s.failed - a.s.failed || a.s.access_pct - b.s.access_pct);
    const cut = rows.filter((r) => r.s.failed).length;
    $("#rank-count").textContent = `${cut} of ${rows.length} atolls with ferry data have ${UNIT[1]} cut off`;
    $("#ranking").innerHTML = rows.map(({ id, net, s }) => {
      const a = atollById[id];
      const reasons = Object.entries(s.by_reason).sort((x, y) => y[1] - x[1]).map(([k, v]) => `${n(v)} ${v === 1 ? REASON_COUNT[k][0] : REASON_COUNT[k][1]}`).join(" · ");
      const ch = net.comparison ? net.comparison.health : null;
      const change = ch && (ch.gained || ch.lost) ? `<span class="rank-change">${ch.gained ? `<b class="good">+${n(ch.gained)}</b>` : ""}${ch.lost ? ` <b class="badtxt">−${n(ch.lost)}</b>` : ""}</span>` : "";
      return `<button type="button" class="rank ${s.failed ? "bad" : "ok"}" data-go-atoll="${id}">
        <span class="rank-top"><span class="rank-name">${esc(a.name)}</span><span class="rank-alt">${esc(a.alt)}</span>${change}</span>
        <span class="rank-big">${s.failed ? `${n(s.failed)}<span class="of"> of ${units(s.eligible)} cut off</span>` : `<span class="okline">${s.eligible === 1 ? "The one ferry-served island can" : `All ${units(s.eligible)} can`} make it</span>`}</span>
        <span class="rank-bar" aria-hidden="true"><i style="width:${(s.access_pct || 0).toFixed(1)}%"></i></span>
        <span class="rank-sub">${s.failed ? esc(reasons) : `${s.access_pct.toFixed(0)}% same-day access`}</span>
      </button>`;
    }).join("");
    const none = geo.atolls.filter((a) => !nets[a.id]);
    $("#nodata-list").innerHTML = none.map((a) => `<button type="button" class="chip" data-go-atoll="${a.id}">${esc(a.name)}${FEED_ATOLLS.includes(a.id) ? " (one island)" : ""}</button>`).join("");
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
        return { head: `${names} ${plural ? "reach" : "reaches"} the hospital after a ${settings.arriveBy} appointment starts`,
          detail: `${routeName(leg.trip_id)} docks at ${hub} at ${fmt(leg.arr)}. With ${r.walk_minutes} min to ${f.name.startsWith("Atoll hospital") ? "the hospital" : f.name}, that's ${fmt(r.facility_arrival)}, ${fmtDur(r.minutes_late)} late.`,
          big: fmtDur(r.minutes_late), bigUnit: "late" };
      }
      case "no_return": {
        const e = r.evidence;
        let detail = `A ${settings.arriveBy} appointment ends at ${fmt(r.activity_end)}.`;
        if (e.late_home_departure != null) detail += ` The next ferry home leaves ${hub} at ${fmt(e.late_home_departure)} and arrives at ${fmt(e.late_home_arrival)}, after ${settings.homeBy}.`;
        else if (e.last_workable_departure != null) detail += ` The last ferry that gets home in time leaves at ${fmt(e.last_workable_departure)}.`;
        else detail += " No ferry goes home after it.";
        return { head: `${names} can reach the hospital but can't get home the same day`, detail, big: null };
      }
      case "missed_connection": {
        const e = r.evidence;
        return { head: `${names} ${plural ? "miss" : "misses"} the connection at ${sname(e.at)}`,
          detail: `The ferry docks at ${sname(e.at)} at ${fmt(e.arrived)}; the onward ferry leaves at ${fmt(e.departs)}, ${e.gap} min later. Changing boats needs ${e.needed} min.`, big: null };
      }
      case "no_service":
        return { head: `${names} ${plural ? "have" : "has"} no ferry today`, detail: "No sailing in the schedule serves this island.", big: null };
      default:
        return { head: `${names} ${plural ? "have" : "has"} no morning ferry towards ${hub}`,
          detail: `No combination of scheduled sailings reaches ${hub} by ${settings.arriveBy}. The island is only served at other times of day.`, big: null };
    }
  }

  function renderCards() {
    const net = nets[state.atoll];
    const box = $("#cards");
    if (!net) {
      $("#card-count").textContent = "";
      box.innerHTML = `<p class="empty">${FEED_ATOLLS.includes(state.atoll) ? "Only one island of this atoll is in the ferry feed, so there are no ferry journeys to model." : "No ferry schedule for this atoll yet."}</p>`;
      return;
    }
    const groups = new Map();
    const fixed = [];
    const waits = [];
    for (const r of net.current.results.health) {
      const b = resOf(net.baseline, r.home_island_id);
      if (!r.success) {
        const key = (active() && b.success ? "new|" : "") + groupKey(r);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(r);
      } else if (active() && !b.success) fixed.push([r, b]);
      else if (r.wait_before_minutes >= 120) waits.push(r);
    }
    const cards = [];
    for (const [r, b] of fixed) {
      cards.push({ tone: "good", pill: "Fixed by this change", r, big: units(r.population_weight), bigUnit: "",
        head: `${sname(r.home_island_id)} can now reach the hospital and get home the same day`,
        detail: `Now at the hospital by ${fmt(r.facility_arrival)} and home by ${fmt(r.home_arrival)}. Before: ${REASON[b.failure_reason].toLowerCase()}.`, w: r.population_weight, sort: 0 });
    }
    for (const [key, rs] of groups) {
      const d = describeGroup(rs);
      const w = rs.reduce((s, x) => s + x.population_weight, 0);
      cards.push({ tone: "bad", pill: key.startsWith("new|") ? "New problem from this change" : REASON[rs[0].failure_reason], r: rs[0],
        big: units(w), bigUnit: d.big ? `· ${d.big} ${d.bigUnit}` : "", head: d.head, detail: d.detail, w, sort: key.startsWith("new|") ? 1 : 2 });
    }
    for (const r of waits.sort((a, b) => b.wait_before_minutes - a.wait_before_minutes).slice(0, 3)) {
      cards.push({ tone: "warn", pill: "Works, with a long wait", r, big: fmtDur(r.wait_before_minutes), bigUnit: "waiting",
        head: `${sname(r.home_island_id)} arrives at ${fmt(r.facility_arrival)} for a ${settings.arriveBy} appointment`,
        detail: `${routeName(r.legs[r.legs.length - 1].trip_id)} is the only way to arrive in time. The trip takes from ${fmt(r.legs[0].dep)} to ${fmt(r.home_arrival)}.`, w: 0, sort: 3 });
    }
    cards.sort((a, b) => a.sort - b.sort || b.w - a.w);
    const bad = cards.filter((c) => c.tone === "bad").length;
    $("#card-count").textContent = bad ? `${bad} barrier${bad === 1 ? "" : "s"} on this timetable` : "No barriers on this timetable";
    box.innerHTML = cards.length ? cards.map((c) => `<article class="impact ${c.tone}">
        <div class="impact-top"><span class="pill ${c.tone}">${esc(c.pill)}</span></div>
        <div class="impact-big">${esc(c.big)}<span class="impact-unit">${esc(c.bigUnit)}</span></div>
        <p class="impact-head">${esc(c.head)}</p>
        <p class="impact-detail">${esc(c.detail)}</p>
        <button type="button" class="link" data-inspect="${c.r.home_island_id}">See the journey →</button>
      </article>`).join("") : `<p class="empty">Every ferry-served island can reach the hospital and get home the same day under this rule.</p>`;
  }

  function showJourney(islandId) {
    state.island = islandId;
    state.leftView = "journey";
    render();
    const left = document.querySelector(".left");
    if (left) left.scrollTop = 0;
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
    steps.push({ kind: "activity", t: settings.arriveBy, title: "Hospital appointment", text: `Until ${fmt(r.activity_end)} · ${fmtDur(settings.activityMin)} (assumed)` });
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

  function renderInspector() {
    const net = nets[state.atoll];
    const sel = $("#insp-island");
    if (!net) return;
    const ids = net.baseline.results.health.map((r) => r.home_island_id);
    const optsKey = ids.join(",");
    if (sel.dataset.key !== optsKey) {
      sel.innerHTML = ids.map((id) => `<option value="${id}">${esc(sname(id))}</option>`).join("");
      sel.dataset.key = optsKey;
    }
    if (!ids.includes(state.island)) state.island = ids[0];
    sel.value = state.island;
    const r = resOf(net.current, state.island);
    const b = resOf(net.baseline, state.island);
    const changed = active() && b.success !== r.success;
    const s = stopById[state.island];
    $("#insp-body").innerHTML = `
      <div class="insp-head">
        <div>
          <div class="insp-title">${esc(s.name)} → ${esc(sname(net.fx.hub))}</div>
          <div class="insp-sub">${s.dv ? `<span lang="dv">${esc(s.dv)}</span> · ` : ""}${popKnown ? `${units(r.population_weight)}` : "Population not loaded"}${s.approx ? " · position approximate" : ""}</div>
        </div>
        <div class="insp-pills">${r.success ? `<span class="pill good">Can make the trip</span>` : `<span class="pill bad">${esc(REASON[r.failure_reason])}</span>`}${changed ? `<span class="pill ${r.success ? "good" : "bad"}">${r.success ? "Fixed by this change" : "New problem"}</span>` : ""}</div>
      </div>
      <ol class="timeline">${timeline(r).map((st) => `<li class="step ${st.kind}"><span class="t mono">${st.t}</span><span class="dot" aria-hidden="true"></span><div><div class="st">${esc(st.title)}</div>${st.text ? `<div class="sx">${esc(st.text)}</div>` : ""}</div></li>`).join("")}</ol>
      ${r.success ? `<div class="burden"><div><span>${fmtDur(r.travel_minutes)}</span>on boats</div><div><span>${fmtDur(r.wait_minutes)}</span>waiting</div><div><span>${fmtDur(r.transfer_minutes)}</span>walking and changing</div></div>` : ""}`;
  }

  // ---- Sidebar -----------------------------------------------------------
  function buildTripOptions() {
    const sel = $("#trip");
    const ids = state.atoll ? tripsTouching(state.atoll).sort((a, b) => firstDep(a) - firstDep(b)) : [];
    sel.innerHTML = ids.map((id) => `<option value="${id}" data-sub="Departs ${fmt(firstDep(id))}${tripAtolls(id).size > 1 ? " · crosses atolls" : ""}">${esc(tripLabel(id))}</option>`).join("");
    if (state.editTrip) sel.value = state.editTrip;
  }

  function setupSidebar() {
    $("#atoll").innerHTML = `<option value="" data-sub="${Object.keys(nets).length} atolls with ferry data">All of the Maldives</option>` + geo.atolls
      .map((a) => `<option value="${a.id}" data-sub="${esc(a.alt)}"${nets[a.id] ? ' data-badge="Ferry data"' : ""}>${esc(a.name)}</option>`).join("");
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

    // Journey rule (assumption) controls
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
      const net = nets[state.atoll];
      if (!net) return;
      const o = M.optimize(net.fx, { candidates: tripsWithin(state.atoll) });
      state.suggestion = { atoll: state.atoll, ...o };
      renderSidebar();
    });
    $("#optimize-all").addEventListener("click", optimizeAll);
    document.querySelector(".side").addEventListener("click", (e) => {
      if (e.target.closest("#apply-suggestion")) { applyShifts(state.suggestion.shifts); state.suggestion = null; render(); }
      else if (e.target.closest("#dismiss-suggestion")) { state.suggestion = null; renderSidebar(); }
      else if (e.target.closest("#apply-national")) { applyShifts(state.national.shifts); state.national = null; render(); }
      else if (e.target.closest("#dismiss-national")) { state.national = null; renderSidebar(); }
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

  function optimizeAll() {
    if (state.busy) return;
    state.busy = true;
    const ids = Object.keys(nets);
    const out = { shifts: {}, perAtoll: [], evaluated: 0 };
    let i = 0;
    const btn = $("#optimize-all");
    (function step() {
      if (i >= ids.length) {
        state.busy = false; btn.disabled = false; btn.textContent = "Find better timetables for every atoll";
        state.national = out; renderSidebar(); return;
      }
      const id = ids[i++];
      btn.disabled = true; btn.textContent = `Checking ${atollById[id].name}…`;
      const o = M.optimize(nets[id].fx, { candidates: tripsWithin(id) });
      Object.assign(out.shifts, o.shifts);
      out.evaluated += o.evaluated;
      out.perAtoll.push({ id, o });
      setTimeout(step, 0);
    })();
  }

  function setShift(v) {
    if (!state.editTrip) return;
    state.shifts = { ...state.shifts, [state.editTrip]: Math.max(-240, Math.min(240, v)) };
    if (!state.shifts[state.editTrip]) delete state.shifts[state.editTrip];
    recompute(); render();
  }

  function syncControls() {
    const has = !!state.editTrip;
    $("#ferry-controls").hidden = !has;
    if (has) {
      const shift = state.shifts[state.editTrip] || 0;
      $("#trip").value = state.editTrip;
      $("#shift").value = shift;
      const from = firstDep(state.editTrip), to = from + shift;
      $("#shift-readout").innerHTML = shift === 0
        ? `Departs <b class="mono">${fmt(from)}</b> <span class="muted">as scheduled</span>`
        : `<span class="mono strike">${fmt(from)}</span> → <b class="mono">${to >= 0 && to <= 1439 ? fmt(to) : "--:--"}</b> <span class="muted">${shift > 0 ? "+" : "−"}${Math.abs(shift)} min, every stop</span>`;
    }
    const list = moved();
    $("#reset").disabled = !list.length;
    $("#moved").innerHTML = list.length
      ? list.map(([id, s]) => `<li><span class="moved-edit"><span>${esc(tripLabel(id))}</span><span class="mono">${fmt(firstDep(id))} → ${fmt(firstDep(id) + s)}</span></span><button type="button" class="x" data-unmove="${id}" aria-label="Put ${esc(tripLabel(id))} back">×</button></li>`).join("")
      : `<li class="none">No sailings moved. Results match the published schedule.</li>`;
    window.Dropdown.syncAll();
  }

  function suggestionHtml(o, scopeName) {
    const changes = Object.entries(o.shifts);
    const h = o.comparison.health;
    const unresolved = o.unresolved.filter((r) => r.journey_rule_id === "health");
    return `
      <div class="sug-head">${changes.length ? `${changes.length} change${changes.length === 1 ? "" : "s"} for ${esc(scopeName)}` : `No better timetable found for ${esc(scopeName)}`}</div>
      ${changes.length ? `<ol class="sug-list">${changes.map(([id, v]) => `<li><span>${esc(tripLabel(id))}</span><span class="mono"><span class="strike">${fmt(firstDep(id))}</span> → <b>${fmt(firstDep(id) + v)}</b></span></li>`).join("")}</ol>` : ""}
      <dl class="sug-result">
        <div><dt>Gain same-day access</dt><dd class="good"><b>+${units(h.gained)}</b></dd></div>
        <div><dt>Lose access</dt><dd>${n(h.lost)} <span class="muted">(not allowed)</span></dd></div>
      </dl>
      ${unresolved.length ? `<div class="sug-unres"><b>Still not fixed:</b> ${unresolved.map((r) => `${esc(sname(r.home_island_id))} (${esc(REASON[r.failure_reason].toLowerCase())})`).join("; ")}. These need a new sailing or a cross-atoll change.</div>` : ""}
      <div class="sug-actions">${changes.length ? `<button type="button" class="btn primary" id="apply-suggestion">Apply to the map</button>` : ""}<button type="button" class="btn" id="dismiss-suggestion">Dismiss</button></div>
      <p class="sug-note">Checked ${n(o.evaluated)} timetables. Only moves sailings within this atoll, in 15-min steps. Doesn't check boats, crews or cost.</p>`;
  }

  function renderSidebar() {
    const net = nets[state.atoll];
    $("#side-national").hidden = !!state.atoll;
    $("#side-nodata").hidden = !state.atoll || !!net;
    $("#side-atoll").hidden = !net;

    const st = $("#scenario-status");
    if (shiftError) { st.className = "status-line error"; st.textContent = `${shiftError} Showing the published schedule instead.`; }
    else if (active()) { st.className = "status-line"; st.textContent = `${moved().length} sailing${moved().length === 1 ? "" : "s"} moved. Same journey rule as the published schedule.`; }
    else { st.className = "status-line"; st.textContent = "Published schedule. Move a sailing to compare."; }

    if (!state.atoll) {
      const t = totals("current");
      $("#nat-summary").innerHTML = `${Object.keys(nets).length} atolls · ${D.trips.length} daily sailings · ${D.stops.length} island stops. ${t.failed ? `<b class="badtxt">${units(t.failed)} cut off</b> under the current rule.` : "Everyone modeled can make the trip."}`;
      const box = $("#national-suggestion");
      if (state.national) {
        const changes = Object.entries(state.national.shifts);
        const gained = state.national.perAtoll.reduce((s, x) => s + x.o.comparison.health.gained, 0);
        const unres = state.national.perAtoll.reduce((s, x) => s + x.o.unresolved.length, 0);
        box.hidden = false;
        box.innerHTML = `
          <div class="sug-head">${changes.length} sailing${changes.length === 1 ? "" : "s"} to move</div>
          <ol class="sug-list">${state.national.perAtoll.filter((x) => Object.keys(x.o.shifts).length).map((x) => `<li><span><b>${esc(atollById[x.id].name)}</b>: ${Object.entries(x.o.shifts).map(([id, v]) => `${routeName(id)} ${fmt(firstDep(id))} → ${fmt(firstDep(id) + v)}`).join(", ")}</span><span class="good">+${units(x.o.comparison.health.gained)}</span></li>`).join("") || "<li>Nothing to move under this rule.</li>"}</ol>
          <dl class="sug-result"><div><dt>Gain same-day access</dt><dd class="good"><b>+${units(gained)}</b></dd></div><div><dt>Lose access</dt><dd>0 <span class="muted">(not allowed)</span></dd></div><div><dt>Still cut off</dt><dd>${units(unres)} <span class="muted">(need new sailings)</span></dd></div></dl>
          <div class="sug-actions">${changes.length ? `<button type="button" class="btn primary" id="apply-national">Apply to the map</button>` : ""}<button type="button" class="btn" id="dismiss-national">Dismiss</button></div>
          <p class="sug-note">Checked ${n(state.national.evaluated)} timetables across ${state.national.perAtoll.length} atolls. Only sailings inside one atoll are moved.</p>`;
      } else box.hidden = true;
    }
    if (state.atoll && !net) {
      $("#nodata-name").textContent = `${atollById[state.atoll].name} (${atollById[state.atoll].alt})`;
      $("#nodata-text").textContent = FEED_ATOLLS.includes(state.atoll)
        ? "Only one island of this atoll is in the ferry feed, so there's no ferry journey to the hospital to model."
        : "The ferry feed has no sailings for this atoll yet. To model it, add:";
      $("#nodata-need").hidden = FEED_ATOLLS.includes(state.atoll);
    }
    if (net) {
      const a = atollById[state.atoll], f = facilityByAtoll[state.atoll];
      $("#atoll-name").textContent = `${a.name} (${a.alt})`;
      $("#atoll-hospital").innerHTML = `<span>${esc(f.name)}${f.name.startsWith("Atoll hospital") ? "" : ` on ${esc(sname(f.stop))}`}</span><span class="tag ${f.classification}">${esc(f.classification)}</span>`;
      $("#atoll-hospital-note").textContent = f.name.startsWith("Atoll hospital") ? `Assumed on ${sname(f.stop)}. ${f.note}.` : f.note;
      const box = $("#suggestion");
      if (state.suggestion && state.suggestion.atoll === state.atoll) { box.hidden = false; box.innerHTML = suggestionHtml(state.suggestion, a.name); }
      else box.hidden = true;
    }
    renderChanges();
  }

  function renderChanges() {
    const el = $("#changes");
    const cur = scopeSummary("current");
    if (!active() || !cur) { el.hidden = true; return; }
    el.hidden = false;
    const base = scopeSummary("baseline");
    const pp = cur.access_pct - base.access_pct;
    el.innerHTML = `<div class="change-row">
      <div class="change-head">${state.atoll ? esc(atollById[state.atoll].name) : "Maldives"}</div>
      <div class="change-nums">
        <span class="cn good">+${n(cur.gained)}</span><span class="cl">gain</span>
        <span class="cn ${cur.lost ? "bad" : "zero"}">−${n(cur.lost)}</span><span class="cl">lose</span>
        <span class="cn">${pp >= 0 ? "+" : "−"}${Math.abs(pp).toFixed(1)}</span><span class="cl">pp</span>
      </div>
      <div class="change-unit">${UNIT[1]} with same-day hospital access</div>
    </div>`;
  }

  // ---- Table + sources ---------------------------------------------------
  function renderTable() {
    if (!state.atoll) {
      $("#table-title").textContent = "Atolls";
      $("#table-hint").textContent = "Click a row to open the atoll.";
      const rows = geo.atolls.map((a) => {
        const net = nets[a.id];
        if (!net) return `<tr data-go-atoll="${a.id}" tabindex="0"><th scope="row">${esc(a.name)}</th><td colspan="5" class="muted">${FEED_ATOLLS.includes(a.id) ? "One island in the feed" : "No ferry data"}</td></tr>`;
        const s = net.current.summary.health, f = facilityByAtoll[a.id];
        return `<tr data-go-atoll="${a.id}" tabindex="0"><th scope="row">${esc(a.name)}</th><td>${esc(sname(f.stop))} <span class="tag ${f.classification}">${f.classification}</span></td>
          <td class="num">${n(s.eligible)}</td><td class="num">${n(s.success)}</td><td class="num ${s.failed ? "badtxt" : ""}">${n(s.failed)}</td><td class="num">${s.access_pct.toFixed(0)}%</td></tr>`;
      }).join("");
      $("#table").innerHTML = `<table><thead><tr><th>Atoll</th><th>Hospital island</th><th class="num">${UNIT[1]}</th><th class="num">Can make it</th><th class="num">Cut off</th><th class="num">Access</th></tr></thead><tbody>${rows}</tbody></table>`;
      return;
    }
    const net = nets[state.atoll];
    $("#table-title").textContent = `Islands in ${atollById[state.atoll].name}`;
    $("#table-hint").textContent = net ? "Click a row to see that island's journey." : "";
    if (!net) { $("#table").innerHTML = `<p class="empty" style="padding:14px">No ferry-served islands to list.</p>`; return; }
    const rows = net.current.results.health.map((r) => {
      const b = resOf(net.baseline, r.home_island_id);
      const was = active() && b.success !== r.success ? `<span class="was">was ${b.success ? "OK" : esc(REASON[b.failure_reason].toLowerCase())}</span>` : "";
      return `<tr data-island="${r.home_island_id}" class="${state.island === r.home_island_id ? "sel" : ""}" tabindex="0">
        <th scope="row">${esc(sname(r.home_island_id))}</th>
        <td>${r.success ? `<span class="pill good">Can make it</span>` : `<span class="pill bad">${esc(REASON[r.failure_reason])}</span>`}${was}</td>
        <td class="num mono">${r.facility_arrival != null ? fmt(r.facility_arrival) : "—"}</td>
        <td class="num mono">${r.home_arrival != null ? fmt(r.home_arrival) : "—"}</td>
        <td class="num">${r.success ? fmtDur(r.wait_minutes) : "—"}</td>
      </tr>`;
    }).join("");
    $("#table").innerHTML = `<table><thead><tr><th>Island</th><th>Hospital trip</th><th class="num">At hospital</th><th class="num">Home</th><th class="num">Waiting</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  function renderSources() {
    const obs = D.facilities.filter((f) => f.classification === "observed").length;
    const rows = [
      ["Ferry schedules", `data/ferry_schedules.csv → GTFS · ${new Set(D.trips.map((t) => t.route)).size} routes, ${D.trips.length} daily sailings`, "observed"],
      ["Operating days", "Not in the source; every route assumed to run daily", "assumed"],
      ["Island positions", `OpenStreetMap · ${D.stops.filter((s) => s.approx).length} approximate`, "observed"],
      ["Hospitals", `data/facilities.csv · ${obs} from OpenStreetMap, ${D.facilities.length - obs} assumed at the atoll capital`, "mixed"],
      ["Population", popKnown ? "data/island_population.csv" : "Not loaded yet. Each island counts once. Add Census 2022 figures to data/island_population.csv", popKnown ? "observed" : "missing"],
      ["Map outlines", "OpenStreetMap coastline and reefs, simplified", "observed"],
      ["Journey rule", "Set in the sidebar", "assumed"],
    ];
    $("#sources").innerHTML = rows.map(([a, b, c]) => `<tr><th scope="row">${a}</th><td>${esc(b)}</td><td><span class="tag ${c}">${c}</span></td></tr>`).join("");
    $("#rules").innerHTML = [
      ...(D.meta.assumptions || []),
      "Residents go to their own atoll's hospital, leave home from 05:00 and must be home by the set time.",
      "Changing boats needs the set buffer; one time per stop means a boat's arrival and departure are the same minute.",
      "Suggested timetables only move existing sailings inside one atoll (15-min steps, up to 4 h, 05:00–22:00) and never cost anyone access.",
    ].map((t) => `<li>${esc(t)}</li>`).join("");
  }

  function render() {
    renderMap();
    renderKpis();
    renderLeft();
    renderSidebar();
    renderTable();
    syncControls();
  }

  // ---- Events ------------------------------------------------------------
  document.addEventListener("click", (e) => {
    const insp = e.target.closest("[data-inspect]");
    if (insp) { showJourney(insp.dataset.inspect); return; }
    if (e.target.closest("#back")) { state.leftView = "cards"; render(); return; }
    const go = e.target.closest("[data-go-atoll]");
    if (go && !go.closest("#mapsvg")) { selectAtoll(go.dataset.goAtoll); window.scrollTo({ top: 0, behavior: "smooth" }); return; }
    const row = e.target.closest("tr[data-island]");
    if (row) { showJourney(row.dataset.island); window.scrollTo({ top: 0, behavior: "smooth" }); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest && e.target.closest("tr[data-island], tr[data-go-atoll]");
    if (!row) return;
    e.preventDefault();
    if (row.dataset.island) showJourney(row.dataset.island); else selectAtoll(row.dataset.goAtoll);
    window.scrollTo({ top: 0 });
  });
  $("#insp-island").addEventListener("change", (e) => { state.island = e.target.value; render(); });

  rebuild();
  setupSidebar();
  window.Dropdown.enhance($("#insp-island"));
  renderSources();
  buildTripOptions();
  render();
})();
