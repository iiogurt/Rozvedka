// The kept scope: a publisher kind, a range of years and a country or coalition chosen on one page can be kept and
// are then applied on the other pages that filter by them – the Reports list, Compare, Events, Series, Named
// together, the topic charts and maps. A line above the page always says what is kept and whether this page uses
// it. Kept in this tab's sessionStorage only, never sent anywhere; the address of a page still says all it shows.
(() => {
  "use strict";
  const KEY = "rz-scope", FIELDS = ["type", "year_from", "year_to", "country", "coalition"];
  // pages whose filters are in the address (the server applies them) and which of the fields each one takes
  const GET = {"/documents": FIELDS, "/compare": FIELDS, "/events": ["country"], "/series": ["country"]};
  // pages whose form (#scope) asks for the data itself
  const LIVE = ["/network", "/trends", "/trends/terms", "/trends/matrix", "/topics/map", "/map/mentions"];
  const WHAT = {type: "publisher kind", year_from: "years", year_to: "years", country: "country", coalition: "coalition"};
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const bar = document.getElementById("kept");
  if (!bar) return;
  const read = () => { try { const s = JSON.parse(sessionStorage.getItem(KEY)); return s && s.v ? s : {v: {}, l: {}}; } catch (e) { return {v: {}, l: {}}; } };
  const write = (s) => { try { Object.keys(s.v).length ? sessionStorage.setItem(KEY, JSON.stringify(s)) : sessionStorage.removeItem(KEY); } catch (e) { /* storage blocked: nothing is kept */ } };

  const path = location.pathname.replace(/(.)\/$/, "$1");
  const params = new URLSearchParams(location.search);
  const form = GET[path] ? document.querySelector(`main form[method=get][action="${path}"]`)
    : LIVE.includes(path) ? document.getElementById("scope") : null;
  const field = (k) => { const el = form && form.elements[k]; return el && el.tagName && el.type !== "hidden" ? el : null; };
  const takes = !form ? [] : GET[path] || FIELDS.filter(field);            // the fields this page filters by
  const has = (el, v) => el.tagName !== "SELECT" || [...el.options].some((o) => o.value === v);

  // what this page shows now: values, and their names as the page words them
  function shown() {
    const v = {}, l = {};
    for (const k of takes) {
      const el = field(k);
      let val = GET[path] ? params.get(k) || "" : el ? el.value : "";
      if (GET[path] && path === "/documents" && k.startsWith("year_") && !val && /^\d{4}$/.test(params.get("year") || "")) val = params.get("year");
      if (!val) continue;
      v[k] = val;
      const o = el && el.tagName === "SELECT" && [...el.options].find((x) => x.value === val);
      l[k] = o ? o.textContent.trim().replace(/^Reports from /, "") : val;
    }
    return {v, l};
  }
  function words(s) {
    const out = [];
    if (s.v.type) out.push(s.l.type || s.v.type);
    if (s.v.year_from || s.v.year_to) out.push(s.v.year_from === s.v.year_to ? s.v.year_from : `${s.v.year_from || "…"}–${s.v.year_to || "…"}`);
    if (s.v.country) out.push(s.l.country || s.v.country);
    if (s.v.coalition) out.push(s.l.coalition || s.v.coalition);
    return out.map(esc).join(" · ");
  }
  const query = (s, fields) => { const q = new URLSearchParams(); for (const k of fields) if (s.v[k]) q.set(k, s.v[k]); return q; };

  // the menu's links to the pages that take the scope carry it
  function links(s) {
    for (const a of document.querySelectorAll(".rail a[href], .sectionnav a[href], .mobmenu a[href]")) {
      const to = a.dataset.href || a.getAttribute("href");
      if (!GET[to]) continue;
      a.dataset.href = to;
      const q = query(s, GET[to]).toString();
      a.setAttribute("href", q ? `${to}?${q}` : to);
    }
  }

  function apply(s) {
    if (GET[path]) {
      for (const k of takes) if (s.v[k]) params.set(k, s.v[k]);
      if (path === "/documents" && (s.v.year_from || s.v.year_to)) params.delete("year");
      params.delete("page");
      location.search = params.toString();
      return;
    }
    let changed = false;
    for (const k of takes) {
      const el = field(k);
      if (s.v[k] && el.value !== s.v[k] && has(el, s.v[k])) { el.value = s.v[k]; changed = true; }
    }
    if (changed) form.dispatchEvent(new Event("change", {bubbles: true}));
  }

  function draw() {
    const s = read(), now = shown();
    const kept = Object.keys(s.v), here = Object.keys(now.v);
    links(s);
    if (!kept.length && !here.length) { bar.hidden = true; return; }
    let html = '<span class="kept-l">Scope</span>';
    if (!kept.length) {
      html += `<span>nothing kept · this page: <b>${words(now)}</b></span>` +
        '<button type="button" data-do="keep" title="Open the other pages that filter by publisher kind, years or country with this choice (this tab only)">keep on other pages</button>';
    } else {
      const usable = kept.filter((k) => takes.includes(k) && (GET[path] || has(field(k), s.v[k])));
      const same = usable.every((k) => now.v[k] === s.v[k]);
      const missing = [...new Set(kept.filter((k) => !usable.includes(k)).map((k) => WHAT[k]))];
      html += `<b>${words(s)}</b>`;
      if (!usable.length) html += "<span>· not used on this page – it has no such filter</span>";
      else if (same) html += `<span>· applied here${missing.length ? ` except ${esc(missing.join(", "))} – no such filter on this page` : ""}</span>`;
      else html += `<span>· this page shows ${here.length ? `<b>${words(now)}</b>` : "everything"}</span>` +
        '<button type="button" data-do="apply">apply the kept scope</button>' +
        (here.length ? '<button type="button" data-do="keep">keep this one instead</button>' : "");
      html += '<button type="button" class="kept-x" data-do="clear" title="Stop keeping this scope">✕</button>';
    }
    bar.innerHTML = html;
    bar.hidden = false;
  }

  bar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-do]");
    if (!b) return;
    const s = read();
    if (b.dataset.do === "apply") { apply(s); draw(); return; }
    if (b.dataset.do === "clear") write({v: {}, l: {}});
    if (b.dataset.do === "keep") {                       // this page's choice replaces what it can set; the rest stays
      const now = shown();
      for (const k of takes) { delete s.v[k]; delete s.l[k]; }
      Object.assign(s.v, now.v); Object.assign(s.l, now.l);
      write(s);
    }
    draw();
  });
  if (form && !GET[path]) form.addEventListener("change", () => setTimeout(draw, 0));

  // a form-driven page opened by its plain address takes the kept scope by itself (these pages write their choice
  // into the address as they load, so the address asked for is read from the navigation itself)
  const nav = performance.getEntriesByType("navigation")[0];
  const asked = nav ? new URL(nav.name, location.href).search : location.search;
  if (form && !GET[path] && !asked && Object.keys(read().v).length) apply(read());
  draw();
})();
