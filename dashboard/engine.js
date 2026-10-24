// Example resident: one synthetic resident's hospital day, before and after one timetable change (/api/demo).
(function () {
  "use strict";
  const el = document.getElementById("engine-panel");
  if (!el || !window.fetch) return;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const n = (x) => Number(x).toLocaleString("en");
  const VERDICT = { no_return: "Can't get home in time", arrives_late: "Arrives late", missed_connection: "Misses a connection",
    no_route: "No ferry route", no_data: "No ferry data" };
  const legs = (ls) => ls.map((l) => `${l.depart}–${l.arrive}`).join(", ");

  function day(title, t, dest) {
    const ok = t.outcome === "success";
    const out = t.outward.length ? t.outward : t.failed_leg === "outward" ? t.diagnostic : [];
    const back = t.return.length ? t.return : t.failed_leg === "return" ? t.diagnostic : [];
    const parts = [];
    if (out.length) parts.push(`To ${esc(dest)} ${legs(out)}`);
    if (back.length) parts.push(`boat home ${legs(back)}`);
    return `<div class="barrier${ok ? " good" : ""}">
      <div class="barrier-top"><span class="barrier-head">${esc(title)}</span>
        <span class="pill ${ok ? "good" : "bad"}">${esc(ok ? `Home by ${t.request.home_by}` : VERDICT[t.outcome] || t.outcome)}</span></div>
      ${parts.length ? `<div class="barrier-detail mono">${parts.join(" · ")}</div>` : ""}</div>`;
  }

  fetch("/api/demo").then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (!d || !d.trip || !d.trip.baseline.request) return;
    const q = d.trip.baseline.request;
    const edit = (d.scenario.timetable_edits || [])[0];
    const change = edit ? `If sailing ${edit.trip_id} leaves ${Math.abs(edit.shift_minutes)} min ${edit.shift_minutes < 0 ? "earlier" : "later"}` : "With the change";
    const hours = q.activity_minutes % 60 ? `${q.activity_minutes} min` : `${q.activity_minutes / 60} h`;
    el.innerHTML = `<div class="eyebrow">Example resident</div>
      <div class="sec-head"><h2>${esc(d.display_name)}, ${esc(d.age)}</h2><span class="tag assumed">synthetic</span></div>
      <p class="issue-why">Lives on ${esc(d.island_name)}. Hospital appointment at ${esc(d.destination_name)} at ${esc(q.arrive_by)} for ${esc(hours)}; needs to be home by ${esc(q.home_by)}.</p>
      <div class="rows">${day("Today", d.trip.baseline, d.destination_name)}${d.trip.scenario ? day(change, d.trip.scenario, d.destination_name) : ""}</div>
      <div class="stats">
        <div class="stat"><b class="good">+${n(d.compare.gained)}</b><span>trips start working</span></div>
        <div class="stat"><b class="badtxt">${n(d.compare.lost)}</b><span>trips stop working</span></div>
      </div>`;
    el.hidden = false;
  }).catch(() => { el.hidden = true; });
})();
