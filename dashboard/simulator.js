// M.A.N.D.A.R.I.N simulator: population generator + journey evaluation.
//
// Runs in the browser for now. The output records follow the shapes in
// M.A.N.D.A.R.I.N_MAJOR_COMPONENTS.md, so this file can later move behind an
// API without changing the UI.

(function () {
  const ALL_DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  const DAY_END = 23 * 60 + 59;

  const toMin = (t) => {
    const [h, m] = t.split(":").map(Number);
    return h * 60 + m;
  };
  const fmt = (min) =>
    String(Math.floor(min / 60)).padStart(2, "0") + ":" + String(min % 60).padStart(2, "0");
  const fmtDur = (min) => {
    min = Math.round(min);
    if (min < 60) return `${min} min`;
    const h = Math.floor(min / 60), m = min % 60;
    return m ? `${h} h ${m} min` : `${h} h`;
  };
  const tripDays = (trip) => (trip.days === "all" ? ALL_DAYS : trip.days);

  // ---- 1. Population generator -------------------------------------------
  // Deterministic: one weighted group per island per eligible population.
  function generatePopulation(fx) {
    const groups = [];
    for (const isl of fx.islands) {
      if (isl.id === fx.hub) continue; // already at the facility; not modeled
      groups.push({
        group_id: `G-${isl.id}-RES`, home_island_id: isl.id, age_group: "residents",
        population_weight: isl.population ?? 1, data_classification: fx.meta.classification,
      });
      if (!isl.ownSecondary && isl.secondaryStudents > 0) {
        groups.push({
          group_id: `G-${isl.id}-SEC`, home_island_id: isl.id, age_group: "secondary_students",
          population_weight: isl.secondaryStudents, data_classification: fx.meta.classification,
        });
      }
    }
    return groups;
  }

  // ---- 2. Scenario patch -------------------------------------------------
  // Returns minute-based trips with one service shifted, or an error.
  function scenarioShifts(scenario) {
    if (!scenario) return {};
    if (scenario.shifts) return scenario.shifts;
    return scenario.tripId && scenario.shiftMin ? { [scenario.tripId]: scenario.shiftMin } : {};
  }

  function prepareTrips(fx, scenario) {
    const trips = fx.trips.map((t) => ({
      id: t.id,
      days: tripDays(t),
      stops: t.stops.map((s) => ({
        island: s.island,
        arr: s.arr != null ? toMin(s.arr) : null,
        dep: s.dep != null ? toMin(s.dep) : null,
      })),
    }));
    const shifts = scenarioShifts(scenario);
    const win = fx.serviceWindow || { start: "00:00", end: fmt(DAY_END) };
    const lo = toMin(win.start), hi = toMin(win.end);
    for (const [tripId, shift] of Object.entries(shifts)) {
      if (!shift) continue;
      const trip = trips.find((t) => t.id === tripId);
      if (!trip) return { error: `Unknown service ${tripId}.` };
      for (const s of trip.stops) {
        for (const k of ["arr", "dep"]) {
          if (s[k] == null) continue;
          s[k] += shift;
          if (s[k] < 0 || s[k] > DAY_END) {
            return { error: "That shift moves the ferry past midnight. Overnight trips aren't supported." };
          }
          if (k === "dep" && (s[k] < lo || s[k] > hi)) {
            return { error: `Ferries can only depart between ${win.start} and ${win.end}.` };
          }
        }
      }
    }
    return { trips };
  }

  function buildConnections(trips, weekday) {
    const conns = [];
    for (const t of trips) {
      if (!t.days.includes(weekday)) continue;
      for (let i = 0; i < t.stops.length - 1; i++) {
        const a = t.stops[i], b = t.stops[i + 1];
        conns.push({ trip: t.id, from: a.island, to: b.island, dep: a.dep, arr: b.arr });
      }
    }
    return conns.sort((x, y) => x.dep - y.dep || x.arr - y.arr);
  }

  // Connection scan: earliest arrival at every island. Staying on the same
  // trip needs no buffer; changing boats needs `buffer` minutes.
  function earliest(conns, origin, start, buffer) {
    const arr = { [origin]: start };
    const via = {};
    const boarded = {};
    for (const c of conns) {
      let onTrip = c.trip in boarded;
      if (!onTrip && arr[c.from] !== undefined) {
        const ready = c.from === origin ? arr[c.from] : arr[c.from] + buffer;
        if (c.dep >= ready) { boarded[c.trip] = c; onTrip = true; }
      }
      if (onTrip && (arr[c.to] === undefined || c.arr < arr[c.to])) {
        arr[c.to] = c.arr;
        via[c.to] = { conn: c, board: boarded[c.trip] };
      }
    }
    return { arr, via };
  }

  function pathLegs(search, origin, dest) {
    const legs = [];
    let cur = dest, guard = 0;
    while (cur !== origin && search.via[cur] && guard++ < 50) {
      const { conn, board } = search.via[cur];
      legs.unshift({ trip_id: conn.trip, from: board.from, to: cur, dep: board.dep, arr: conn.arr });
      cur = board.from;
    }
    return legs;
  }

  const rideMin = (legs) => legs.reduce((s, l) => s + (l.arr - l.dep), 0);
  const gapMin = (legs) => legs.slice(1).reduce((s, l, i) => s + (l.dep - legs[i].arr), 0);

  // ---- 3. Journey evaluation ---------------------------------------------
  function evaluate(ctx, rule, group) {
    const { fx, conns, trips } = ctx;
    const buffer = fx.transferBufferMin;
    const hub = rule.destination;
    const walk = fx.islands.find((i) => i.id === hub).harbourToFacilityMin || 0;
    const origin = group.home_island_id;
    const start = toMin(rule.earliestStart);
    const arriveBy = toMin(rule.arriveBy);
    const activityEnd = arriveBy + rule.activityMin;
    const homeBy = toMin(rule.homeBy);

    const base = {
      group_id: group.group_id, journey_rule_id: rule.id, home_island_id: origin,
      population_weight: group.population_weight,
      success: false, outward_feasible: false, return_feasible: null, failure_reason: null,
      legs: [], return_legs: [], travel_minutes: null, wait_minutes: null, transfer_minutes: null,
      arrive_by: arriveBy, activity_end: activityEnd, home_by: homeBy, walk_minutes: walk,
    };

    if (!conns.some((c) => c.from === origin)) {
      const days = [...new Set(trips.filter((t) => t.stops.some((s) => s.island === origin)).flatMap((t) => t.days))];
      return { ...base, failure_reason: "no_service", evidence: { days_running: ALL_DAYS.filter((d) => days.includes(d)) } };
    }

    const out = earliest(conns, origin, start, buffer);
    const harbourArr = out.arr[hub];
    if (harbourArr === undefined || harbourArr + walk > arriveBy) {
      // A missed connection needs evidence: the journey works with no buffer.
      const loose = earliest(conns, origin, start, 0);
      if (loose.arr[hub] !== undefined && loose.arr[hub] + walk <= arriveBy) {
        const legs = pathLegs(loose, origin, hub);
        let evidence = null;
        for (let i = 1; i < legs.length; i++) {
          const gap = legs[i].dep - legs[i - 1].arr;
          if (gap < buffer) {
            evidence = { at: legs[i].from, arrived: legs[i - 1].arr, departs: legs[i].dep, gap, needed: buffer };
            break;
          }
        }
        if (evidence) return { ...base, failure_reason: "missed_connection", legs, evidence };
      }
      if (harbourArr === undefined) return { ...base, failure_reason: "no_route" };
      const legs = pathLegs(out, origin, hub);
      return {
        ...base, failure_reason: "late_arrival", legs,
        facility_arrival: harbourArr + walk, minutes_late: harbourArr + walk - arriveBy,
      };
    }

    const legs = pathLegs(out, origin, hub);
    const facilityArr = harbourArr + walk;
    const returnReady = activityEnd + walk;
    const back = earliest(conns, hub, returnReady, buffer);
    const homeArr = back.arr[origin];

    if (homeArr === undefined || homeArr > homeBy) {
      const deps = [...new Set(conns.filter((c) => c.from === hub).map((c) => c.dep))].sort((a, b) => b - a);
      let lastWorkable = null;
      for (const d of deps) {
        const r = earliest(conns, hub, d, buffer);
        if (r.arr[origin] !== undefined && r.arr[origin] <= homeBy) { lastWorkable = d; break; }
      }
      return {
        ...base, outward_feasible: true, return_feasible: false, failure_reason: "no_return", legs,
        facility_arrival: facilityArr,
        evidence: {
          return_ready: returnReady, last_workable_departure: lastWorkable, late_home_arrival: homeArr ?? null,
          late_home_departure: homeArr !== undefined ? pathLegs(back, hub, origin)[0].dep : null,
        },
      };
    }

    const returnLegs = pathLegs(back, hub, origin);
    const waitBefore = arriveBy - facilityArr;
    const waitAfter = returnLegs[0].dep - returnReady;
    return {
      ...base, success: true, outward_feasible: true, return_feasible: true,
      legs, return_legs: returnLegs, facility_arrival: facilityArr, home_arrival: homeArr,
      travel_minutes: rideMin(legs) + rideMin(returnLegs),
      transfer_minutes: gapMin(legs) + gapMin(returnLegs) + 2 * walk,
      wait_minutes: waitBefore + waitAfter,
      wait_before_minutes: waitBefore, wait_after_minutes: waitAfter,
    };
  }

  // ---- 4. Aggregation ----------------------------------------------------
  function aggregate(fx, rule, results) {
    const eligible = results.reduce((s, r) => s + r.population_weight, 0);
    const ok = results.filter((r) => r.success);
    const success = ok.reduce((s, r) => s + r.population_weight, 0);
    const byReason = {};
    for (const r of results) if (!r.success) byReason[r.failure_reason] = (byReason[r.failure_reason] || 0) + r.population_weight;
    const wavg = (k) => (success ? ok.reduce((s, r) => s + r[k] * r.population_weight, 0) / success : null);
    return {
      rule_id: rule.id, eligible, success, failed: eligible - success,
      access_pct: eligible ? (success / eligible) * 100 : null,
      by_reason: byReason,
      avg_travel_minutes: wavg("travel_minutes"),
      avg_wait_minutes: wavg("wait_minutes"),
      avg_transfer_minutes: wavg("transfer_minutes"),
    };
  }

  function run(fx, scenario) {
    const prepared = prepareTrips(fx, scenario);
    if (prepared.error) return { error: prepared.error };
    const conns = buildConnections(prepared.trips, fx.meta.weekday);
    const ctx = { fx, conns, trips: prepared.trips };
    const population = generatePopulation(fx);
    const results = {}, summary = {};
    for (const rule of fx.rules) {
      const groups = population.filter((g) => g.age_group === rule.eligible);
      results[rule.id] = groups.map((g) => evaluate(ctx, rule, g));
      summary[rule.id] = aggregate(fx, rule, results[rule.id]);
    }
    return { scenario: scenario || null, population, trips: prepared.trips, conns, results, summary };
  }

  // Gains and losses are counted separately, per rule (never summed across rules).
  function compare(baseline, scenario) {
    const out = {};
    for (const ruleId of Object.keys(baseline.results)) {
      const changes = [];
      let gained = 0, lost = 0;
      for (const b of baseline.results[ruleId]) {
        const s = scenario.results[ruleId].find((r) => r.group_id === b.group_id);
        if (!b.success && s.success) { gained += b.population_weight; changes.push({ ...s, change: "gained" }); }
        if (b.success && !s.success) { lost += b.population_weight; changes.push({ ...s, change: "lost" }); }
      }
      const bp = baseline.summary[ruleId].access_pct, sp = scenario.summary[ruleId].access_pct;
      out[ruleId] = { gained, lost, net: gained - lost, pp: bp != null && sp != null ? sp - bp : null, changes };
    }
    return out;
  }

  // ---- 5. Timetable optimizer -------------------------------------------
  // Coordinate search over departure shifts (15-min steps). Objective, in order:
  //   1. more people with complete journeys (hospital residents + school students),
  //   2. less total waiting for those who succeed (only with opts.reduceWait),
  //   3. smaller total change to the timetable.
  // Hard constraint: nobody who has access in the baseline loses it.
  // It does not check vessels, crews, harbours or cost.
  function optimize(fx, opts = {}) {
    const step = opts.step || 15, maxShift = opts.maxShift || 240, maxPasses = opts.maxPasses || 4;
    const baseline = run(fx, null);
    const key = (r) => `${r.journey_rule_id}|${r.group_id}`;
    const hadAccess = new Set(Object.values(baseline.results).flat().filter((r) => r.success).map(key));
    const candidates = opts.candidates || baseline.trips.filter((t) => t.days.includes(fx.meta.weekday)).map((t) => t.id);
    let evaluated = 0;

    function score(shifts) {
      const r = run(fx, { shifts });
      evaluated++;
      if (r.error) return null;
      const all = Object.values(r.results).flat();
      if (all.some((x) => hadAccess.has(key(x)) && !x.success)) return null;
      const ok = all.filter((x) => x.success);
      return {
        access: ok.reduce((s, x) => s + x.population_weight, 0),
        wait: opts.reduceWait ? Math.round(ok.reduce((s, x) => s + x.wait_minutes * x.population_weight, 0) / 1000) : 0,
        moved: Object.values(shifts).reduce((s, v) => s + Math.abs(v), 0),
      };
    }
    const better = (a, b) =>
      a.access !== b.access ? a.access > b.access : a.wait !== b.wait ? a.wait < b.wait : a.moved < b.moved;

    let shifts = {};
    let best = score(shifts);
    for (let pass = 0; pass < maxPasses; pass++) {
      let improved = false;
      for (const id of candidates) {
        const curShift = shifts[id] || 0;
        let pick = curShift, pickScore = best;
        for (let s = -maxShift; s <= maxShift; s += step) {
          if (s === curShift) continue;
          const trial = { ...shifts, [id]: s };
          if (!s) delete trial[id];
          const sc = score(trial);
          if (sc && better(sc, pickScore)) { pick = s; pickScore = sc; }
        }
        if (pick !== curShift) {
          shifts = { ...shifts, [id]: pick };
          if (!pick) delete shifts[id];
          best = pickScore; improved = true;
        }
      }
      if (!improved) break;
    }
    const result = run(fx, { shifts });
    return {
      shifts, result, comparison: compare(baseline, result), evaluated,
      unresolved: Object.values(result.results).flat().filter((r) => !r.success),
    };
  }

  window.Mandarin = { run, compare, optimize, generatePopulation, toMin, fmt, fmtDur, tripDays };
})();
