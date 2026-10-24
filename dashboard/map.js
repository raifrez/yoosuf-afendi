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
    const NATIONAL = [all[0] - 3000, all[1] - 6500, all[2] - all[0] + 14000, all[3] - all[1] + 9500]; // room for the top legend // extra top room for the map toolbar
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

    let vb = NATIONAL.slice();
    let upp = 1; // map units per screen pixel
    let pins = [];
    let tween = 0;

    el("rect", { class: "sea", x: -60000, y: -60000, width: 200000, height: 220000 }, svg);
    const gAtolls = el("g", { class: "atolls" }, svg);
    const gLabels = el("g", { class: "atoll-labels" }, svg);
    const gNet = el("g", { class: "network" }, svg);
    // Wake gradient: drawn in each boat's local (screen-pixel) frame, white at
    // the stern fading out behind it.
    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: "wakeFade", gradientUnits: "userSpaceOnUse", x1: -9, y1: 0, x2: -52, y2: 0 }, defs);
    el("stop", { offset: 0, "stop-color": "#fff", "stop-opacity": 0.9 }, grad);
    el("stop", { offset: 1, "stop-color": "#fff", "stop-opacity": 0 }, grad);
    const gBoats = el("g", { class: "boats" }, svg);
    const boatEls = new Map();
    let lastBoats = [];
    let routeLines = []; // [{ id, color, points: [[x,y]...], el, glow }]
    let fullPins = [];   // labelled stops in the atoll view
    let tags = [];       // route number tags

    // Greedy label placement in screen space: route tags first (on a free
    // stretch of their line), then island names around their pin (below,
    // right, left, above). Captions drop before names; hidden names stay in
    // the pin's tooltip.
    function layoutPinLabels() {
      if (!fullPins.length && !tags.length) return;
      const boxes = fullPins.map((p) => ({ x0: p.x - (p.r + 3) * upp, y0: p.y - (p.r + 3) * upp, x1: p.x + (p.r + 3) * upp, y1: p.y + (p.r + 3) * upp }));
      const hit = (b) => boxes.some((o) => b.x0 < o.x1 && b.x1 > o.x0 && b.y0 < o.y1 && b.y1 > o.y0);
      for (const t of tags) {
        const segs = [];
        for (let i = 0; i < t.points.length - 1; i++) segs.push([t.points[i], t.points[i + 1]]);
        segs.sort((a, b) => Math.hypot(b[1][0] - b[0][0], b[1][1] - b[0][1]) - Math.hypot(a[1][0] - a[0][0], a[1][1] - a[0][1]));
        let placed = null;
        for (const [a, b] of segs) {
          for (const f of [0.5, 0.35, 0.65, 0.2, 0.8]) {
            const cx = a[0] + (b[0] - a[0]) * f, cy = a[1] + (b[1] - a[1]) * f;
            const bx = { x0: cx - (t.w / 2 + 2) * upp, y0: cy - 11 * upp, x1: cx + (t.w / 2 + 2) * upp, y1: cy + 11 * upp };
            if (!hit(bx)) { placed = [cx, cy, bx]; break; }
          }
          if (placed) break;
        }
        t.g.classList.toggle("hidden-label", !placed);
        if (placed) {
          t.g.setAttribute("transform", `translate(${placed[0].toFixed(1)} ${placed[1].toFixed(1)}) scale(${upp.toFixed(3)})`);
          boxes.push(placed[2]);
        }
      }
      for (const p of [...fullPins].sort((a, b) => a.prio - b.prio)) {
        const nameW = p.name.length * 7.3 + 4, capW = p.cap ? p.cap.length * 6.3 + 4 : 0;
        let done = false;
        for (const withCap of p.cap ? [true, false] : [false]) {
          const w = Math.max(nameW, withCap ? capW : 0), h = withCap ? 29 : 16, r = p.r;
          const cands = [
            { box: [-w / 2, r + 3, w / 2, r + 3 + h], anchor: "middle", nx: 0, ny: r + 15 },
            { box: [r + 5, -8, r + 5 + w, -8 + h], anchor: "start", nx: r + 5, ny: 4 },
            { box: [-r - 5 - w, -8, -r - 5, -8 + h], anchor: "end", nx: -r - 5, ny: 4 },
            { box: [-w / 2, -r - 3 - h, w / 2, -r - 3], anchor: "middle", nx: 0, ny: -r - 3 - h + 12 },
          ];
          for (const c of cands) {
            const b = { x0: p.x + c.box[0] * upp, y0: p.y + c.box[1] * upp, x1: p.x + c.box[2] * upp, y1: p.y + c.box[3] * upp };
            if (hit(b)) continue;
            for (const [elx, dy] of [[p.nameEl, 0], [p.capEl, 13]]) {
              // Inline style, because the stylesheet's text-anchor would override the attribute.
              elx.setAttribute("x", c.nx); elx.setAttribute("y", c.ny + dy); elx.style.textAnchor = c.anchor;
            }
            p.nameEl.style.display = ""; p.capEl.style.display = withCap ? "" : "none";
            boxes.push(b); done = true; break;
          }
          if (done) break;
        }
        if (!done) { p.nameEl.style.display = "none"; p.capEl.style.display = "none"; }
      }
    }

    const atollEls = {};
    for (const a of atolls) {
      const g = el("g", { class: "atoll", "data-atoll": a.id }, gAtolls);
      const [x0, y0, x1, y1] = a.bbox;
      el("rect", { class: "hit", x: x0 - 700, y: y0 - 700, width: x1 - x0 + 1400, height: y1 - y0 + 1400 }, g);
      if (a.reef) el("path", { class: "reef", d: a.reef, "vector-effect": "non-scaling-stroke" }, g);
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
        const w = (a.name.length * 7.4 + altText.length * 6.2 + 12) * upp;
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

    // fit: optional [[x, y], ...] to frame instead of the whole atoll (its ferry stops).
    function boxFor(id, fit) {
      const a = atolls.find((x) => x.id === id);
      if (!a) return NATIONAL.slice();
      if (fit && fit.length) {
        let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
        for (const [x, y] of fit) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
        const ext = Math.max(x1 - x0, y1 - y0, 1800);
        const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, half = ext / 2 + Math.max(ext * 0.22, 700);
        return [cx - half, cy - half * 1.15, 2 * half, 2 * half * 1.1];
      }
      const [x0, y0, x1, y1] = a.bbox;
      const w = x1 - x0, h = y1 - y0, pad = Math.max(w, h) * 0.12 + 500;
      // A little extra room at the top for the legend.
      return [x0 - pad, y0 - pad * 1.6, w + 2 * pad, h + 2.6 * pad];
    }

    function applyViewBox() {
      svg.setAttribute("viewBox", vb.map((v) => v.toFixed(1)).join(" "));
      const r = svg.getBoundingClientRect();
      upp = Math.max(vb[2] / (r.width || 1), vb[3] / (r.height || 1));
      gLabels.setAttribute("font-size", (12.5 * upp).toFixed(1));
      layoutLabels();
      for (const p of pins) p.setAttribute("transform", `translate(${p.dataset.x} ${p.dataset.y}) scale(${upp.toFixed(3)})`);
      svg.style.setProperty("--dash", `${(3 * upp).toFixed(1)} ${(6 * upp).toFixed(1)}`);
      layoutRouteLines();
      layoutPinLabels();
      placeBoats();
    }

    // Timer-driven (not requestAnimationFrame) so the zoom still finishes in
    // throttled or background panes; each step is computed from elapsed time.
    let lastZoom = { id: null, fit: null };
    let baseUpp = null; // map units per pixel at the atoll's framed view
    function zoomTo(id, animate = true, fit = null) {
      lastZoom = { id, fit };
      const to = boxFor(id, fit);
      const r0 = svg.getBoundingClientRect();
      baseUpp = Math.max(to[2] / (r0.width || 1), to[3] / (r0.height || 1));
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

    // status: { atollId: "bad" | "ok" | "none" }, notes: { atollId: "short text" }
    function setState({ atollId, status = {}, notes = {} }) {
      svg.classList.toggle("is-national", !atollId);
      for (const a of atolls) {
        const { g, label, alt } = atollEls[a.id];
        g.classList.toggle("active", a.id === atollId);
        for (const k of ["bad", "ok", "none"]) {
          g.classList.toggle(`st-${k}`, status[a.id] === k);
          label.classList.toggle(`st-${k}`, status[a.id] === k);
        }
        // National labels stay short: the atoll name plus an optional status note.
        alt.textContent = notes[a.id] || "";
      }
      layoutLabels();
    }

    // nodes: {id, x, y, r, status, label, caption, selected, hub, mini}
    // routes: {x1, y1, x2, y2, kind}
    // bubbles: {atoll, x, y, r, text, status}
    function setNetwork(net) {
      gNet.replaceChildren();
      pins = [];
      if (!net) return;
      for (const r of net.routes) {
        el("line", { class: `route ${r.kind}`, x1: r.x1, y1: r.y1, x2: r.x2, y2: r.y2, "vector-effect": "non-scaling-stroke" }, gNet);
      }
      // Coloured route lines (atoll view). Routes sharing a stretch are drawn
      // side by side, like a metro map, so each stays visible.
      routeLines = [];
      fullPins = []; tags = [];
      const use = new Map();
      for (const r of net.routeLines || []) {
        for (let i = 0; i < r.points.length - 1; i++) {
          const k = [r.stops[i], r.stops[i + 1]].sort().join("|");
          if (!use.has(k)) use.set(k, []);
          if (!use.get(k).includes(r.id)) use.get(k).push(r.id);
        }
      }
      for (const r of net.routeLines || []) {
        const glow = r.edited ? el("polyline", { class: "route-glow", "vector-effect": "non-scaling-stroke", "data-route": r.id }, gNet) : null;
        const line = el("polyline", { class: "route-line", "vector-effect": "non-scaling-stroke", "data-route": r.id, style: `stroke:${r.color}` }, gNet);
        routeLines.push({ ...r, el: line, glow, use });
      }
      for (const r of net.routeLines || []) {
        const g = el("g", { class: "route-tag", "data-route": r.id }, gNet);
        g.dataset.x = r.labelAt[0]; g.dataset.y = r.labelAt[1];
        const w = 10 + String(r.label).length * 7.2;
        el("rect", { x: -w / 2, y: -9, width: w, height: 18, rx: 9, style: `fill:${r.color}` }, g);
        const t = el("text", { y: 0.5, "dominant-baseline": "middle" }, g);
        t.textContent = r.label;
        pins.push(g);
        tags.push({ g, w, points: r.points });
      }
      for (const n of net.nodes.filter((x) => x.mini)) {
        const g = el("g", { class: `pin mini ${n.status}`, "aria-hidden": "true" }, gNet);
        g.dataset.x = n.x; g.dataset.y = n.y;
        el("circle", { class: "dot", r: n.hub ? 3.5 : 2.4 }, g);
        pins.push(g);
      }
      for (const b of net.bubbles || []) {
        const g = el("g", { class: `bubble ${b.status}`, "data-atoll": b.atoll }, gNet);
        g.dataset.x = b.x; g.dataset.y = b.y;
        el("circle", { r: b.r }, g);
        const t = el("text", { y: 0.5, "dominant-baseline": "middle" }, g);
        t.textContent = b.text;
        pins.push(g);
      }
      for (const n of net.nodes.filter((x) => !x.mini)) {
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
        el("title", {}, g).textContent = n.caption ? `${n.label}: ${n.caption}` : n.label;
        pins.push(g);
        fullPins.push({ g, x: n.x, y: n.y, r: n.r, name: n.label, cap: n.caption, nameEl: t, capEl: c,
          prio: n.hub ? 0 : n.selected ? 1 : n.status === "bad" ? 2 : 3 });
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

    function layoutRouteLines() {
      const gap = 5 * upp;
      for (const r of routeLines) {
        const segOff = [];
        for (let i = 0; i < r.points.length - 1; i++) {
          const k = [r.stops[i], r.stops[i + 1]].sort().join("|");
          const ids = r.use.get(k);
          const idx = ids.indexOf(r.id), cnt = ids.length;
          // Perpendicular, with a direction that doesn't flip between the two ways of travel.
          const [a, b] = r.stops[i] < r.stops[i + 1] ? [r.points[i], r.points[i + 1]] : [r.points[i + 1], r.points[i]];
          const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1;
          const o = (idx - (cnt - 1) / 2) * gap;
          segOff.push([(-dy / L) * o, (dx / L) * o]);
        }
        const pts = r.points.map((p, i) => {
          const s1 = segOff[i - 1], s2 = segOff[i];
          const ox = s1 && s2 ? (s1[0] + s2[0]) / 2 : (s1 || s2)[0];
          const oy = s1 && s2 ? (s1[1] + s2[1]) / 2 : (s1 || s2)[1];
          return `${(p[0] + ox).toFixed(1)},${(p[1] + oy).toFixed(1)}`;
        }).join(" ");
        r.el.setAttribute("points", pts);
        if (r.glow) r.glow.setAttribute("points", pts);
      }
    }

    let hlRoute = null;
    function highlightRoute(id) {
      hlRoute = id;
      gNet.classList.toggle("has-hl", !!id);
      gBoats.classList.toggle("has-hl", !!id);
      for (const e of svg.querySelectorAll("[data-route]")) e.classList.toggle("hl", e.dataset.route === id);
    }

    // boats: [{ id, x, y, angle (deg), cls, title, color, route }] — positions in map units.
    function setBoats(boats) {
      lastBoats = boats;
      const seen = new Set();
      for (const b of boats) {
        seen.add(b.id);
        let g = boatEls.get(b.id);
        if (!g) {
          g = el("g", { class: "boat" }, gBoats);
          // Three foam trails from the stern (centre and both quarters), fanning out.
          const w = el("g", { class: "wake" }, g);
          el("path", { d: "M-9 0L-52 0" }, w);
          el("path", { d: "M-9 -2.6L-50 -7.5" }, w);
          el("path", { d: "M-9 2.6L-50 7.5" }, w);
          el("path", { class: "hull", d: "M-9 -4.4H3Q9.5 -3.8 11.5 0Q9.5 3.8 3 4.4H-9Q-10 0 -9 -4.4Z" }, g);
          el("path", { class: "deck", d: "M-6.5 -2.6H1.5Q5 -2.2 5.8 0Q5 2.2 1.5 2.6H-6.5Z" }, g);
          el("title", {}, g);
          boatEls.set(b.id, g);
        }
        g.setAttribute("class", `boat ${b.cls || ""}${b.route && b.route === hlRoute ? " hl" : ""}`);
        g.style.setProperty("--boat-color", b.color || "");
        g.lastChild.textContent = b.title || "";
      }
      for (const [id, g] of boatEls) if (!seen.has(id)) { g.remove(); boatEls.delete(id); }
      placeBoats();
    }

    // Wake: three foam trails behind the stern (centre and both quarters) that
    // fan out and sway in a travelling wave, wider further back.
    function wakePath(side, t) {
      const pts = [];
      for (let k = 0; k <= 16; k++) {
        const x = -9 - k * 2.8, d = k / 16;
        const spread = side * (2.6 + d * 5.2);
        const amp = (side ? 0.5 : 0.35) + d * (side ? 1.8 : 1.1);
        const y = spread + amp * Math.sin(k * 0.62 - t * 7 + side * 1.4);
        pts.push(`${k ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(2)}`);
      }
      return pts.join("");
    }
    function placeBoats() {
      // Boats keep their size at the atoll's framed view and grow as you zoom in
      // (up to 3.5x), so they stay in proportion with the islands.
      const grow = baseUpp && !svg.classList.contains("is-national") ? Math.min(3.5, Math.max(1, Math.pow(baseUpp / upp, 0.75))) : 1;
      const sc = (Math.max(upp, 0.0001) * grow).toFixed(3);
      const t = reduced ? 0 : performance.now() / 1000;
      for (const b of lastBoats) {
        const g = boatEls.get(b.id);
        if (!g) continue;
        g.setAttribute("transform", `translate(${b.x.toFixed(1)} ${b.y.toFixed(1)}) rotate(${b.angle.toFixed(1)}) scale(${sc})`);
        const paths = g.querySelectorAll(".wake path");
        if (paths.length === 3) {
          paths[0].setAttribute("d", wakePath(0, t));
          paths[1].setAttribute("d", wakePath(-1, t));
          paths[2].setAttribute("d", wakePath(1, t));
        }
      }
    }

    // Scroll to zoom around the cursor, drag to pan.
    function zoomAround(clientX, clientY, f) {
      ++tween;
      const r = svg.getBoundingClientRect();
      const w = Math.max(450, Math.min(NATIONAL[2] * 1.3, vb[2] * f));
      const k = w / vb[2];
      const cx = vb[0] + vb[2] / 2, cy = vb[1] + vb[3] / 2;
      const px = cx + (clientX - (r.left + r.width / 2)) * upp, py = cy + (clientY - (r.top + r.height / 2)) * upp;
      const ncx = px - (px - cx) * k, ncy = py - (py - cy) * k;
      vb = [ncx - (vb[2] * k) / 2, ncy - (vb[3] * k) / 2, vb[2] * k, vb[3] * k];
      applyViewBox();
    }
    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const d = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      zoomAround(e.clientX, e.clientY, Math.exp(Math.max(-60, Math.min(60, d)) * 0.004));
    }, { passive: false });
    let drag = null, suppressClick = false;
    svg.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY, vb: vb.slice(), moved: false, id: e.pointerId };
    });
    svg.addEventListener("pointermove", (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) < 4) return;
      if (!drag.moved) { drag.moved = true; ++tween; svg.setPointerCapture(e.pointerId); svg.classList.add("dragging"); }
      vb = [drag.vb[0] - dx * upp, drag.vb[1] - dy * upp, drag.vb[2], drag.vb[3]];
      applyViewBox();
    });
    const endDrag = () => { if (drag && drag.moved) suppressClick = true; drag = null; svg.classList.remove("dragging"); };
    svg.addEventListener("pointerup", endDrag);
    svg.addEventListener("pointercancel", endDrag);
    function zoomBy(f) { const r = svg.getBoundingClientRect(); zoomAround(r.left + r.width / 2, r.top + r.height / 2, f); }
    function refit() { zoomTo(lastZoom.id, true, lastZoom.fit); }

    svg.addEventListener("click", (e) => {
      if (suppressClick) { suppressClick = false; return; }
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
    const project = (lon, lat) => [(lon - geo.projection.lon0) * geo.projection.k, (geo.projection.lat0 - lat) * geo.projection.k];
    const centreOf = (id) => { const a = atolls.find((x) => x.id === id); return [(a.bbox[0] + a.bbox[2]) / 2, a.labelY != null ? a.labelY : (a.bbox[1] + a.bbox[3]) / 2]; };
    function setSearching(on) { svg.classList.toggle("searching", !!on); }
    function markAtoll(id) { for (const a of atolls) atollEls[a.id].g.classList.toggle("checking", a.id === id); }
    function flashEdited() {
      svg.classList.remove("just-applied");
      void svg.getBoundingClientRect();
      svg.classList.add("just-applied");
      setTimeout(() => svg.classList.remove("just-applied"), 2600);
    }
    return { setSearching, markAtoll, flashEdited, zoomTo, zoomBy, refit, setState, setNetwork, setBoats, highlightRoute, bboxOf, project, centreOf };
  }

  window.MandarinMap = { createMap };
})();
