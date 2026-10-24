// Maldives map: real island + reef outlines (OpenStreetMap, see maldives-geo.js),
// atoll zoom, and the transport network overlay for the selected atoll.

(function () {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  };

  function createMap(svg, geo, opts) {
    const atolls = geo.atolls;
    const all = atolls.reduce((b, a) => [Math.min(b[0], a.bbox[0]), Math.min(b[1], a.bbox[1]), Math.max(b[2], a.bbox[2]), Math.max(b[3], a.bbox[3])], [1e9, 1e9, -1e9, -1e9]);
    const NATIONAL = [all[0] - 3000, all[1] - 7500, all[2] - all[0] + 14000, all[3] - all[1] + 11000]; // extra top room for the map toolbar
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

    let vb = NATIONAL.slice();
    let upp = 1; // map units per screen pixel
    let pins = [];
    let tween = 0;

    el("rect", { class: "sea", x: -60000, y: -60000, width: 200000, height: 220000 }, svg);
    const gAtolls = el("g", { class: "atolls" }, svg);
    const gLabels = el("g", { class: "atoll-labels" }, svg);
    const gNet = el("g", { class: "network" }, svg);

    const atollEls = {};
    for (const a of atolls) {
      const g = el("g", { class: "atoll", "data-atoll": a.id }, gAtolls);
      const [x0, y0, x1, y1] = a.bbox;
      el("rect", { class: "hit", x: x0 - 700, y: y0 - 700, width: x1 - x0 + 1400, height: y1 - y0 + 1400 }, g);
      if (a.reef) el("path", { class: "reef", d: a.reef }, g);
      if (a.land) el("path", { class: "land", d: a.land }, g);
      const t = el("text", { class: "atoll-label", x: x1 + 450, y: (y0 + y1) / 2, "data-atoll": a.id }, gLabels);
      el("tspan", { class: "al-name" }, t).textContent = a.name;
      const alt = el("tspan", { class: "al-alt", x: x1 + 450, dy: "1.25em" }, t);
      alt.textContent = a.alt;
      atollEls[a.id] = { g, label: t, alt };
    }

    // Labels sit right of each atoll; push a label down if it would collide
    // with the previous one (Haa Alif / Haa Dhaalu are very close).
    function layoutLabels() {
      const minGap = 2.6 * 12.5 * upp;
      let lastY = -Infinity;
      for (const a of atolls) {
        const { label } = atollEls[a.id];
        let y = (a.bbox[1] + a.bbox[3]) / 2;
        if (y - lastY < minGap) y = lastY + minGap;
        label.setAttribute("y", y);
        lastY = y;
      }
    }

    function boxFor(id) {
      const a = atolls.find((x) => x.id === id);
      if (!a) return NATIONAL.slice();
      const [x0, y0, x1, y1] = a.bbox;
      const w = x1 - x0, h = y1 - y0, pad = Math.max(w, h) * 0.12 + 500;
      return [x0 - pad, y0 - pad, w + 2 * pad, h + 2 * pad];
    }

    function applyViewBox() {
      svg.setAttribute("viewBox", vb.map((v) => v.toFixed(1)).join(" "));
      const r = svg.getBoundingClientRect();
      upp = Math.max(vb[2] / (r.width || 1), vb[3] / (r.height || 1));
      gLabels.setAttribute("font-size", (12.5 * upp).toFixed(1));
      layoutLabels();
      for (const p of pins) p.setAttribute("transform", `translate(${p.dataset.x} ${p.dataset.y}) scale(${upp.toFixed(3)})`);
      svg.style.setProperty("--dash", `${(3 * upp).toFixed(1)} ${(6 * upp).toFixed(1)}`);
    }

    // Timer-driven (not requestAnimationFrame) so the zoom still finishes in
    // throttled or background panes; each step is computed from elapsed time.
    function zoomTo(id, animate = true) {
      const to = boxFor(id);
      const id0 = ++tween;
      if (!animate || reduced) { vb = to; applyViewBox(); return; }
      const from = vb.slice(), t0 = performance.now(), dur = 800;
      (function step() {
        if (id0 !== tween) return;
        const k = Math.min(1, (performance.now() - t0) / dur);
        const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
        // Interpolate the zoom geometrically so it feels even from far out.
        const w = from[2] * Math.pow(to[2] / from[2], e), h = from[3] * Math.pow(to[3] / from[3], e);
        const cx = from[0] + from[2] / 2 + (to[0] + to[2] / 2 - from[0] - from[2] / 2) * e;
        const cy = from[1] + from[3] / 2 + (to[1] + to[3] / 2 - from[1] - from[3] / 2) * e;
        vb = [cx - w / 2, cy - h / 2, w, h];
        applyViewBox();
        if (k < 1) setTimeout(step, 16);
      })();
    }

    function setState({ atollId, demoAtollId }) {
      svg.classList.toggle("is-national", !atollId);
      for (const a of atolls) {
        const { g, label, alt } = atollEls[a.id];
        g.classList.toggle("active", a.id === atollId);
        g.classList.toggle("demo", a.id === demoAtollId);
        label.classList.toggle("demo", a.id === demoAtollId);
        alt.textContent = a.id === demoAtollId ? `${a.alt} · demo network` : a.alt;
      }
    }

    // nodes: {id, x, y, r, status, label, caption, selected, hub}
    // routes: {x1, y1, x2, y2, kind}
    function setNetwork(net) {
      gNet.replaceChildren();
      pins = [];
      if (!net) return;
      for (const r of net.routes) {
        el("line", { class: `route ${r.kind}`, x1: r.x1, y1: r.y1, x2: r.x2, y2: r.y2, "vector-effect": "non-scaling-stroke" }, gNet);
      }
      for (const n of net.nodes) {
        const g = el("g", {
          class: `pin ${n.status}${n.selected ? " sel" : ""}`, "data-island": n.id,
          tabindex: n.hub ? -1 : 0, role: n.hub ? "img" : "button", "aria-label": `${n.label}: ${n.caption}`,
        }, gNet);
        g.dataset.x = n.x; g.dataset.y = n.y;
        if (n.selected) el("circle", { class: "sel-ring", r: n.r + 6 }, g);
        el("circle", { class: "dot", r: n.r }, g);
        if (n.hub) el("path", { class: "cross", d: "M-6 0h12M0 -6v12" }, g);
        const t = el("text", { class: "pin-name", y: n.r + 15 }, g);
        t.textContent = n.label;
        const c = el("text", { class: "pin-cap", y: n.r + 28 }, g);
        c.textContent = n.caption;
        pins.push(g);
      }
      applyViewBox();
    }

    svg.addEventListener("click", (e) => {
      const pin = e.target.closest("[data-island]");
      if (pin) { opts.onIsland && opts.onIsland(pin.dataset.island); return; }
      const a = e.target.closest("[data-atoll]");
      if (a) opts.onAtoll && opts.onAtoll(a.dataset.atoll);
    });
    svg.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const pin = e.target.closest && e.target.closest("[data-island]");
      if (pin) { e.preventDefault(); opts.onIsland && opts.onIsland(pin.dataset.island); }
    });
    new ResizeObserver(applyViewBox).observe(svg);
    applyViewBox();

    const bboxOf = (id) => atolls.find((a) => a.id === id).bbox;
    return { zoomTo, setState, setNetwork, bboxOf };
  }

  window.MandarinMap = { createMap };
})();
