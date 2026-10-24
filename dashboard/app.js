// M.A.N.D.A.R.I.N dashboard UI. Every number on screen comes from the
// simulator output (window.Mandarin.run), never from hand-written copy.

(function () {
  const fx = window.MANDARIN_FIXTURE;
  const geo = window.MALDIVES_GEO;
  const M = window.Mandarin;
  const { fmt, fmtDur, toMin } = M;

  const islandById = Object.fromEntries(fx.islands.map((i) => [i.id, i]));
  const ruleById = Object.fromEntries(fx.rules.map((r) => [r.id, r]));
  const atollById = Object.fromEntries(geo.atolls.map((a) => [a.id, a]));
  const hub = islandById[fx.hub];
  const demoAtoll = atollById[fx.atollId];
  const DAY_NAMES = { sun: "Sun", mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat" };
  const WEEKDAY_LONG = { sun: "Sundays", mon: "Mondays", tue: "Tuesdays", wed: "Wednesdays", thu: "Thursdays", fri: "Fridays", sat: "Saturdays" };

  const state = { leftView: "cards", atoll: null, editTrip: "T-B1", shifts: {}, island: "D", rule: "health", reduceWait: false, suggestion: null };
  const baseline = M.run(fx, null);
  let current = baseline;
  let comparison = null;
  let scenarioError = null;

  const $ = (sel) => document.querySelector(sel);
  const n = (v) => Math.round(v).toLocaleString("en-US");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const name = (id) => islandById[id].name;
  const moved = () => Object.entries(state.shifts).filter(([, v]) => v);
  const active = () => moved().length > 0 && !scenarioError;
  const resultFor = (run, ruleId, islandId) => run.results[ruleId].find((r) => r.home_island_id === islandId);
  const origTrip = (id) => baseline.trips.find((t) => t.id === id);
  const signed = (v, digits = 0) => `${v >= 0 ? "+" : "−"}${digits ? Math.abs(v).toFixed(digits) : n(Math.abs(v))}`;

  function tripLabel(trip) {
    const a = trip.stops[0], b = trip.stops[trip.stops.length - 1];
    return `${name(a.island)} → ${name(b.island)}`;
  }

  function rerun() {
    if (!moved().length) {
      current = baseline; comparison = null; scenarioError = null;
    } else {
      const r = M.run(fx, { shifts: state.shifts });
      if (r.error) { scenarioError = r.error; current = baseline; comparison = null; }
      else { scenarioError = null; current = r; comparison = M.compare(baseline, r); }
    }
    render();
  }

  // ---- Map ---------------------------------------------------------------
  const map = window.MandarinMap.createMap($("#mapsvg"), geo, {
    onAtoll: (id) => selectAtoll(id),
    onIsland: (id) => { if (id !== fx.hub) showJourney(id); },
  });

  function selectAtoll(id) {
    state.atoll = id || null;
    map.zoomTo(state.atoll);
    $("#atoll").value = state.atoll || "";
    render();
  }

  function pinXY(isl) {
    const [x0, y0, x1, y1] = map.bboxOf(fx.atollId);
    const w = x1 - x0, h = y1 - y0;
    return [x0 + w * (0.1 + 0.8 * (isl.x / 600)), y0 + h * (0.1 + 0.8 * (isl.y / 430))];
  }

  function statusOf(ruleId, islandId) {
    if (islandId === fx.hub) return "hub";
    const r = resultFor(current, ruleId, islandId);
    if (!r) return "na";
    return r.success ? "ok" : "bad";
  }

  function renderMap() {
    map.setState({ atollId: state.atoll, demoAtollId: fx.atollId });
    $("#map-lens").hidden = state.atoll !== fx.atollId;
    $("#map-legend-net").hidden = state.atoll !== fx.atollId;
    $("#map-hint").hidden = !!state.atoll;
    document.querySelectorAll("[data-lens]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lens === state.rule)));
    if (state.atoll !== fx.atollId) { map.setNetwork(null); return; }

    const pos = Object.fromEntries(fx.islands.map((i) => [i.id, pinXY(i)]));
    const editedIds = new Set(active() ? moved().map(([id]) => id) : []);
    const pairs = new Map();
    for (const t of current.trips) {
      for (let i = 0; i < t.stops.length - 1; i++) {
        const a = t.stops[i].island, b = t.stops[i + 1].island;
        const key = [a, b].sort().join("-");
        const p = pairs.get(key) || { a, b, today: false, edited: false };
        if (t.days.includes(fx.meta.weekday)) p.today = true;
        if (editedIds.has(t.id)) p.edited = true;
        pairs.set(key, p);
      }
    }
    const routes = [...pairs.values()].map((p) => ({
      x1: pos[p.a][0], y1: pos[p.a][1], x2: pos[p.b][0], y2: pos[p.b][1],
      kind: p.edited ? "edited" : p.today ? "today" : "off",
    }));
    const nodes = fx.islands.map((isl) => {
      const st = statusOf(state.rule, isl.id);
      let caption;
      if (st === "hub") caption = "Hospital · secondary school";
      else if (st === "na") caption = "Own secondary school";
      else {
        const r = resultFor(current, state.rule, isl.id);
        caption = r.success ? "Can make the trip" : REASON_PILL[r.failure_reason];
      }
      return {
        id: isl.id, x: pos[isl.id][0], y: pos[isl.id][1], r: Math.round(7 + Math.sqrt(isl.population) / 4.5),
        status: st, label: isl.name, caption, hub: isl.id === fx.hub, selected: isl.id === state.island,
      };
    });
    map.setNetwork({ nodes, routes });
  }

  // ---- Sidebar -----------------------------------------------------------
  function setupSidebar() {
    $("#atoll").innerHTML = `<option value="" data-sub="${geo.atolls.length} atolls">All of the Maldives</option>` + geo.atolls
      .map((a) => `<option value="${a.id}" data-sub="${esc(a.alt)}"${a.id === fx.atollId ? ' data-badge="Demo"' : ""}>${esc(a.name)}</option>`)
      .join("");
    $("#atoll").addEventListener("change", (e) => selectAtoll(e.target.value));
    $("#to-national").addEventListener("click", () => selectAtoll(null));

    const sel = $("#trip");
    sel.innerHTML = baseline.trips
      .map((t) => `<option value="${t.id}" data-sub="Departs ${fmt(t.stops[0].dep)}${t.days.includes(fx.meta.weekday) ? "" : " · not running today"}">${esc(tripLabel(t))}</option>`)
      .join("");
    sel.addEventListener("change", () => { state.editTrip = sel.value; syncControls(); });
    $("#shift").addEventListener("input", (e) => setShift(Number(e.target.value)));
    $("#earlier").addEventListener("click", () => setShift((state.shifts[state.editTrip] || 0) - 15));
    $("#later").addEventListener("click", () => setShift((state.shifts[state.editTrip] || 0) + 15));
    $("#reset").addEventListener("click", () => { state.shifts = {}; syncControls(); rerun(); });

    $("#presets").innerHTML = fx.presets
      .map((p, i) => `<button type="button" class="chip" data-preset="${i}">${esc(p.label)}${p.note ? ` <span class="chip-note">${esc(p.note)}</span>` : ""}</button>`)
      .join("");
    $("#presets").addEventListener("click", (e) => {
      const b = e.target.closest("[data-preset]");
      if (!b) return;
      const p = fx.presets[Number(b.dataset.preset)];
      state.shifts = { [p.tripId]: p.shiftMin }; state.editTrip = p.tripId;
      syncControls(); rerun();
      focusFirstChange();
    });

    $("#moved").addEventListener("click", (e) => {
      const rm = e.target.closest("[data-unmove]");
      const ed = e.target.closest("[data-edit]");
      if (rm) { delete state.shifts[rm.dataset.unmove]; syncControls(); rerun(); }
      else if (ed) { state.editTrip = ed.dataset.edit; syncControls(); }
    });

    window.Dropdown.enhance($("#atoll"));
    window.Dropdown.enhance(sel);

    $("#reduce-wait").addEventListener("change", (e) => { state.reduceWait = e.target.checked; state.suggestion = null; renderSuggestion(); });
    $("#optimize").addEventListener("click", () => {
      state.suggestion = M.optimize(fx, { reduceWait: state.reduceWait });
      renderSuggestion();
    });
    $("#suggestion").addEventListener("click", (e) => {
      if (e.target.closest("#apply-suggestion")) {
        state.shifts = { ...state.suggestion.shifts };
        state.editTrip = Object.keys(state.shifts)[0] || state.editTrip;
        syncControls(); rerun();
        focusFirstChange();
      } else if (e.target.closest("#dismiss-suggestion")) {
        state.suggestion = null; renderSuggestion();
      }
    });
  }

  function showJourney(islandId, ruleId) {
    state.island = islandId;
    if (ruleId) state.rule = ruleId;
    state.leftView = "journey";
    render();
    const left = document.querySelector(".left");
    if (left) left.scrollTop = 0;
  }

  function focusFirstChange() {
    const first = comparison && Object.values(comparison).flatMap((c) => c.changes)[0];
    if (first) { state.island = first.home_island_id; state.rule = first.journey_rule_id; render(); }
  }

  function setShift(v) {
    state.shifts = { ...state.shifts, [state.editTrip]: Math.max(-240, Math.min(240, v)) };
    if (!state.shifts[state.editTrip]) delete state.shifts[state.editTrip];
    syncControls(); rerun();
  }

  function syncControls() {
    const shift = state.shifts[state.editTrip] || 0;
    $("#trip").value = state.editTrip;
    $("#shift").value = shift;
    const t = origTrip(state.editTrip);
    const from = t.stops[0].dep, to = from + shift;
    $("#shift-readout").innerHTML = shift === 0
      ? `Departs <b class="mono">${fmt(from)}</b> <span class="muted">as timetabled</span>`
      : `<span class="mono strike">${fmt(from)}</span> → <b class="mono">${to >= 0 && to <= 1439 ? fmt(to) : "--:--"}</b> <span class="muted">${shift > 0 ? "+" : "−"}${Math.abs(shift)} min</span>`;
    $("#reset").disabled = !moved().length;
    window.Dropdown.syncAll();
    const list = moved();
    $("#moved").innerHTML = list.length
      ? list.map(([id, s]) => {
          const t = origTrip(id);
          return `<li><button type="button" class="moved-edit${id === state.editTrip ? " cur" : ""}" data-edit="${id}">${esc(tripLabel(t))} <span class="mono">${fmt(t.stops[0].dep)} → ${fmt(t.stops[0].dep + s)}</span></button><button type="button" class="x" data-unmove="${id}" aria-label="Put ${esc(tripLabel(t))} back to ${fmt(t.stops[0].dep)}">×</button></li>`;
        }).join("")
      : `<li class="none">No ferries moved. Results match the timetable.</li>`;
  }

  function renderSidebar() {
    const isDemo = state.atoll === fx.atollId;
    $("#side-national").hidden = !!state.atoll;
    $("#side-nodata").hidden = !state.atoll || isDemo;
    $("#side-demo").hidden = !isDemo;
    if (state.atoll && !isDemo) {
      const a = atollById[state.atoll];
      $("#nodata-name").textContent = `${a.name} (${a.alt})`;
    }
    if (isDemo) {
      $("#demo-atoll-name").textContent = `${demoAtoll.name} (${demoAtoll.alt})`;
    }
    const st = $("#scenario-status");
    if (scenarioError) { st.className = "status-line error"; st.textContent = `${scenarioError} Showing the timetable instead.`; }
    else if (active()) { st.className = "status-line"; st.textContent = `${moved().length} ferr${moved().length === 1 ? "y" : "ies"} moved. Same population and journey rules as the timetable.`; }
    else { st.className = "status-line"; st.textContent = "Move a ferry, try an example, or ask for a suggested timetable."; }
    renderChanges();
  }

  function renderChanges() {
    const el = $("#changes");
    if (!active()) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = fx.rules.map((rule) => {
      const c = comparison[rule.id];
      const unit = rule.id === "health" ? "residents" : "students";
      return `<div class="change-row">
        <div class="change-head">${esc(rule.short)}</div>
        <div class="change-nums">
          <span class="cn good">+${n(c.gained)}</span><span class="cl">gain</span>
          <span class="cn ${c.lost ? "bad" : "zero"}">−${n(c.lost)}</span><span class="cl">lose</span>
          <span class="cn">${c.pp == null ? "n/a" : signed(c.pp, 1)}</span><span class="cl">pp</span>
        </div>
        <div class="change-unit">${unit}</div>
      </div>`;
    }).join("");
  }

  function renderSuggestion() {
    const box = $("#suggestion");
    const s = state.suggestion;
    if (!s) { box.hidden = true; return; }
    box.hidden = false;
    const changes = Object.entries(s.shifts);
    const h = s.comparison.health, sc = s.comparison.school;
    const bh = baseline.summary.health, rh = s.result.summary.health;
    const bs = baseline.summary.school, rs = s.result.summary.school;
    const unresolved = [];
    for (const r of s.unresolved) {
      const key = `${r.home_island_id}|${r.failure_reason}`;
      if (unresolved.some((u) => u.key === key)) continue;
      unresolved.push({ key, r });
    }
    box.innerHTML = `
      <div class="sug-head">${changes.length ? `${changes.length} change${changes.length === 1 ? "" : "s"} suggested` : "No better timetable found"}</div>
      ${changes.length ? `<ol class="sug-list">${changes.map(([id, v]) => {
        const t = origTrip(id);
        return `<li><span>${esc(tripLabel(t))}</span><span class="mono"><span class="strike">${fmt(t.stops[0].dep)}</span> → <b>${fmt(t.stops[0].dep + v)}</b></span></li>`;
      }).join("")}</ol>` : ""}
      <dl class="sug-result">
        <div><dt>Hospital access</dt><dd>${bh.access_pct.toFixed(0)}% → <b>${rh.access_pct.toFixed(0)}%</b> <span class="good">+${n(h.gained)} residents</span></dd></div>
        <div><dt>Full school day</dt><dd>${n(bs.success)} → <b>${n(rs.success)}</b> of ${n(rs.eligible)} <span class="good">+${n(sc.gained)} students</span></dd></div>
        <div><dt>Lose access</dt><dd>${n(h.lost + sc.lost)} <span class="muted">(not allowed)</span></dd></div>
      </dl>
      ${unresolved.length ? `<div class="sug-unres"><b>Still not fixed:</b> ${unresolved.map(({ r }) => `${esc(name(r.home_island_id))} (${esc(r.failure_reason === "no_service" ? "no ferry runs today; it needs a new service, not a new time" : REASON_PILL[r.failure_reason].toLowerCase())})`).join("; ")}.</div>` : ""}
      <div class="sug-actions">
        ${changes.length ? `<button type="button" class="btn primary" id="apply-suggestion">Apply to the map</button>` : ""}
        <button type="button" class="btn" id="dismiss-suggestion">Dismiss</button>
      </div>
      <p class="sug-note">Checked ${n(s.evaluated)} timetables. Doesn't check boats, crews, harbour slots or cost.</p>`;
  }

  // ---- KPIs --------------------------------------------------------------
  function delta(value, goodWhenUp, unit) {
    if (!active()) return "";
    if (value == null || Math.abs(value) < 0.05) return `<span class="delta flat">No change</span>`;
    const up = value > 0;
    const good = up === goodWhenUp;
    const txt = unit === "pp" ? `${signed(value, 1)} pp` : signed(value);
    return `<span class="delta ${good ? "good" : "bad"}">${up ? "▲" : "▼"} ${txt} vs timetable</span>`;
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
        sub: `${n(h.success)} of ${n(h.eligible)} modeled residents`, d: delta(h.access_pct - hb.access_pct, true, "pp"), tone: "lead" },
      { label: "Residents without same-day hospital access", value: n(h.failed),
        sub: `Can't arrive by ${ruleById.health.arriveBy} and be home by ${ruleById.health.homeBy}`, d: delta(h.failed - hb.failed, false), tone: h.failed ? "bad" : "good" },
      { label: "Reach the hospital but can't get home", value: n(noRet),
        sub: "No ferry back after the appointment", d: delta(noRet - noRetB, false), tone: noRet ? "bad" : "good" },
      { label: "Secondary students missing the full school day", value: `${n(s.failed)}<span class="of"> / ${n(s.eligible)}</span>`,
        sub: `${n(late)} arrive late · ${n(strand)} can't get home · ${n(none)} have no ferry`, d: delta(s.failed - sb.failed, false), tone: s.failed ? "bad" : "good" },
    ];
    $("#kpis").innerHTML = tiles
      .map((t) => `<div class="kpi ${t.tone}"><div class="kpi-label">${t.label}</div><div class="kpi-value">${t.value}</div><div class="kpi-sub">${t.sub}</div>${t.d}</div>`)
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

  const pctOfSchoolAge = (r) => Math.round((r.population_weight / islandById[r.home_island_id].schoolAge) * 100);

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
        head = school ? `on ${isl} reach school ${fmtDur(r.minutes_late)} late` : `on ${isl} can't make a ${rule.arriveBy} hospital appointment`;
        detail = school
          ? `${studentsLine} The first ferry leaves at ${fmt(r.legs[0].dep)}, and classes start at ${rule.arriveBy}.`
          : `The first ferry leaves at ${fmt(r.legs[0].dep)} and gets them to the hospital at ${fmt(r.facility_arrival)}, ${fmtDur(r.minutes_late)} after the appointment starts.`;
        break;
      case "no_return": {
        const last = r.evidence.last_workable_departure;
        head = school ? `on ${isl} can get to school but not home again` : `on ${isl} can reach the hospital but can't get home the same day`;
        const ends = `${school ? "Classes end" : `A ${rule.arriveBy} appointment ends`} at ${fmt(r.activity_end)}`;
        detail = last != null ? `${ends}. The last ferry that gets them home leaves at ${fmt(last)}.` : `${ends}, and no ferry goes back to ${isl} today.`;
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
          const isNew = active() && b.success;
          cards.push({ r, sort: isNew ? 1 : 2, weight: r.population_weight, tone: "bad",
            pill: isNew ? "New problem from this change" : REASON_PILL[r.failure_reason], ...describeFailure(r) });
        } else if (active() && !b.success) {
          const isl = name(r.home_island_id);
          const school = rule.id === "school";
          cards.push({ r, sort: 0, weight: r.population_weight, tone: "good", pill: "Fixed by this change",
            big: school ? `${pctOfSchoolAge(r)}%` : n(r.population_weight),
            bigUnit: school ? "of school-age children" : "residents",
            head: school ? `on ${isl} now make the full school day` : `on ${isl} can now reach the hospital and get home the same day`,
            detail: `Now they arrive at ${fmt(r.facility_arrival)} and are home by ${fmt(r.home_arrival)}. Before: ${REASON_PILL[b.failure_reason].toLowerCase()}.` });
        } else if (rule.id === "health" && r.wait_before_minutes >= 90) {
          cards.push({ r, sort: 3, weight: r.population_weight, tone: "warn", pill: "Works, with a long wait",
            big: fmtDur(r.wait_before_minutes), bigUnit: "waiting",
            head: `before a ${rule.arriveBy} appointment for residents of ${name(r.home_island_id)}`,
            detail: `Their morning ferry arrives at ${fmt(r.legs[r.legs.length - 1].arr)}. A hospital visit takes them from ${fmt(r.legs[0].dep)} to ${fmt(r.home_arrival)}.` });
        }
      }
    }
    cards.sort((a, b) => a.sort - b.sort || b.weight - a.weight);
    const bad = cards.filter((c) => c.tone === "bad").length;
    $("#card-count").textContent = bad ? `${bad} barrier${bad === 1 ? "" : "s"} on this timetable` : "No barriers on this timetable";
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

    if (r.failure_reason === "no_service" || r.failure_reason === "no_route") {
      steps.push({ kind: "fail", t: "—", title: r.failure_reason === "no_service" ? `No ferry leaves ${name(r.home_island_id)} today` : "No route", text: describeFailure(r).detail });
      return steps;
    }
    if (r.failure_reason === "missed_connection") {
      const e = r.evidence;
      const idx = r.legs.findIndex((l) => l.from === e.at && l.dep === e.departs);
      r.legs.slice(0, idx).forEach((l, i, arr) => { if (i > 0) steps.push({ kind: "wait", t: fmt(arr[i - 1].arr), title: `Change boats at ${name(l.from)}`, text: "" }); ride(l); });
      steps.push({ kind: "fail", t: fmt(e.arrived), title: `Missed connection at ${name(e.at)}`, text: `The ferry to ${hub.name} leaves at ${fmt(e.departs)}, ${e.gap} min after they dock. Changing boats needs ${e.needed} min, and no later ferry arrives in time.` });
      return steps;
    }

    rideAll(r.legs);
    steps.push({ kind: "walk", t: fmt(r.legs[r.legs.length - 1].arr), title: `Walk to the ${rule.id === "health" ? "hospital" : "school"}`, text: `${r.walk_minutes} min from the harbour` });
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
    $("#left-cards").hidden = state.leftView !== "cards";
    $("#inspector").hidden = state.leftView !== "journey";
    const sel = $("#insp-island");
    if (!sel.options.length) {
      sel.innerHTML = fx.islands.filter((i) => i.id !== fx.hub).map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("");
      sel.addEventListener("change", () => { state.island = sel.value; render(); });
      window.Dropdown.enhance(sel);
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
    const who = state.rule === "health" ? "residents" : "secondary students";
    body.innerHTML = `
      <div class="insp-head">
        <div>
          <div class="insp-title">${esc(isl.name)} · ${esc(ruleById[state.rule].label.toLowerCase())}</div>
          <div class="insp-sub">Synthetic group <span class="mono">${esc(r.group_id)}</span> represents <b>${n(r.population_weight)} ${who}</b>. Not a real person.</div>
        </div>
        <div class="insp-pills">${r.success ? `<span class="pill good">Can make the trip</span>` : `<span class="pill bad">${esc(REASON_PILL[r.failure_reason])}</span>`}${changed ? `<span class="pill ${r.success ? "good" : "bad"}">${r.success ? "Fixed by this change" : "New problem"}</span>` : ""}</div>
      </div>
      <ol class="timeline">${timeline(r).map((s) => `<li class="step ${s.kind}"><span class="t mono">${s.t}</span><span class="dot" aria-hidden="true"></span><div><div class="st">${esc(s.title)}${s.trip ? ` <span class="trip mono">${esc(s.trip)}</span>` : ""}</div>${s.text ? `<div class="sx">${esc(s.text)}</div>` : ""}</div></li>`).join("")}</ol>
      ${r.success ? `<div class="burden"><div><span>${fmtDur(r.travel_minutes)}</span>on boats</div><div><span>${fmtDur(r.wait_minutes)}</span>waiting</div><div><span>${fmtDur(r.transfer_minutes)}</span>walking and changing</div></div>` : ""}`;
  }

  // ---- Island table ------------------------------------------------------
  function cell(ruleId, islandId) {
    const r = resultFor(current, ruleId, islandId);
    if (!r) return `<span class="muted">Own school</span>`;
    const b = resultFor(baseline, ruleId, islandId);
    const was = active() && b.success !== r.success ? `<span class="was">was ${b.success ? "OK" : esc(REASON_PILL[b.failure_reason].toLowerCase())}</span>` : "";
    return (r.success ? `<span class="pill good">Can make it</span>` : `<span class="pill bad">${esc(REASON_PILL[r.failure_reason])}</span>`) + was;
  }

  function renderTable() {
    const rows = fx.islands.filter((i) => i.id !== fx.hub).map((isl) => {
      const h = resultFor(current, "health", isl.id);
      const s = resultFor(current, "school", isl.id);
      return `<tr data-island="${isl.id}" class="${state.island === isl.id ? "sel" : ""}" tabindex="0">
        <th scope="row">${esc(isl.name)}</th>
        <td class="num">${n(isl.population)}</td>
        <td>${cell("health", isl.id)}</td>
        <td class="num">${h.success ? fmtDur(h.wait_minutes) : "—"}</td>
        <td class="num">${s ? n(s.population_weight) : `<span class="muted">${n(isl.secondaryStudents)}</span>`}</td>
        <td>${cell("school", isl.id)}</td>
      </tr>`;
    }).join("");
    $("#table").innerHTML = `<table>
      <thead><tr><th scope="col">Island</th><th scope="col" class="num">Residents</th><th scope="col">Hospital trip</th><th scope="col" class="num">Waiting</th><th scope="col" class="num">Students</th><th scope="col">School trip</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }

  function renderStatic() {
    $("#sources").innerHTML = fx.sources
      .map((s) => `<tr><th scope="row">${esc(s.dataset)}</th><td>${esc(s.planned)}</td><td><span class="tag ${s.classification}">${esc(s.classification)}</span></td></tr>`)
      .join("");
    const h = ruleById.health, sc = ruleById.school;
    $("#rules").innerHTML = `
      <li><b>Hospital trip:</b> arrive by ${h.arriveBy}, ${fmtDur(h.activityMin)} appointment, home by ${h.homeBy}.</li>
      <li><b>School day:</b> arrive by ${sc.arriveBy}, classes until ${fmt(toMin(sc.arriveBy) + sc.activityMin)}, home by ${sc.homeBy}. Only islands without a secondary school are modeled.</li>
      <li><b>Changing boats</b> needs at least ${fx.transferBufferMin} min. Walking between harbour and facility takes ${hub.harbourToFacilityMin} min.</li>
      <li><b>Operating day:</b> ${DAY_NAMES[fx.meta.weekday]} ${fx.meta.operatingDate}. Ferries may depart ${fx.serviceWindow.start}–${fx.serviceWindow.end}; overnight trips are rejected.</li>
      <li><b>Suggested timetables</b> only move existing departures in 15-min steps (up to 4 h), never cost anyone access, and prefer the fewest minutes moved.</li>`;
    $("#net-title").textContent = `Demo network · ${demoAtoll.name}`;
    $("#net-title-short").textContent = demoAtoll.name;
  }

  function render() {
    renderMap();
    renderSidebar();
    renderKpis();
    renderCards();
    renderInspector();
    renderTable();
    window.Dropdown.syncAll();
  }

  // ---- Events ------------------------------------------------------------
  document.addEventListener("click", (e) => {
    const insp = e.target.closest("[data-inspect]");
    if (insp) {
      const [isl, rule] = insp.dataset.inspect.split("|");
      showJourney(isl, rule);
      return;
    }
    if (e.target.closest("#back")) { state.leftView = "cards"; render(); return;
    }
    if (e.target.closest("[data-go-demo]")) { selectAtoll(fx.atollId); return; }
    const lens = e.target.closest("[data-lens]");
    if (lens) { state.rule = lens.dataset.lens; render(); return; }
    const tab = e.target.closest("[data-rule-tab]");
    if (tab) { state.rule = tab.dataset.ruleTab; render(); return; }
    const row = e.target.closest("tr[data-island]");
    if (row) { showJourney(row.dataset.island); window.scrollTo({ top: 0, behavior: "smooth" }); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest && e.target.closest("tr[data-island]");
    if (row) { e.preventDefault(); showJourney(row.dataset.island); window.scrollTo({ top: 0 }); }
  });

  setupSidebar();
  syncControls();
  renderStatic();
  render();
})();
