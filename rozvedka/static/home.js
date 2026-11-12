/* Home page: the search box's suggestions.
   Suggestions come from /api/suggest; each one opens the Documents list it counts. Recent searches are kept in
   this browser only (localStorage) and can be cleared. */
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);

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
    const form = $(".h-console");
    if (form) consoleSearch(form);
  });
})();
