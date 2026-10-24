// Themed dropdown that replaces a native <select> while keeping it as the
// source of truth: picking an option sets select.value and fires "change",
// so existing listeners keep working. Options may carry data-sub (second
// line) and data-badge (small tag).

(function () {
  const all = [];
  let openOne = null;

  function enhance(select) {
    if (select.dataset.enhanced) return;
    select.dataset.enhanced = "1";
    select.classList.add("dd-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    const wrap = document.createElement("div");
    wrap.className = "dd";
    select.after(wrap);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dd-trigger";
    btn.setAttribute("aria-haspopup", "listbox");
    btn.setAttribute("aria-expanded", "false");
    const label = select.getAttribute("aria-label") || (select.labels && select.labels[0] && select.labels[0].textContent) || "";
    if (label) btn.setAttribute("aria-label", label);
    if (select.id) { const l = document.querySelector(`label[for="${select.id}"]`); if (l) l.htmlFor = ""; }
    btn.innerHTML = `<span class="dd-value"></span><svg class="dd-chev" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
    wrap.appendChild(btn);

    const list = document.createElement("ul");
    list.className = "dd-list";
    list.setAttribute("role", "listbox");
    list.tabIndex = -1;
    list.hidden = true;
    document.body.appendChild(list);

    let active = -1;
    let typed = "", typedAt = 0;

    function options() { return [...select.options]; }

    function sync() {
      const o = select.options[select.selectedIndex];
      btn.querySelector(".dd-value").innerHTML = o
        ? `<span class="dd-main">${esc(o.text)}</span>${o.dataset.sub ? `<span class="dd-sub">${esc(o.dataset.sub)}</span>` : ""}${o.dataset.badge ? `<span class="dd-badge">${esc(o.dataset.badge)}</span>` : ""}`
        : "";
    }

    function build() {
      list.innerHTML = options().map((o, i) => `<li role="option" id="${uid}-${i}" data-i="${i}" aria-selected="${o.selected}" class="dd-opt${o.selected ? " sel" : ""}${o.disabled ? " dis" : ""}">
        <svg class="dd-check" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="dd-text"><span class="dd-main">${esc(o.text)}</span>${o.dataset.sub ? `<span class="dd-sub">${esc(o.dataset.sub)}</span>` : ""}</span>
        ${o.dataset.badge ? `<span class="dd-badge">${esc(o.dataset.badge)}</span>` : ""}
      </li>`).join("");
    }
    const uid = "dd" + Math.random().toString(36).slice(2, 8);

    function place() {
      const r = btn.getBoundingClientRect();
      const vh = window.innerHeight, vw = window.innerWidth;
      const width = Math.max(r.width, Math.min(320, vw - 24));
      list.style.minWidth = `${Math.round(width)}px`;
      list.style.maxWidth = `${Math.round(vw - 24)}px`;
      const below = vh - r.bottom - 12, above = r.top - 12;
      const up = below < 240 && above > below;
      list.style.maxHeight = `${Math.round(Math.min(380, up ? above : below))}px`;
      list.style.left = `${Math.round(Math.min(r.left, vw - 12 - Math.min(width, vw - 24)))}px`;
      list.style.top = up ? "" : `${Math.round(r.bottom + 6)}px`;
      list.style.bottom = up ? `${Math.round(vh - r.top + 6)}px` : "";
    }

    function setActive(i, scroll = true) {
      const items = list.children;
      if (!items.length) return;
      active = Math.max(0, Math.min(items.length - 1, i));
      [...items].forEach((li, j) => li.classList.toggle("act", j === active));
      list.setAttribute("aria-activedescendant", items[active].id);
      if (scroll) items[active].scrollIntoView({ block: "nearest" });
    }

    function open() {
      if (openOne && openOne !== api) openOne.close();
      build();
      list.hidden = false;
      place();
      btn.setAttribute("aria-expanded", "true");
      wrap.classList.add("open");
      openOne = api;
      setActive(select.selectedIndex);
      list.focus({ preventScroll: true });
    }

    function close(focusBtn) {
      if (list.hidden) return;
      list.hidden = true;
      btn.setAttribute("aria-expanded", "false");
      wrap.classList.remove("open");
      if (openOne === api) openOne = null;
      if (focusBtn) btn.focus();
    }

    function choose(i) {
      const o = select.options[i];
      if (!o || o.disabled) return;
      const changed = select.selectedIndex !== i;
      select.selectedIndex = i;
      sync();
      close(true);
      if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    btn.addEventListener("click", () => (list.hidden ? open() : close()));
    btn.addEventListener("keydown", (e) => {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); open(); }
    });
    list.addEventListener("click", (e) => {
      const li = e.target.closest("[data-i]");
      if (li) choose(Number(li.dataset.i));
    });
    list.addEventListener("mousemove", (e) => {
      const li = e.target.closest("[data-i]");
      if (li && Number(li.dataset.i) !== active) setActive(Number(li.dataset.i), false);
    });
    list.addEventListener("keydown", (e) => {
      const n = list.children.length;
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
      else if (e.key === "Home") { e.preventDefault(); setActive(0); }
      else if (e.key === "End") { e.preventDefault(); setActive(n - 1); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(active); }
      else if (e.key === "Escape") { e.preventDefault(); close(true); }
      else if (e.key === "Tab") { close(false); }
      else if (e.key.length === 1) {
        const now = Date.now();
        typed = now - typedAt > 700 ? e.key.toLowerCase() : typed + e.key.toLowerCase();
        typedAt = now;
        const i = options().findIndex((o) => o.text.toLowerCase().startsWith(typed));
        if (i >= 0) setActive(i);
      }
    });

    const api = { select, sync, close, list, wrap, place };
    all.push(api);
    sync();
    return api;
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  document.addEventListener("mousedown", (e) => {
    if (!openOne) return;
    if (openOne.list.contains(e.target) || openOne.wrap.contains(e.target)) return;
    openOne.close(false);
  });
  window.addEventListener("resize", () => openOne && openOne.place());
  document.addEventListener("scroll", (e) => {
    if (openOne && !openOne.list.contains(e.target)) openOne.close(false);
  }, true);

  window.Dropdown = {
    enhance,
    syncAll() { all.forEach((d) => d.sync()); },
  };
})();
