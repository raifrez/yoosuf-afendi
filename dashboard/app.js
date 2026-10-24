// M.A.N.D.A.R.I.N dashboard UI. Every number on screen comes from the
// simulator output (window.Mandarin.run), never from hand-written copy.

(function () {
  const fx = window.MANDARIN_FIXTURE;
  const M = window.Mandarin;
  const { fmt, fmtDur, toMin } = M;

  const islandById = Object.fromEntries(fx.islands.map((i) => [i.id, i]));
  const ruleById = Object.fromEntries(fx.rules.map((r) => [r.id, r]));
  const hub = islandById[fx.hub];
  const DAY_NAMES = { sun: "Sun", mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat" };
  const WEEKDAY_LONG = { sun: "Sundays", mon: "Mondays", tue: "Tuesdays", wed: "Wednesdays", thu: "Thursdays", fri: "Fridays", sat: "Saturdays" };

  const state = { tripId: "T-B1", shift: 0, island: "D", rule: "health" };
  const baseline = M.run(fx, null);
  let current = baseline;
  let comparison = null;
  let scenarioError = null;

  const $ = (sel) => document.querySelector(sel);
  const n = (v) => Math.round(v).toLocaleString("en-US");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const name = (id) => islandById[id].name;
  const active = () => state.shift !== 0 && !scenarioError;
  const resultFor = (run, ruleId, islandId) => run.results[ruleId].find((r) => r.home_island_id === islandId);

  function tripLabel(trip) {
    const a = trip.stops[0], b = trip.stops[trip.stops.length - 1];
    return `${name(a.island)} → ${name(b.island)}`;
  }
  const origTrip = (id) => baseline.trips.find((t) => t.id === id);

  function rerun() {
    if (state.shift === 0) {
      current = baseline; comparison = null; scenarioError = null;
    } else {
      const r = M.run(fx, { tripId: state.tripId, shiftMin: state.shift });
      if (r.error) { scenarioError = r.error; current = baseline; comparison = null; }
      else { scenarioError = null; current = r; comparison = M.compare(baseline, r); }
    }
    render();
  }

  // ---- Scenario controls -------------------------------------------------
  function setupControls() {
    const sel = $("#trip");
    sel.innerHTML = baseline.trips
      .map((t) => {
        const off = !t.days.includes(fx.meta.weekday);
        return `<option value="${t.id}">${esc(tripLabel(t))} · ${fmt(t.stops[0].dep)}${off ? " (not running today)" : ""}</option>`;
      })
      .join("");
    sel.value = state.tripId;
    sel.addEventListener("change", () => { state.tripId = sel.value; state.shift = 0; syncControls(); rerun(); });

    const range = $("#shift");
    range.addEventListener("input", () => { state.shift = Number(range.value); syncControls(); rerun(); });
    $("#earlier").addEventListener("click", () => step(-15));
    $("#later").addEventListener("click", () => step(15));
    $("#reset").addEventListener("click", () => { state.shift = 0; syncControls(); rerun(); });

    $("#presets").innerHTML = fx.presets
      .map((p, i) => `<button type="button" class="chip" data-preset="${i}">${esc(p.label)}${p.note ? ` <span class="chip-note">${esc(p.note)}</span>` : ""}</button>`)
      .join("");
    $("#presets").addEventListener("click", (e) => {
      const b = e.target.closest("[data-preset]");
      if (!b) return;
      const p = fx.presets[Number(b.dataset.preset)];
      state.tripId = p.tripId; state.shift = p.shiftMin;
      syncControls(); rerun();
      // Point the inspector at the island this preset is about.
      const first = comparison && Object.values(comparison).flatMap((c) => c.changes)[0];
      if (first) { state.island = first.home_island_id; state.rule = first.journey_rule_id; render(); }
    });
  }
  function step(d) {
    state.shift = Math.max(-180, Math.min(180, state.shift + d));
    syncControls(); rerun();
  }
  function syncControls() {
    $("#trip").value = state.tripId;
    $("#shift").value = state.shift;
    const t = origTrip(state.tripId);
    const from = t.stops[0].dep, to = from + state.shift;
    const sign = state.shift > 0 ? "+" : state.shift < 0 ? "−" : "±";
    $("#shift-readout").innerHTML = state.shift === 0
      ? `Departs <b class="mono">${fmt(from)}</b> <span class="muted">(timetable)</span>`
      : `<span class="mono strike">${fmt(from)}</span> → <b class="mono">${to >= 0 && to <= 1439 ? fmt(to) : "--:--"}</b> <span class="muted">${sign}${Math.abs(state.shift)} min</span>`;
    $("#reset").disabled = state.shift === 0;
  }

  // ---- Rendering ---------------------------------------------------------
  function render() {
    renderStatus();
    renderKpis();
    renderChanges();
    renderCards();
    renderMap();
    renderInspector();
    renderTable();
  }

  function renderStatus() {
    const el = $("#scenario-status");
    if (scenarioError) {
      el.className = "status-line error";
      el.textContent = scenarioError + " Showing the baseline timetable.";
    } else if (active()) {
      const t = origTrip(state.tripId);
      el.className = "status-line";
      el.innerHTML = `Comparing with baseline: <b>${esc(tripLabel(t))}</b> moved from <span class="mono">${fmt(t.stops[0].dep)}</span> to <span class="mono">${fmt(t.stops[0].dep + state.shift)}</span>. Same population and journey rules.`;
    } else {
      el.className = "status-line";
      el.textContent = "Showing the baseline timetable. Move a ferry or pick an example to compare.";
    }
  }

  function delta(value, goodWhenUp, unit) {
    if (!active() || value == null || Math.abs(value) < 0.05) return active() ? `<span class="delta flat">No change</span>` : "";
    const up = value > 0;
    const good = up === goodWhenUp;
    const txt = unit === "pp" ? `${up ? "+" : "−"}${Math.abs(value).toFixed(1)} pp` : `${up ? "+" : "−"}${n(Math.abs(value))}`;
    return `<span class="delta ${good ? "good" : "bad"}">${up ? "▲" : "▼"} ${txt} vs baseline</span>`;
  }

  function renderKpis() {
    const h = current.summary.health, hb = baseline.summary.health;
    const s = current.summary.school, sb = baseline.summary.school;
    const noRet = h.by_reason.no_return || 0, noRetB = hb.by_reason.no_return || 0;
    const sr = current.results.school;
    const late = sr.filter((r) => r.failure_reason === "late_arrival").reduce((a, r) => a + r.population_weight, 0);
    const strand = sr.filter((r) => r.failure_reason === "no_return").reduce((a, r) => a + r.population_weight, 0);
    const none = s.failed - late - strand;

    const tiles = [
      { label: "Same-day hospital access", value: h.access_pct == null ? "n/a" : `${h.access_pct.toFixed(1)}%`,
        sub: `${n(h.success)} of ${n(h.eligible)} modeled residents`, d: delta(h.access_pct - hb.access_pct, true, "pp"), tone: "" },
      { label: "Residents without same-day hospital access", value: n(h.failed),
        sub: "Can't arrive by 10:00 and get home by 18:00", d: delta(h.failed - hb.failed, false), tone: h.failed ? "bad" : "good" },
      { label: "Reach the hospital but can't get home", value: n(noRet),
        sub: "No ferry back after the appointment", d: delta(noRet - noRetB, false), tone: noRet ? "bad" : "good" },
      { label: "Secondary students missing the full school day", value: `${n(s.failed)}<span class="of"> / ${n(s.eligible)}</span>`,
        sub: `${n(late)} arrive late · ${n(strand)} can't get home · ${n(none)} have no route`, d: delta(s.failed - sb.failed, false), tone: s.failed ? "bad" : "good" },
    ];
    $("#kpis").innerHTML = tiles
      .map((t) => `<div class="kpi ${t.tone}"><div class="kpi-label">${t.label}</div><div class="kpi-value">${t.value}</div><div class="kpi-sub">${t.sub}</div>${t.d}</div>`)
      .join("");
  }

  function renderChanges() {
    const el = $("#changes");
    if (!active()) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = fx.rules
      .map((rule) => {
        const c = comparison[rule.id];
        const unit = rule.id === "health" ? "residents" : "students";
        const list = c.changes.length
          ? c.changes.map((x) => `<li class="${x.change}"><b>${esc(name(x.home_island_id))}</b> ${x.change === "gained" ? "gains" : "loses"} access · ${n(x.population_weight)} ${unit}</li>`).join("")
          : `<li class="none">No island changes</li>`;
        return `<div class="change-col">
          <div class="change-head">${esc(rule.label)}</div>
          <div class="change-nums">
            <div><span class="cn good">+${n(c.gained)}</span><span class="cl">gained</span></div>
            <div><span class="cn ${c.lost ? "bad" : ""}">−${n(c.lost)}</span><span class="cl">lost</span></div>
            <div><span class="cn">${c.net >= 0 ? "+" : "−"}${n(Math.abs(c.net))}</span><span class="cl">net ${unit}</span></div>
            <div><span class="cn">${c.pp == null ? "n/a" : `${c.pp >= 0 ? "+" : "−"}${Math.abs(c.pp).toFixed(1)}`}</span><span class="cl">pp access</span></div>
          </div>
          <ul class="change-list">${list}</ul>
        </div>`;
      })
      .join("");
  }

  // ---- Impact cards ------------------------------------------------------
  const REASON_PILL = {
    late_arrival: "Arrives late",
    no_return: "Stranded after",
    missed_connection: "Missed connection",
    no_service: "No ferry today",
    no_route: "No route",
  };

  function pctOfSchoolAge(r) {
    const isl = islandById[r.home_island_id];
    return Math.round((r.population_weight / isl.schoolAge) * 100);
  }

  function describeFailure(r) {
    const rule = ruleById[r.journey_rule_id];
    const isl = name(r.home_island_id);
    const school = rule.id === "school";
    const big = school ? `${pctOfSchoolAge(r)}%` : n(r.population_weight);
    const bigUnit = school ? "of school-age children" : "residents";
    const studentsLine = `They're the ${n(r.population_weight)} secondary students who travel to ${hub.name}.`;
    let head = "", detail = "";
    switch (r.failure_reason) {
      case "late_arrival":
        head = school
          ? `on ${isl} reach school ${fmtDur(r.minutes_late)} late`
          : `on ${isl} can't make a ${rule.arriveBy} hospital appointment`;
        detail = school
          ? `${studentsLine} The first ferry leaves at ${fmt(r.legs[0].dep)}, and classes start at ${rule.arriveBy}.`
          : `The first ferry leaves at ${fmt(r.legs[0].dep)} and gets them to the hospital at ${fmt(r.facility_arrival)}, ${fmtDur(r.minutes_late)} after the appointment starts.`;
        break;
      case "no_return": {
        const last = r.evidence.last_workable_departure;
        head = school ? `on ${isl} can get to school but not home again` : `on ${isl} can reach the hospital but can't get home the same day`;
        const ends = `${school ? "Classes end" : `A ${rule.arriveBy} appointment ends`} at ${fmt(r.activity_end)}`;
        detail = last != null
          ? `${ends}. The last ferry that gets them home leaves at ${fmt(last)}.`
          : `${ends}, and no ferry goes back to ${isl} today.`;
        if (school) detail = `${studentsLine} ${detail}`;
        break;
      }
      case "missed_connection": {
        const e = r.evidence;
        head = school ? `on ${isl} miss their connection to school` : `on ${isl} miss their connection to the hospital`;
        detail = `Their ferry reaches ${name(e.at)} at ${fmt(e.arrived)}. The onward ferry leaves at ${fmt(e.departs)}, only ${e.gap} min later; changing boats safely takes ${e.needed} min.`;
        break;
      }
      case "no_service": {
        const days = r.evidence.days_running.map((d) => DAY_NAMES[d]).join(", ");
        head = school ? `on ${isl} have no ferry to school on ${WEEKDAY_LONG[fx.meta.weekday]}` : `on ${isl} have no ferry to the hospital on ${WEEKDAY_LONG[fx.meta.weekday]}`;
        detail = days ? `${isl}'s ferry only runs on ${days}.` : `No ferry serves ${isl} at all.`;
        if (school) detail = `${studentsLine} ${detail}`;
        break;
      }
      default:
        head = `on ${isl} have no ferry route to ${hub.name}`;
        detail = "No combination of today's ferries reaches the destination.";
    }
    return { big, bigUnit, head, detail };
  }

  function renderCards() {
    const cards = [];
    for (const rule of fx.rules) {
      for (const r of current.results[rule.id]) {
        const b = resultFor(baseline, rule.id, r.home_island_id);
        if (!r.success) {
          const d = describeFailure(r);
          const isNew = active() && b.success;
          cards.push({ r, sort: isNew ? 1 : 2, weight: r.population_weight, tone: "bad",
            pill: isNew ? "New problem from this change" : REASON_PILL[r.failure_reason], ...d });
        } else if (active() && !b.success) {
          const isl = name(r.home_island_id);
          const school = rule.id === "school";
          cards.push({ r, sort: 0, weight: r.population_weight, tone: "good", pill: "Fixed by this change",
            big: school ? `${pctOfSchoolAge(r)}%` : n(r.population_weight),
            bigUnit: school ? "of school-age children" : "residents",
            head: school ? `on ${isl} now make the full school day` : `on ${isl} can now reach the hospital and get home the same day`,
            detail: `Before: ${describeFailure(b).head.replace(/^on [^ ]+ [^ ]+ /, "")}. Now they arrive at ${fmt(r.facility_arrival)} and are home by ${fmt(r.home_arrival)}.` });
        } else if (rule.id === "health" && r.wait_before_minutes >= 90) {
          cards.push({ r, sort: 3, weight: r.population_weight, tone: "warn", pill: "Works, with a long wait",
            big: fmtDur(r.wait_before_minutes), bigUnit: "waiting",
            head: `before a ${rule.arriveBy} appointment for residents of ${name(r.home_island_id)}`,
            detail: `Their only morning ferry arrives at ${fmt(r.legs[r.legs.length - 1].arr)}. A full hospital visit takes them from ${fmt(r.legs[0].dep)} to ${fmt(r.home_arrival)}.` });
        }
      }
    }
    cards.sort((a, b) => a.sort - b.sort || b.weight - a.weight);
    $("#card-count").textContent = cards.filter((c) => c.tone === "bad").length
      ? `${cards.filter((c) => c.tone === "bad").length} barriers found`
      : "No barriers found";
    $("#cards").innerHTML = cards
      .map((c) => `<article class="impact ${c.tone}">
        <div class="impact-top"><span class="pill ${c.tone}">${esc(c.pill)}</span><span class="impact-rule">${esc(ruleById[c.r.journey_rule_id].short)}</span></div>
        <div class="impact-big">${c.big}<span class="impact-unit">${esc(c.bigUnit)}</span></div>
        <p class="impact-head">${esc(c.head)}</p>
        <p class="impact-detail">${esc(c.detail)}</p>
        <button type="button" class="link" data-inspect="${c.r.home_island_id}|${c.r.journey_rule_id}">See the journey →</button>
      </article>`)
      .join("");
  }

  // ---- Map ---------------------------------------------------------------
  function statusOf(run, ruleId, islandId) {
    if (islandId === fx.hub) return "hub";
    const r = resultFor(run, ruleId, islandId);
    if (!r) return "na";
    return r.success ? "ok" : "bad";
  }

  function renderMap() {
    const pairs = new Map();
    for (const t of current.trips) {
      for (let i = 0; i < t.stops.length - 1; i++) {
        const a = t.stops[i].island, b = t.stops[i + 1].island;
        const key = [a, b].sort().join("-");
        const p = pairs.get(key) || { a, b, today: false, edited: false };
        if (t.days.includes(fx.meta.weekday)) p.today = true;
        if (active() && t.id === state.tripId) p.edited = true;
        pairs.set(key, p);
      }
    }
    const lines = [...pairs.values()]
      .map((p) => {
        const A = islandById[p.a], B = islandById[p.b];
        const cls = p.edited ? "route edited" : p.today ? "route" : "route off";
        return `<line class="${cls}" x1="${A.x}" y1="${A.y}" x2="${B.x}" y2="${B.y}"/>`;
      })
      .join("");

    const nodes = fx.islands
      .map((isl) => {
        const st = statusOf(current, state.rule, isl.id);
        const r = Math.round(10 + Math.sqrt(isl.population) / 3.2);
        const sel = state.island === isl.id;
        let caption;
        if (st === "hub") caption = state.rule === "health" ? "Hospital" : "Secondary school";
        else if (st === "na") caption = "Own school";
        else {
          const res = resultFor(current, state.rule, isl.id);
          caption = res.success ? "Can make the trip" : REASON_PILL[res.failure_reason];
        }
        const ly = isl.y + r + 16;
        return `<g class="isl ${st}${sel ? " sel" : ""}" data-island="${isl.id}" tabindex="${isl.id === fx.hub ? -1 : 0}" role="button" aria-label="${esc(isl.name)}: ${esc(caption)}">
          ${sel ? `<circle class="sel-ring" cx="${isl.x}" cy="${isl.y}" r="${r + 7}"/>` : ""}
          <circle class="land" cx="${isl.x}" cy="${isl.y}" r="${r}"/>
          ${st === "hub" ? `<path class="cross" d="M${isl.x - 7} ${isl.y}h14M${isl.x} ${isl.y - 7}v14"/>` : ""}
          <text class="isl-name" x="${isl.x}" y="${ly}">${esc(isl.name)}</text>
          <text class="isl-cap" x="${isl.x}" y="${ly + 14}">${esc(caption)}</text>
        </g>`;
      })
      .join("");

    $("#map").innerHTML = `<svg viewBox="0 0 600 430" role="img" aria-label="Schematic map of the demo atoll">
      <rect class="sea" x="0" y="0" width="600" height="430" rx="0"/>
      ${lines}${nodes}
    </svg>`;
    document.querySelectorAll("[data-lens]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lens === state.rule)));
  }

  // ---- Journey inspector -------------------------------------------------
  function timeline(r) {
    const rule = ruleById[r.journey_rule_id];
    const steps = [];
    const ride = (l) => steps.push({ kind: "ride", t: fmt(l.dep), title: `Ferry ${name(l.from)} → ${name(l.to)}`, text: `Arrives ${fmt(l.arr)} · ${fmtDur(l.arr - l.dep)} on board`, trip: l.trip_id });
    const rideAll = (legs) => legs.forEach((l, i) => {
      if (i > 0) steps.push({ kind: "wait", t: fmt(legs[i - 1].arr), title: `Change boats at ${name(l.from)}`, text: `${fmtDur(l.dep - legs[i - 1].arr)} between ferries` });
      ride(l);
    });
    const activity = rule.id === "health" ? "Hospital appointment" : "School day";

    if (r.failure_reason === "no_service") {
      steps.push({ kind: "fail", t: "—", title: `No ferry leaves ${name(r.home_island_id)} today`, text: describeFailure(r).detail });
      return steps;
    }
    if (r.failure_reason === "no_route") {
      steps.push({ kind: "fail", t: "—", title: "No route", text: describeFailure(r).detail });
      return steps;
    }
    if (r.failure_reason === "missed_connection") {
      const e = r.evidence;
      const idx = r.legs.findIndex((l) => l.from === e.at && l.dep === e.departs);
      r.legs.slice(0, idx).forEach((l, i, arr) => { if (i > 0) steps.push({ kind: "wait", t: fmt(arr[i - 1].arr), title: `Change boats at ${name(l.from)}`, text: "" }); ride(l); });
      steps.push({ kind: "fail", t: fmt(e.arrived), title: `Missed connection at ${name(e.at)}`, text: `The ferry to ${hub.name} leaves at ${fmt(e.departs)}, ${e.gap} min after they dock. Changing boats needs ${e.needed} min, and there's no later ferry that arrives in time.` });
      return steps;
    }

    rideAll(r.legs);
    const harbour = r.legs[r.legs.length - 1].arr;
    steps.push({ kind: "walk", t: fmt(harbour), title: `Walk to the ${rule.id === "health" ? "hospital" : "school"}`, text: `${r.walk_minutes} min from the harbour` });

    if (r.failure_reason === "late_arrival") {
      steps.push({ kind: "fail", t: fmt(r.facility_arrival), title: `Arrives ${fmtDur(r.minutes_late)} late`, text: `${activity} starts at ${rule.arriveBy}.` });
      return steps;
    }
    const waitBefore = r.arrive_by - r.facility_arrival;
    if (waitBefore > 0) steps.push({ kind: "wait", t: fmt(r.facility_arrival), title: "Wait", text: `${fmtDur(waitBefore)} before it starts` });
    steps.push({ kind: "activity", t: rule.arriveBy, title: activity, text: `Until ${fmt(r.activity_end)} · ${fmtDur(rule.activityMin)}` });
    steps.push({ kind: "walk", t: fmt(r.activity_end), title: "Walk back to the harbour", text: `${r.walk_minutes} min` });

    if (r.failure_reason === "no_return") {
      const last = r.evidence.last_workable_departure;
      steps.push({ kind: "fail", t: fmt(r.evidence.return_ready), title: "No ferry home today", text: last != null ? `The last ferry that gets them home left at ${fmt(last)}.` : `No ferry reaches ${name(r.home_island_id)} by ${rule.homeBy}.` });
      return steps;
    }
    const waitAfter = r.return_legs[0].dep - (r.activity_end + r.walk_minutes);
    if (waitAfter > 0) steps.push({ kind: "wait", t: fmt(r.activity_end + r.walk_minutes), title: "Wait for the ferry home", text: fmtDur(waitAfter) });
    rideAll(r.return_legs);
    steps.push({ kind: "home", t: fmt(r.home_arrival), title: `Home on ${name(r.home_island_id)}`, text: `Whole trip ${fmtDur(r.home_arrival - r.legs[0].dep)}` });
    return steps;
  }

  function renderInspector() {
    const sel = $("#insp-island");
    if (!sel.options.length) {
      sel.innerHTML = fx.islands.filter((i) => i.id !== fx.hub).map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("");
      sel.addEventListener("change", () => { state.island = sel.value; render(); });
    }
    sel.value = state.island;
    document.querySelectorAll("[data-rule-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.ruleTab === state.rule)));

    const body = $("#insp-body");
    const r = resultFor(current, state.rule, state.island);
    const isl = islandById[state.island];
    if (!r) {
      body.innerHTML = `<p class="empty">${esc(isl.name)} has its own secondary school, so its students aren't modeled as travelling. Pick another island or switch to the hospital trip.</p>`;
      return;
    }
    const b = resultFor(baseline, state.rule, state.island);
    const changed = active() && b.success !== r.success;
    const statusPill = r.success
      ? `<span class="pill good">Can make the trip</span>`
      : `<span class="pill bad">${esc(REASON_PILL[r.failure_reason])}</span>`;
    const who = state.rule === "health" ? "residents" : "secondary students";
    const burden = r.success
      ? `<div class="burden">
          <div><span>${fmtDur(r.travel_minutes)}</span>on boats</div>
          <div><span>${fmtDur(r.wait_minutes)}</span>waiting</div>
          <div><span>${fmtDur(r.transfer_minutes)}</span>walking and changing</div>
        </div>`
      : "";
    body.innerHTML = `
      <div class="insp-head">
        <div>
          <div class="insp-title">${esc(isl.name)} · ${esc(ruleById[state.rule].label.toLowerCase())}</div>
          <div class="insp-sub">Synthetic group <span class="mono">${esc(r.group_id)}</span> represents <b>${n(r.population_weight)} ${who}</b>. Not a real person.</div>
        </div>
        <div class="insp-pills">${statusPill}${changed ? `<span class="pill ${r.success ? "good" : "bad"}">${r.success ? "Fixed by this change" : "New problem"}</span>` : ""}</div>
      </div>
      <ol class="timeline">${timeline(r)
        .map((s) => `<li class="step ${s.kind}"><span class="t mono">${s.t}</span><span class="dot" aria-hidden="true"></span><div><div class="st">${esc(s.title)}${s.trip ? ` <span class="trip mono">${esc(s.trip)}</span>` : ""}</div>${s.text ? `<div class="sx">${esc(s.text)}</div>` : ""}</div></li>`)
        .join("")}</ol>
      ${burden}`;
  }

  // ---- Island table ------------------------------------------------------
  function cell(run, ruleId, islandId) {
    const r = resultFor(run, ruleId, islandId);
    if (!r) return `<span class="muted">Own school</span>`;
    const b = resultFor(baseline, ruleId, islandId);
    const was = active() && b.success !== r.success ? `<span class="was">was ${b.success ? "OK" : esc(REASON_PILL[b.failure_reason].toLowerCase())}</span>` : "";
    return r.success
      ? `<span class="pill good">Can make it</span>${was}`
      : `<span class="pill bad">${esc(REASON_PILL[r.failure_reason])}</span>${was}`;
  }

  function renderTable() {
    const rows = fx.islands.filter((i) => i.id !== fx.hub).map((isl) => {
      const h = resultFor(current, "health", isl.id);
      const s = resultFor(current, "school", isl.id);
      return `<tr data-island="${isl.id}" class="${state.island === isl.id ? "sel" : ""}" tabindex="0">
        <th scope="row">${esc(isl.name)}</th>
        <td class="num">${n(isl.population)}</td>
        <td>${cell(current, "health", isl.id)}</td>
        <td class="num">${h.success ? fmtDur(h.wait_minutes) : "—"}</td>
        <td class="num">${s ? n(s.population_weight) : `<span class="muted">${n(isl.secondaryStudents)}</span>`}</td>
        <td>${cell(current, "school", isl.id)}</td>
      </tr>`;
    }).join("");
    $("#table").innerHTML = `<table>
      <thead><tr><th scope="col">Island</th><th scope="col" class="num">Residents</th><th scope="col">Hospital trip</th><th scope="col" class="num">Waiting</th><th scope="col" class="num">Secondary students</th><th scope="col">School trip</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }

  function renderSources() {
    $("#sources").innerHTML = fx.sources
      .map((s) => `<tr><th scope="row">${esc(s.dataset)}</th><td>${esc(s.planned)}</td><td><span class="tag ${s.classification}">${esc(s.classification)}</span></td></tr>`)
      .join("");
    const h = ruleById.health, sc = ruleById.school;
    $("#rules").innerHTML = `
      <li><b>Hospital trip:</b> arrive by ${h.arriveBy}, ${fmtDur(h.activityMin)} appointment, home by ${h.homeBy}.</li>
      <li><b>School day:</b> arrive by ${sc.arriveBy}, classes until ${fmt(toMin(sc.arriveBy) + sc.activityMin)}, home by ${sc.homeBy}. Only islands without a secondary school are modeled.</li>
      <li><b>Changing boats</b> needs at least ${fx.transferBufferMin} min. Walking between harbour and facility takes ${hub.harbourToFacilityMin} min.</li>
      <li><b>Operating day:</b> ${DAY_NAMES[fx.meta.weekday]} ${fx.meta.operatingDate}. Same-day trips only; overnight shifts are rejected.</li>
      <li><b>Waiting</b> counts time before the appointment and at the harbour for the ferry home. Times are for successful journeys only.</li>`;
  }

  // ---- Events ------------------------------------------------------------
  document.addEventListener("click", (e) => {
    const insp = e.target.closest("[data-inspect]");
    if (insp) {
      const [isl, rule] = insp.dataset.inspect.split("|");
      state.island = isl; state.rule = rule; render();
      $("#inspector").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      return;
    }
    const lens = e.target.closest("[data-lens]");
    if (lens) { state.rule = lens.dataset.lens; render(); return; }
    const tab = e.target.closest("[data-rule-tab]");
    if (tab) { state.rule = tab.dataset.ruleTab; render(); return; }
    const isl = e.target.closest("[data-island]");
    if (isl && isl.dataset.island !== fx.hub) { state.island = isl.dataset.island; render(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const isl = e.target.closest && e.target.closest("[data-island]");
    if (isl && isl.dataset.island !== fx.hub) { e.preventDefault(); state.island = isl.dataset.island; render(); }
  });

  setupControls();
  syncControls();
  renderSources();
  render();
})();
