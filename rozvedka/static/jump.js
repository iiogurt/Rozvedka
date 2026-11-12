// Jump to anything (Ctrl K, or the button in the header): type a name, get the page of the country, agency, actor,
// topic, report or network entity that carries it (/api/jump). And the trail: the pages opened in this tab, in order,
// as a row above the page – kept in this tab's sessionStorage only, never sent anywhere.
(() => {
  "use strict";
  const KEY = "rz-trail", KEEP = 8;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const read = () => { try { return JSON.parse(sessionStorage.getItem(KEY)) || []; } catch (e) { return []; } };
  const write = (t) => { try { sessionStorage.setItem(KEY, JSON.stringify(t)); } catch (e) { /* storage blocked: no trail */ } };

  // ── trail ──
  const here = location.pathname + location.search;
  const title = document.title.replace(/\s*·\s*Rozvedka$/, "").split(" · ")[0].trim() || "Home";
  let trail = read();
  const seen = trail.findIndex((x) => x.u === here);
  if (seen >= 0) trail = trail.slice(0, seen);            // back at an earlier page: the trail is cut to it
  trail.push({u: here, t: title});
  trail = trail.slice(-KEEP);
  write(trail);
  const bar = document.getElementById("trail");
  if (bar && trail.length > 1) {
    bar.innerHTML = '<span class="trail-l">Trail</span>' + trail.slice(0, -1).map((x) =>
      `<a href="${esc(x.u)}">${esc(x.t)}</a><span aria-hidden="true">→</span>`).join("") +
      `<b>${esc(title)}</b><button type="button" class="trail-x" title="Forget this trail">✕</button>`;
    bar.hidden = false;
    bar.querySelector(".trail-x").addEventListener("click", () => { write([{u: here, t: title}]); bar.hidden = true; });
  }

  // ── jump box ──
  const box = document.getElementById("jump");
  if (!box || !box.showModal) return;
  const input = box.querySelector("input"), list = box.querySelector("[role=listbox]");
  let items = [], active = -1, timer = 0, seq = 0;

  function setActive(i) {
    active = i;
    const opts = list.querySelectorAll("[role=option]");
    opts.forEach((li, k) => li.setAttribute("aria-selected", String(k === i)));
    if (opts[i]) { opts[i].scrollIntoView({block: "nearest"}); input.setAttribute("aria-activedescendant", opts[i].id); }
    else input.removeAttribute("aria-activedescendant");
  }
  function render(groups, q) {
    items = [];
    let html = "";
    const row = (it, glyph) => {
      const i = items.length;
      items.push(it.url);
      return `<li role="option" id="jp-${i}"><a href="${esc(it.url)}" tabindex="-1">${glyph ? `<i class="gl gl-${glyph}" aria-hidden="true"></i>` : ""}` +
        `${it.flag ? `<img class="flag-sm" src="${esc(it.flag)}" alt="" width="16" height="12">` : ""}<span class="jp-l">${esc(it.label)}</span>` +
        `<span class="jp-s">${esc(it.sub || "")}</span></a></li>`;
    };
    for (const g of groups) {
      html += `<li class="jp-g" role="presentation">${esc(g.name)}</li>`;
      for (const it of g.items) html += row(it, g.glyph);
    }
    if (q) {
      html += '<li class="jp-g" role="presentation">Full text</li>' +
        row({url: "/search?q=" + encodeURIComponent(q), label: `Search the reports for “${q}”`, sub: "words in the text"}, "reports");
      if (!groups.length) html = '<li class="jp-none" role="presentation">Nothing carries this name.</li>' + html;
    }
    list.innerHTML = html;
    setActive(items.length ? 0 : -1);
  }
  function ask() {
    const q = input.value.trim(), mine = ++seq;
    clearTimeout(timer);
    if (q.length < 2) {                                    // nothing typed: where you have been, newest first
      const back = read().slice(0, -1).reverse().map((x) => ({url: x.u, label: x.t, sub: x.u}));
      return render(back.length ? [{name: "Where you have been in this tab", glyph: "", items: back}] : [], "");
    }
    timer = setTimeout(() => {
      fetch("/api/jump?q=" + encodeURIComponent(q)).then((r) => r.json())
        .then((d) => { if (mine === seq) render(d.groups, q); }).catch(() => { /* keep what is shown */ });
    }, 130);
  }
  function open() {
    if (box.open) return;
    input.value = "";
    box.showModal();
    ask();
    input.focus();
  }
  input.addEventListener("input", ask);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(items.length - 1, active + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(0, active - 1)); }
    else if (e.key === "Enter" && items[active]) { e.preventDefault(); location.href = items[active]; }
  });
  box.addEventListener("click", (e) => { if (e.target === box) box.close(); });      // a click on the backdrop
  document.querySelectorAll(".jump-open").forEach((b) => b.addEventListener("click", open));
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") { e.preventDefault(); open(); }
  });
})();
