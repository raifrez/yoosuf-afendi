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
      // Western atolls are labelled on their left so they don't compete with
      // the eastern atolls at the same latitude (Ari vs Malé, Nilandhe vs Mulaku).
      const west = (x0 + x1) / 2 < 6500;
      const t = el("text", { class: "atoll-label", x: west ? x0 - 450 : x1 + 450, y: (y0 + y1) / 2, "text-anchor": west ? "end" : "start", "dominant-baseline": "middle", "data-atoll": a.id }, gLabels);
      t.dataset.west = west ? "1" : "";
      el("tspan", { class: "al-name" }, t).textContent = a.name;
      const alt = el("tspan", { class: "al-alt", dx: "0.45em" }, t);
      alt.textContent = a.alt;
      atollEls[a.id] = { g, label: t, alt };
    }

    // Labels sit right of each atoll at the centre of its islands and reefs.
    // A label only moves down when it would overlap one already placed
    // beside it (e.g. Haa Alif / Haa Dhaalu, Gaafu Alif / Gaafu Dhaalu).
    function layoutLabels() {
      const lineH = 12.5 * upp, minGap = 1.45 * lineH;
      const placed = [];
      for (const a of atolls) {
        const { label } = atollEls[a.id];
        const altText = atollEls[a.id].alt.textContent;
        const w = (a.name.length * 7.4 + altText.length * 5.6 + 8) * upp;
        const west = label.dataset.west === "1";
        const x0 = west ? a.bbox[0] - 450 - w : a.bbox[2] + 450;
        const x1 = x0 + w;
        const want = a.labelY != null ? a.labelY : (a.bbox[1] + a.bbox[3]) / 2;
        const free = (y) => !placed.some((p) => x0 < p.x1 && x1 > p.x0 && Math.abs(y - p.y) < minGap);
        let y = want;
        // Try the wanted spot, then step outward up and down; keep the nearest free one.
        for (let k = 1; !free(y) && k < 12; k++) {
          const down = want + Math.ceil(k / 2) * (minGap / 2), up = want - Math.ceil(k / 2) * (minGap / 2);
          y = k % 2 ? down : up;
        }
        label.setAttribute("y", y.toFixed(0));
        placed.push({ x0, x1, y });
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

    let hovered = null;
    function setHover(id) {
      if (id === hovered) return;
      if (hovered && atollEls[hovered]) { atollEls[hovered].g.classList.remove("hover"); atollEls[hovered].label.classList.remove("hover"); }
      hovered = id;
      if (id && atollEls[id]) { atollEls[id].g.classList.add("hover"); atollEls[id].label.classList.add("hover"); }
    }
    svg.addEventListener("mouseover", (e) => {
      const a = e.target.closest("[data-atoll]");
      setHover(a && !e.target.closest("[data-island]") ? a.dataset.atoll : null);
    });
    svg.addEventListener("mouseleave", () => setHover(null));

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
