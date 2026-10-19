/* Timeline (/timeline): lanes of states and actors on one time axis, drawn with vis-timeline from /api/timeline.
   Each lane holds its events (Wikidata, EuRepoC, UCDP) and the library's dated records, with UCDP's deaths per month
   as a shaded background and a thin row of the library's reports per year under it (each year opens its list).
   At every zoom a lane draws only its heaviest events that fit and says how many it hides – nothing is merged.
   The whole view (lanes, period, selection, wall mode) lives in the address, so a view can be opened on a big screen
   as it is. Clicking an event draws its chain: the relations a source states (Wikidata, or written by hand with their
   evidence), up to DEPTH steps to its causes and its effects, as arrows between the events on screen.
   Keys: F full screen, W wall mode, 0 fit, + / − zoom, ← / → move, Esc clears the chain. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (n) => Number(n || 0).toLocaleString("en");
  const DAY = 864e5, DEPTH = 3, PARTS = 20;     // a whole with more parts shows its heaviest PARTS, the rest as a count
  const REL = { caused: { color: "--warn", line: 0 }, "immediately caused": { color: "--err", line: 0 },
                "response to": { color: "--accent", line: 0 }, "followed by": { color: "--muted", line: 1 } };
  const wrap = $("#tl-wrap"), panel = $("#tl-panel");
  const SOURCE = { wikidata: "Wikidata", eurepoc: "EuRepoC", ucdp: "UCDP", library: "library" };

  // ── state in the address ──
  const url = new URL(window.location);
  let lanes = url.searchParams.getAll("lane");
  const state = { start: url.searchParams.get("start"), end: url.searchParams.get("end"), sel: url.searchParams.get("sel"),
                  wall: url.searchParams.get("wall") === "1" };
  let data = null, all = [], timeline = null, forced = new Set(), arrows = null;
  let chain = { keys: new Set(), parts: new Set(), used: [] };
  const items = new vis.DataSet(), groups = new vis.DataSet();

  function save() {
    const u = new URL(window.location);
    u.search = "";
    for (const l of lanes) u.searchParams.append("lane", l);
    if (timeline) {
      const w = timeline.getWindow();
      u.searchParams.set("start", w.start.toISOString().slice(0, 10));
      u.searchParams.set("end", w.end.toISOString().slice(0, 10));
    }
    if (state.sel) u.searchParams.set("sel", state.sel);
    if (state.wall) u.searchParams.set("wall", "1");
    history.replaceState(null, "", u);
  }

  // ── dates: "2017" → 1 Jan 2017, "2017-06" → 1 Jun 2017; a range's end is exclusive in vis-timeline ──
  const day = (s) => new Date((String(s) + "-01-01").slice(0, 10) + "T00:00:00Z");
  function span(it) {
    const start = day(it.start);
    // known only to the year: a bar over the whole year ("some time in 2024"), not a point on 1 January
    if (String(it.start).length === 4 && (!it.end || it.end === it.start)) return { start, end: day(Number(it.start) + 1), year: true };
    const end = it.end && it.end !== it.start ? new Date(day(it.end).getTime() + DAY) : null;
    return { start, end: end && end - start > DAY ? end : null };
  }
  // a span narrower than 1/12 of the view is drawn as a point (its dates in the tooltip): a short bar cuts its label off
  const minSpan = () => { if (!timeline) return 365 * DAY; const w = timeline.getWindow(); return (w.end - w.start) / 12; };

  // a lane's label as an element: vis-timeline passes strings through its XSS filter, which drops the button
  function laneLabel(l, hidden) {
    const div = document.createElement("div");
    div.className = "tl-lane";
    const flag = l.kind === "country" ? `<img class="flag-sm" src="/static/flags/${esc(l.value.toLowerCase())}.svg" alt="" width="18" height="13"> ` : "";
    const name = l.href ? `<a href="${esc(l.href)}">${esc(l.label)}</a>` : esc(l.label);
    div.innerHTML = `${flag}${name}<button type="button" class="tl-rm" data-lane="${esc(l.id)}" title="Remove this lane" aria-label="Remove ${esc(l.label)}">×</button>
      <div class="tl-lane-n">${num(l.events)} events${hidden ? ` · <b>${num(hidden)}</b> hidden – zoom in` : ""}</div>`;
    return div;
  }

  function itemOf(it, min) {
    const sp = span(it), start = sp.start, end = sp.year || (sp.end && sp.end - start >= min) ? sp.end : null;
    const year = String(it.start).length === 4;
    const cls = `src-${it.source}${it.preliminary ? " prelim" : ""}${sp.year ? " tl-year" : ""}${chain.keys.has(it.key) ? " tl-chain" : chain.parts.has(it.key) ? " tl-part" : ""}`;
    const label = it.label.length > 70 ? it.label.slice(0, 68) + "…" : it.label;
    const title = `${esc(it.label)}<br><span class="muted">${esc(it.start)}${it.end && it.end !== it.start ? " – " + esc(it.end) : ""}${year ? " (year only)" : ""}
      · ${esc(it.kind)} · ${SOURCE[it.source]}${it.deaths ? ` · ${num(it.deaths)} deaths` : ""}${it.preliminary ? " · preliminary" : ""}</span>`;
    return { id: it.id, group: it.lane, start, end: end || undefined, type: end ? "range" : "point", content: esc(label),
             className: cls, title };
  }

  // ── the zoom threshold: each lane keeps the heaviest events in view that fit ──
  function visibleIds() {
    const w = timeline ? timeline.getWindow() : { start: day(1999), end: new Date() };
    const width = $("#tl").clientWidth || 1200, keep = Math.max(6, Math.round(width / (state.wall ? 130 : 85)));
    const byLane = {};
    for (const it of all) {
      const { start, end } = span(it);
      if ((end || start) < w.start || start > w.end) continue;
      (byLane[it.lane] = byLane[it.lane] || []).push(it);
    }
    const ids = new Set(forced), hidden = {};
    for (const [lane, list] of Object.entries(byLane)) {
      list.sort((a, b) => b.rank - a.rank || String(b.start).localeCompare(String(a.start)));
      list.slice(0, keep).forEach((it) => ids.add(it.id));
      hidden[lane] = Math.max(0, list.length - keep);
    }
    return { ids, hidden };
  }

  let pending = null;
  function refresh() {
    clearTimeout(pending);
    pending = setTimeout(() => {
      const { ids, hidden } = visibleIds();
      const now = new Set(items.getIds().filter((id) => !String(id).startsWith("bg|") && !String(id).startsWith("rp|")));
      const min = minSpan();
      items.remove([...now].filter((id) => !ids.has(id)));
      items.update(all.filter((it) => ids.has(it.id)).map((it) => itemOf(it, min)));     // new ones, and bar or point for this zoom
      groups.update(data.lanes.map((l) => ({ id: l.id, content: laneLabel(l, hidden[l.id] || 0) })));
      drawArrows();
      save();
    }, 80);
  }

  // ── strips: reports per year (own row under each lane) and UCDP deaths per month (the lane's background) ──
  const heat = (n, max) => (n ? Math.min(5, 1 + Math.floor(4 * Math.log1p(n) / Math.log1p(max))) : 0);
  const deathClass = (n) => (n >= 2000 ? 5 : n >= 500 ? 4 : n >= 100 ? 3 : n >= 25 ? 2 : 1);
  function strips() {
    const out = [];
    for (const l of data.lanes) {
      const s = data.strips[l.id] || { reports: {}, deaths: {} };
      const max = Math.max(1, ...Object.values(s.reports).map((r) => r.n));
      for (const [y, r] of Object.entries(s.reports)) {
        // ends an hour before the next year: touching bars would stack into two rows
        out.push({ id: `rp|${l.id}|${y}`, group: `${l.id}|reports`, start: day(y), end: new Date(day(Number(y) + 1) - 36e5), type: "range",
                   content: String(r.n), className: `tl-rp h${heat(r.n, max)}`, title: `${num(r.n)} report${r.n === 1 ? "" : "s"} of ${y} in the library naming ${esc(l.label)} – click to list them` });
      }
      for (const [m, d] of Object.entries(s.deaths)) {
        const [y, mo] = m.split("-").map(Number);
        out.push({ id: `bg|${l.id}|${m}`, group: l.id, start: new Date(Date.UTC(y, mo - 1, 1)), end: new Date(Date.UTC(y, mo, 1)),
                   type: "background", className: `tl-d${deathClass(d.n)}`,
                   title: `${esc(l.label)}, ${m}: ${num(d.n)} deaths in organised violence (UCDP${d.preliminary ? ", preliminary" : ""})` });
      }
    }
    return out;
  }

  // ── chains: the stated relations around one event ──
  function chainOf(key) {
    const fwd = {}, back = {};
    for (const l of data.links || []) {
      if (l.rel === "part of") continue;
      (fwd[l.src] = fwd[l.src] || []).push(l);
      (back[l.dst] = back[l.dst] || []).push(l);
    }
    const keys = new Set([key]), used = new Set(), steps = { up: [], down: [] };
    const walk = (map, end, dir) => {
      let front = [key];
      for (let depth = 1; depth <= DEPTH && front.length; depth++) {
        const next = [];
        for (const k of front) for (const l of map[k] || []) {
          used.add(l);
          const other = l[end];
          if (!keys.has(other)) { keys.add(other); next.push(other); steps[dir].push({ key: other, depth, link: l }); }
        }
        front = next;
      }
    };
    walk(back, "src", "up");
    walk(fwd, "dst", "down");
    const wholes = [], members = [], rank = (k) => Math.max(0, ...all.filter((it) => it.key === k).map((it) => it.rank));
    for (const l of data.links || []) {
      if (l.rel !== "part of") continue;
      if (l.src === key) wholes.push(l);
      if (l.dst === key) members.push(l);
    }
    members.sort((a, b) => rank(b.src) - rank(a.src));
    const parts = new Set([...wholes.map((l) => l.dst), ...members.slice(0, PARTS).map((l) => l.src)]);
    return { keys, parts, used: [...used], steps, wholes, members };
  }
  // the timeline item of an event: in the selected item's lane if it is there, else in the first lane that has it
  function instance(key, lane) {
    const found = all.filter((it) => it.key === key);
    return (found.find((it) => it.lane === lane) || found[0] || {}).id;
  }
  function drawArrows() {
    if (!window.RzArrow || !timeline) return;
    if (!arrows) arrows = new window.RzArrow(timeline, [], { followRelationships: true, strokeWidth: state.wall ? 3 : 2, hideWhenItemsNotVisible: false });
    for (const id of arrows.getIdArrows()) arrows.removeArrow(id);
    if (!chain.used.length) return;
    const css = getComputedStyle(document.documentElement), lane = chain.lane;
    for (const l of chain.used) {
      const a = instance(l.src, lane), b = instance(l.dst, lane);
      if (!a || !b || !items.get(a) || !items.get(b)) continue;
      const r = REL[l.rel] || REL.caused;
      // straight from the middle of the cause to the middle of the effect, the head always at the effect (the default
      // curve joins the facing ends and can put the head on the cause when the effect is a bar that starts earlier)
      arrows.addArrow({ id: `${l.src}>${l.rel}>${l.dst}`, id_item_1: a, id_item_2: b, direction: 1, line: r.line, type: 1,
                        color: css.getPropertyValue(r.color).trim() || "#e69f00",
                        title: `${l.src_label} – ${l.rel} – ${l.dst_label} (${l.stated_by === "hand" ? "written by hand" : "Wikidata " + l.property})` });
    }
  }
  function setChain(it) {
    const c = it && it.key ? chainOf(it.key) : null;
    chain = c && (c.used.length || c.parts.size) ? { ...c, lane: it.lane } : { keys: new Set(), parts: new Set(), used: [] };
    wrap.classList.toggle("tl-focus", !!chain.used.length || !!chain.parts.size);
    forced = new Set([it && it.id, ...[...chain.keys, ...chain.parts].map((k) => instance(k, chain.lane))].filter(Boolean));
    items.update(all.filter((x) => items.get(x.id)).map((x) => itemOf(x, minSpan())));
    refresh();
  }
  function chainList(c) {
    const row = (s, arrow) => {
      const id = instance(s.key, chain.lane), label = s.link.src === s.key ? s.link.src_label : s.link.dst_label;
      const name = id ? `<a href="#" data-focus="${esc(s.key)}">${esc(label)}</a>` : `${esc(label)} <span class="muted">(not in these lanes)</span>`;
      return `<li><span class="muted">${arrow.repeat(s.depth)}</span> ${name} <span class="muted small">${esc(s.link.rel)}${s.link.stated_by === "hand" ? `, <a href="${esc(s.link.evidence)}" target="_blank" rel="noopener">by hand</a>` : ""}</span></li>`;
    };
    if (!c || !(c.steps.up.length || c.steps.down.length || c.wholes.length || c.members.length)) return '<p class="muted small">No chain: no source states a cause, effect or sequence for this event.</p>';
    return `${c.steps.up.length ? `<h3 class="tl-ph3">Back to its causes</h3><ul class="tl-list tl-chainlist small">${c.steps.up.map((s) => row(s, "←")).join("")}</ul>` : ""}
      ${c.steps.down.length ? `<h3 class="tl-ph3">Forward to its effects</h3><ul class="tl-list tl-chainlist small">${c.steps.down.map((s) => row(s, "→")).join("")}</ul>` : ""}
      ${c.wholes.length ? `<h3 class="tl-ph3">Part of</h3><ul class="tl-list small">${c.wholes.map((l) => `<li>${instance(l.dst, chain.lane) ? `<a href="#" data-focus="${esc(l.dst)}">${esc(l.dst_label)}</a>` : esc(l.dst_label)}</li>`).join("")}</ul>` : ""}
      ${c.members.length ? `<h3 class="tl-ph3">Its parts <span class="muted">${c.members.length > PARTS ? `– the ${PARTS} heaviest of ${c.members.length} highlighted` : ""}</span></h3><ul class="tl-list small">${c.members.map((l) => `<li>${instance(l.src, chain.lane) ? `<a href="#" data-focus="${esc(l.src)}">${esc(l.src_label)}</a>` : esc(l.src_label)}</li>`).join("")}</ul>` : ""}`;
  }

  // ── the detail panel ──
  const fmtDate = (e) => esc(e.start) + (e.end && e.end !== e.start ? " – " + esc(e.end) : "");
  function showRecord(it) {
    panel.innerHTML = `<h2 class="tl-ph">${esc(it.label)}</h2><p class="small">${esc(it.start)} · ${esc(it.kind)} · library record</p>
      ${it.detail ? `<p class="small">${esc(it.detail)}</p>` : ""}
      <p class="small">Source: ${it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.by || it.url)}</a>` : esc(it.by || "")}</p>`;
  }
  async function showEvent(key) {
    panel.innerHTML = '<p class="muted small">Loading…</p>';
    const r = await fetch(`/api/timeline/event/${encodeURIComponent(key)}`);
    if (!r.ok) { panel.innerHTML = '<p class="muted small">This event is no longer stored.</p>'; return; }
    const e = await r.json();
    const actors = e.actors.map((a) => `<li><span class="muted">${esc(a.role)}:</span> ${a.actor_key ? `<a href="/actors/${esc(a.actor_key)}">${esc(a.actor_label || a.name)}</a>`
      : `<span title="${esc(a.reason || "")}">${esc(a.name)}</span>`}${a.actor_key && a.reason ? ` <span class="muted small">(${esc(a.reason)})</span>` : ""}</li>`).join("");
    const rel = e.links.map((l) => {
      const out = l.src === e.key, other = out ? l.dst : l.src, otherLabel = out ? l.dst_label : l.src_label;
      const here = all.find((it) => it.key === other);
      const link = here ? `<a href="#" data-focus="${esc(other)}">${esc(otherLabel)}</a>` : `<a href="https://www.wikidata.org/wiki/${esc(other)}" target="_blank" rel="noopener">${esc(otherLabel)}</a>`;
      return `<li>${out ? `→ ${esc(l.rel)} ${link}` : `← ${link} ${esc(l.rel)} this`} <span class="muted small">(Wikidata ${esc(l.property)})</span></li>`;
    }).join("");
    panel.addEventListener("error", flagFallback, true);
    const c = chain.used.length || chain.parts.size ? chain : null;
    panel.innerHTML = `<h2 class="tl-ph">${esc(e.label)}${e.preliminary ? ' <span class="muted" title="preliminary">◌</span>' : ""}</h2>
      <p class="small">${fmtDate(e)} · ${esc(e.kind)}${e.deaths != null ? ` · <b>${num(e.deaths)}</b> deaths` : ""}</p>
      ${e.description ? `<p class="small">${esc(e.description)}</p>` : ""}
      ${e.countries.length ? `<p class="small">${e.countries.map((c) => `<img class="flag-sm" src="/static/flags/${esc(c.toLowerCase())}.svg" alt="${esc(c)}" title="${esc(c)}" width="18" height="13" data-code="${esc(c)}">`).join(" ")}</p>` : ""}
      ${actors ? `<h3 class="tl-ph3">Who</h3><ul class="tl-list small">${actors}</ul>` : ""}
      <div class="tl-chainbox">${chainList(c)}</div>
      ${rel ? `<details class="small"><summary>All stated relations (${e.links.length})</summary><ul class="tl-list small">${rel}</ul></details>` : ""}
      <p class="small">Source: <a href="${esc(e.url)}" target="_blank" rel="noopener">${SOURCE[e.source]}</a> ·
        <a href="/events?q=${encodeURIComponent(e.label.slice(0, 40))}">in the event list</a></p>`;
  }
  // a state without a flag file shows its code
  function flagFallback(ev) {
    const img = ev.target;
    if (img.tagName === "IMG" && img.dataset.code) img.replaceWith(document.createTextNode(img.dataset.code));
  }
  function focusEvent(key) {
    const it = all.find((x) => x.key === key);
    if (!it) return;
    forced.add(it.id);
    refresh();
    setTimeout(() => { timeline.setSelection([it.id], { focus: true }); select(it.id); }, 150);
  }
  function select(id) {
    if (!id) return;
    if (String(id).startsWith("rp|")) { const [, lane, y] = String(id).split("|"); const r = data.strips[lane].reports[y]; if (r) window.location.href = r.url; return; }
    const it = all.find((x) => x.id === id);
    if (!it) return;
    state.sel = it.key || null;
    setChain(it);
    if (it.key) showEvent(it.key); else showRecord(it);
    save();
  }
  panel.addEventListener("click", (ev) => {
    const a = ev.target.closest("[data-focus]");
    if (a) { ev.preventDefault(); focusEvent(a.dataset.focus); }
  });

  // ── loading and lanes ──
  async function load() {
    const q = new URLSearchParams();
    for (const l of lanes) q.append("lane", l);
    data = await fetch(`/api/timeline?${q}`).then((r) => r.json());
    lanes = data.lanes.map((l) => l.id);
    all = data.items;
    groups.clear();
    groups.add(data.lanes.flatMap((l, i) => [
      { id: l.id, content: laneLabel(l, 0), order: 2 * i, className: "tl-g" },
      { id: `${l.id}|reports`, content: '<span class="tl-rp-h">reports per year</span>', order: 2 * i + 1, className: "tl-g-rp" },
    ]));
    items.clear();
    items.add(strips());
    if (!timeline) {
      timeline = new vis.Timeline($("#tl"), items, groups, {
        stack: true, orientation: { axis: "top", item: "top" }, height: "100%", verticalScroll: true, groupOrder: "order",
        zoomMin: 7 * DAY, zoomMax: 40 * 365 * DAY, min: day(1990), max: new Date(Date.now() + 365 * DAY),
        margin: { item: { horizontal: 0, vertical: 4 }, axis: 6 },   // 0: the year bars of the report strip touch without stacking tooltip: { followMouse: true, overflowMethod: "cap", delay: 120 },
        showCurrentTime: true, selectable: true, multiselect: false, start: state.start ? new Date(state.start) : day(2014),
        end: state.end ? new Date(state.end) : new Date(Date.now() + 60 * DAY),
      });
      timeline.on("rangechanged", refresh);
      timeline.on("select", (p) => (p.items.length ? select(p.items[0]) : clearChain()));
    }
    if (state.sel) {
      const it = all.find((x) => x.key === state.sel);
      if (it) { forced.add(it.id); setTimeout(() => { timeline.setSelection([it.id]); select(it.id); }, 200); }
    }
    refresh();
  }

  function clearChain() {
    if (!chain.used.length && !chain.parts.size) return;
    state.sel = null;
    setChain(null);
  }

  function addLane(l) { if (l && !lanes.includes(l)) { lanes.push(l); load(); } }
  $("#tl").addEventListener("click", (ev) => {
    const b = ev.target.closest(".tl-rm");
    if (!b) return;
    ev.stopPropagation();
    lanes = lanes.filter((l) => l !== b.dataset.lane);
    if (!lanes.length) lanes = ["country:UA"];
    load();
  }, true);
  const form = $("#tl-add");
  form.country.addEventListener("change", () => { addLane(form.country.value && `country:${form.country.value}`); form.country.value = ""; });
  let suggest = {}, timer = null;
  form.actor.addEventListener("input", () => {
    const q = form.actor.value.trim();
    if (suggest[q]) { addLane(`actor:${suggest[q]}`); form.actor.value = ""; return; }
    clearTimeout(timer);
    if (q.length < 2) return;
    timer = setTimeout(async () => {
      const r = await fetch(`/api/actors/suggest?q=${encodeURIComponent(q)}`).then((x) => x.json());
      suggest = {};
      $("#tl-actors").innerHTML = r.actors.filter((a) => a.kind !== "country").map((a) => { suggest[a.label] = a.key; return `<option value="${esc(a.label)}">${esc(a.kind_name)} · ${num(a.docs)} reports</option>`; }).join("");
    }, 220);
  });

  // ── full screen, wall mode, keys ──
  function setWall(on) {
    state.wall = on;
    wrap.classList.toggle("tl-wall", on);
    $("#tl-wall").setAttribute("aria-pressed", on ? "true" : "false");
    if (timeline) { timeline.redraw(); refresh(); }
    save();
  }
  $("#tl-wall").addEventListener("click", () => setWall(!state.wall));
  $("#tl-full").addEventListener("click", () => (document.fullscreenElement ? document.exitFullscreen() : wrap.requestFullscreen()));
  $("#tl-fit").addEventListener("click", () => timeline && timeline.fit());
  document.addEventListener("fullscreenchange", () => { wrap.classList.toggle("tl-full", !!document.fullscreenElement); if (timeline) timeline.redraw(); });
  document.addEventListener("keydown", (ev) => {
    if (ev.target.closest("input, select, textarea") || ev.ctrlKey || ev.metaKey || ev.altKey || !timeline) return;
    const w = timeline.getWindow(), step = (w.end - w.start) * 0.2;
    if (ev.key === "f" || ev.key === "F") $("#tl-full").click();
    else if (ev.key === "w" || ev.key === "W") setWall(!state.wall);
    else if (ev.key === "0") timeline.fit();
    else if (ev.key === "+" || ev.key === "=") timeline.zoomIn(0.4);
    else if (ev.key === "-" || ev.key === "_") timeline.zoomOut(0.4);
    else if (ev.key === "ArrowLeft") timeline.setWindow(w.start - step, w.end - step);
    else if (ev.key === "ArrowRight") timeline.setWindow(+w.start + step, +w.end + step);
    else if (ev.key === "Escape") { timeline.setSelection([]); clearChain(); return; }
    else return;
    ev.preventDefault();
  });

  if (!lanes.length) lanes = (wrap.dataset.lanes || "").split(",").filter(Boolean);
  setWall(state.wall);
  load();
})();
