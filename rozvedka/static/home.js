/* Home page: the ASCII radar in the banner and the search console's suggestions.
   The radar is decoration only (aria-hidden); it stands still for viewers who prefer reduced motion.
   Suggestions come from /api/suggest; each one opens the Documents list it counts. Recent searches are kept in
   this browser only (localStorage) and can be cleared. */
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);

  // ------------------------------------------------------------------ radar
  function radar(pre) {
    const W = 39, H = 17, cx = (W - 1) / 2, cy = (H - 1) / 2, R = 8;      // a cell is about twice as tall as wide
    const TRAIL = ["█", "▓", "▒", "░", "·"];
    const blips = [[0.7, 0.62], [2.1, 0.35], [2.9, 0.8], [4.2, 0.55], [5.3, 0.9], [5.9, 0.28]].map(([a, r]) => ({
      x: Math.round(cx + Math.cos(a) * r * R * 2), y: Math.round(cy - Math.sin(a) * r * R)}));
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let sweep = 1.0;

    function frame() {
      let out = "";
      for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
          const dx = (x - cx) / 2, dy = cy - y, d = Math.hypot(dx, dy);
          const a = (Math.atan2(dy, dx) + 2 * Math.PI) % (2 * Math.PI);
          const behind = (sweep - a + 2 * Math.PI) % (2 * Math.PI);          // radians since the beam passed
          const blip = blips.find((b) => b.x === x && b.y === y);
          let ch = " ", cls = "";
          if (Math.abs(d - R) < 0.45) { ch = "·"; cls = "r"; }
          else if (d > R) { ch = " "; }
          else if (blip) { ch = behind < 2.2 ? "◉" : "∘"; cls = behind < 2.2 ? "bh" : "b"; }
          else if (x === cx && y === cy) { ch = "+"; cls = "r"; }
          else if (behind < 0.9 && d > 0.6) { ch = TRAIL[Math.min(4, Math.floor(behind / 0.18))]; cls = "s"; }
          else if (Math.abs(d - R / 2) < 0.4) { ch = "·"; cls = "g"; }
          else if (y === cy) { ch = "-"; cls = "g"; }
          else if (x === cx) { ch = "¦"; cls = "g"; }
          out += cls ? `<span class="${cls}">${ch}</span>` : ch;
        }
        out += "\n";
      }
      pre.innerHTML = out;
    }
    let last = 0;
    function tick(t) {
      if (t - last > 70) { sweep = (sweep - 0.07 + 2 * Math.PI) % (2 * Math.PI); frame(); last = t; }  // clockwise
      requestAnimationFrame(tick);
    }
    frame();
    if (!still) requestAnimationFrame(tick);
  }

  // ------------------------------------------------------------------ search console
  const RECENT = "rz-recent-searches";
  function recent() {
    try { return JSON.parse(localStorage.getItem(RECENT) || "[]"); } catch (e) { return []; }
  }
  function remember(q) {
    try { localStorage.setItem(RECENT, JSON.stringify([q, ...recent().filter((r) => r !== q)].slice(0, 6))); } catch (e) { /* not kept */ }
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  }

  function consoleSearch(form) {
    const input = $("#hq", form), list = $("#h-suggest", form);
    let items = [], active = -1, timer = 0, seq = 0, prefix = "";

    function open(on) { list.hidden = !on; input.setAttribute("aria-expanded", String(on)); }
    function setActive(i) {
      active = i;
      list.querySelectorAll("[role=option]").forEach((li, k) => li.setAttribute("aria-selected", String(k === i)));
      const el = list.querySelectorAll("[role=option]")[i];
      if (el) { el.scrollIntoView({block: "nearest"}); input.setAttribute("aria-activedescendant", el.id); }
      else input.removeAttribute("aria-activedescendant");
    }
    function render(groups, q) {
      items = []; let html = "";
      if (q.trim()) {
        items.push({url: "/search?q=" + encodeURIComponent(q), token: null});
        html += `<li role="option" id="hs-0" class="hs-all"><span class="hs-l">Search the library for <b>${esc(q)}</b></span><span class="hs-n">⏎</span></li>`;
      }
      for (const g of groups) {
        html += `<li class="hs-g" role="presentation">${esc(g.name)}</li>`;
        for (const it of g.items) {
          const i = items.length; items.push(it);
          html += `<li role="option" id="hs-${i}"><span class="hs-l">${it.flag ? `<img class="flag-sm" src="${esc(it.flag)}" alt="">` : ""}${esc(it.label)} <span class="muted small">${esc(it.sub || "")}</span></span>${it.n === null ? "" : `<span class="hs-n" title="reports listed">${it.n}</span>`}</li>`;
        }
      }
      if (!q.trim()) {
        const r = recent();
        if (r.length) {
          html += `<li class="hs-g" role="presentation">Recent searches <button type="button" class="hs-clear">clear</button></li>`;
          for (const s of r) { const i = items.length; items.push({url: "/search?q=" + encodeURIComponent(s), token: null, q: s}); html += `<li role="option" id="hs-${i}"><span class="hs-l"><code>${esc(s)}</code></span></li>`; }
        }
      }
      list.innerHTML = html;
      list.querySelectorAll("[role=option]").forEach((li, k) => {
        li.addEventListener("mousedown", (e) => { e.preventDefault(); go(k); });
      });
      const clear = $(".hs-clear", list);
      if (clear) clear.addEventListener("mousedown", (e) => { e.preventDefault(); try { localStorage.removeItem(RECENT); } catch (x) { /* ignore */ } render([], ""); });
      open(items.length > 0); setActive(-1);
    }
    function go(k) {
      const it = items[k];
      if (!it) return;
      if (input.value.trim()) remember(input.value.trim());
      window.location.href = it.url;
    }
    function complete(k) {   // Tab: put the suggestion into the query as a filter, keep typing
      const it = items[k];
      if (!it || !it.token) return false;
      input.value = ((prefix ? prefix + " " : "") + it.token + " ");
      fetchSuggest();
      return true;
    }
    function fetchSuggest() {
      const q = input.value, mine = ++seq;
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (!q.trim()) { render([], ""); return; }
        fetch("/api/suggest?q=" + encodeURIComponent(q)).then((r) => r.json()).then((data) => {
          if (mine === seq) { prefix = data.prefix || ""; render(data.groups, q); }
        }).catch(() => open(false));
      }, 140);
    }
    input.addEventListener("input", fetchSuggest);
    input.addEventListener("focus", fetchSuggest);
    input.addEventListener("blur", () => setTimeout(() => open(false), 120));
    input.addEventListener("keydown", (e) => {
      if (list.hidden && e.key === "ArrowDown") { fetchSuggest(); return; }
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(items.length - 1, active + 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(-1, active - 1)); }
      else if (e.key === "Tab" && !list.hidden && active >= 0) { if (complete(active)) e.preventDefault(); }
      else if (e.key === "Escape") { open(false); }
      else if (e.key === "Enter" && !list.hidden && active >= 0) { e.preventDefault(); go(active); }
    });
    form.addEventListener("submit", () => { if (input.value.trim()) remember(input.value.trim()); });
    document.querySelectorAll(".h-op").forEach((b) => b.addEventListener("click", () => {
      input.value = (input.value.replace(/\s*$/, "") + " " + b.dataset.op).replace(/^\s+/, "");
      input.focus(); fetchSuggest();
    }));
    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && !/^(input|textarea|select)$/i.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const pre = $("#radar");
    if (pre) radar(pre);
    const form = $(".h-console");
    if (form) consoleSearch(form);
  });
})();
