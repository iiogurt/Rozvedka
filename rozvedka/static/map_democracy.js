/* Ratings over time: every country coloured by one measure for a chosen year – democracy (V-Dem, Freedom House, World
   Bank), security (World Bank, UNODC, SIPRI) or governance (World Bank, Transparency International) – the library's
   states listed with their course since 1990, and the library's sources on top.
   All years come in one request (/api/ratings/map); the slider and the play button only redraw. Every report count
   opens /documents?country=…&year=…&type=official. Colours: blue = the better end of the measure (more democratic,
   safer, cleaner), orange = the worse end (Okabe–Ito, colour-blind safe), always with a label; a measure without a
   better end (military spending) has a single-hue scale. */
(function () {
  "use strict";
  // hover cards fully opaque while open; Leaflet sets 0 when one closes, so only the card under the pointer shows
  L.Tooltip.mergeOptions({ opacity: 1 });
  const $ = (s) => document.querySelector(s);
  const form = $("#dm");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // colours from style.css (rzTokens), read again when the theme is switched: regime types, the worse → better ramp, the
  // yellow low → high ramp of a measure without a better end, no data, the think tanks' credibility, outlines
  const tok = (name) => window.rzTokens.get(name), run = (p, n) => Array.from({ length: n }, (_, i) => tok(p + (i + 1)));
  let REGIME, RAMP, SEQ, NODATA, CRED, LINE;
  function palette() {
    REGIME = Object.fromEntries([0, 1, 2, 3].map((k) => [k, tok(`--regime-${k}`)]));
    RAMP = run("--ramp-", 7);
    SEQ = run("--yel-", 7);
    NODATA = tok("--nodata");
    CRED = Object.fromEntries(["transparent", "partial", "concerns", "redflag", "unassessed"].map((k) => [k, tok(`--pl-${k}`)]));
    LINE = { edge: tok("--map-edge"), line: tok("--map-line"), hover: tok("--map-hover"), spark: tok("--map-spark"),
             ink: tok("--ink"), panel: tok("--panel"), muted: tok("--muted") };
  }
  palette();
  window.rzDark.addEventListener("change", () => { palette(); if (data) { redraw(); drawSources(); } });
  const CHANGE_SPAN = 10, CHANGE_MAX = 0.25;     // years compared; ±0.25 LDI saturates the colour

  let geo, data, agencies = [], layer = null, dots = null, playing = null;
  const byIso = {};

  // ── state in the address ──
  const url = new URL(window.location);
  for (const el of form.elements) {
    const v = url.searchParams.get(el.name);
    if (v == null) continue;
    if (el.type === "checkbox") el.checked = v === "1"; else el.value = v;
  }
  const measure = () => form.measure.value;
  const year = () => Number(form.year.value);

  const map = L.map("map", { worldCopyJump: true, maxZoom: 8, minZoom: 1, zoomSnap: 0.5 }).setView([30, 10], 2);
  map.attributionControl.addAttribution('Country outlines: <a href="https://www.naturalearthdata.com/">Natural Earth</a>');

  // ── values ──
  const idx = (y) => y - data.years[0];
  function val(c, key, y) {
    if (!c) return null;
    if (key === "change") {
      const now = val(c, "vdem_libdem", y), then = val(c, "vdem_libdem", y - CHANGE_SPAN);
      return now == null || then == null ? null : now - then;
    }
    const arr = c.values[key];
    const i = idx(y);
    return arr && i >= 0 && i < arr.length ? arr[i] : null;
  }
  // the latest year in which any country has a value (measures end in different years: RSF 2026, GCI 2024 …)
  function lastYear(key) {
    const k = key === "change" ? "vdem_libdem" : key;
    for (let i = data.years.length - 1; i >= 0; i--)
      if (Object.values(data.countries).some((c) => (c.values[k] || [])[i] != null)) return data.years[i];
    return data.years.at(-1);
  }
  const hasYear = (key, y) => Object.values(data.countries).some((c) => val(c, key, y) != null);
  function colour(key, v) {
    if (v == null) return NODATA;
    if (key === "vdem_regime") return REGIME[Math.round(v)];
    let t;
    if (key === "change") t = (Math.max(-CHANGE_MAX, Math.min(CHANGE_MAX, v)) + CHANGE_MAX) / (2 * CHANGE_MAX);
    else {
      const m = data.measures[key], [lo, hi] = m.scale;
      t = (v - lo) / (hi - lo);
      if (m.better === "low") t = 1 - t;
      if (!m.better) return SEQ[Math.max(0, Math.min(SEQ.length - 1, Math.round(t * (SEQ.length - 1))))];
    }
    return RAMP[Math.max(0, Math.min(RAMP.length - 1, Math.round(t * (RAMP.length - 1))))];
  }
  // the measure's own format ("{:+.2f}", "{:.1f} %", "T{:.0f}" …, as on the server)
  function fmt(key, v) {
    if (v == null) return "–";
    if (key === "vdem_regime") return data.regimes[Math.round(v)];
    if (key === "change") return (v >= 0 ? "+" : "") + v.toFixed(2);
    const f = (data.measures[key] || {}).fmt || "{:.2f}", dec = /\.(\d)f/.exec(f);
    return f.split("{")[0] + (f.includes("+") && v >= 0 ? "+" : "") + v.toFixed(dec ? Number(dec[1]) : 0) + (f.endsWith(" %") ? " %" : "");
  }
  const groupOf = (key) => key === "change" ? "democracy" : (data.measures[key] || {}).group;
  // best first: the better end of the measure (higher first when it has none)
  const better = (key) => key === "change" ? "high" : (data.measures[key] || {}).better;
  const SHORT = { 3: "liberal dem.", 2: "electoral dem.", 1: "electoral aut.", 0: "closed aut." };   // the list's narrow column
  const reportsIn = (iso, y) => (data.reports[iso] || {})[String(y)] || 0;
  const docsUrl = (iso, y) => `/documents?country=${encodeURIComponent(iso)}&year=${y}&type=official`;

  // a small line of the chosen measure since 1990 on its own scale (the Liberal Democracy Index for the regime type
  // and its change), the chosen year marked
  function spark(c, y, w = 70, h = 16, key = "vdem_libdem") {
    const k = key === "change" || key === "vdem_regime" ? "vdem_libdem" : key;
    const arr = c.values[k] || [], n = arr.length, [lo, hi] = (data.measures[k] || {}).scale || [0, 1];
    const t = (v) => Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
    const pts = arr.map((v, i) => v == null ? null : `${(i / (n - 1) * w).toFixed(1)},${(h - 1 - t(v) * (h - 2)).toFixed(1)}`).filter(Boolean);
    const x = (idx(y) / (n - 1) * w).toFixed(1);
    return `<svg class="dm-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
      <polyline points="${pts.join(" ")}" fill="none" stroke="${LINE.spark}" stroke-width="1.3"/>
      <line x1="${x}" x2="${x}" y1="0" y2="${h}" stroke="${LINE.ink}" stroke-width="1" stroke-dasharray="2 2"/></svg>`;
  }

  // ── drawing ──
  function tooltip(f) {
    const c = data.countries[f.properties.iso], y = year();
    if (!c) return `<div class="tip-h"><b>${esc(f.properties.name)}</b></div><span class="muted">no rating in these datasets</span>`;
    const key = measure();
    const row = (k, label, by) => `<tr${k === key ? ' class="on"' : ""}><th>${label}</th><td>${esc(fmt(k, val(c, k, y)))}</td><td class="src">${by}</td></tr>`;
    const n = reportsIn(f.properties.iso, y), g = groupOf(key);
    const rows = g === "democracy"
      ? `${row("vdem_regime", "Regime type", "V-Dem")}${row("vdem_libdem", "Liberal Democracy Index", "V-Dem")}
         ${row("change", `LDI change since ${y - CHANGE_SPAN}`, "V-Dem")}
         ${row("fh_score", "Freedom in the World", "Freedom House")}${row("wgi_va", "Voice and Accountability", "World Bank")}`
      : Object.entries(data.measures).filter(([, m]) => m.group === g).map(([k, m]) => row(k, esc(m.name), esc(m.by))).join("");
    return `<div class="tip-h"><b>${esc(c.name)}</b><span class="muted">${y}</span></div>
      <table class="dm-tip">${rows}</table>
      <div class="tip-spark"><span class="muted">${esc(groupOf(key) === "democracy" ? "LDI" : data.measures[key].short)} ${data.years[0]}</span>${spark(c, y, 190, 26, key)}<span class="muted">${data.years.at(-1)}</span></div>
      <div class="tip-foot">${c.library
        ? `<span class="${n ? "" : "muted"}">${n} official report${n === 1 ? "" : "s"} from ${y} in the library</span>${n ? '<span class="hint">click to list them</span>' : ""}`
        : '<span class="muted">not a reporting state of the library</span>'}</div>`;
  }

  function style(f) {
    const c = data.countries[f.properties.iso], key = measure(), only = form.only.checked;
    const lib = c && c.library;
    return { fillColor: colour(key, val(c, key, year())), fillOpacity: only && !lib ? 0.12 : c ? 0.88 : 0.5,
             color: lib ? LINE.edge : LINE.line, weight: lib ? 1.1 : 0.5 };
  }

  function drawCountries() {
    if (layer) { layer.setStyle(style); return; }
    layer = L.geoJSON(geo, {
      style,
      onEachFeature: (f, l) => {
        byIso[f.properties.iso] = l;
        l.bindTooltip(() => tooltip(f), { sticky: true, className: "hq-tip country-tip" });
        l.on("click", () => {
          const c = data.countries[f.properties.iso];
          if (c && c.library && reportsIn(f.properties.iso, year())) window.location.href = docsUrl(f.properties.iso, year());
        });
        l.on("mouseover", () => l.setStyle({ weight: 2.4, color: LINE.hover }));
        l.on("mouseout", () => layer.resetStyle(l));
      },
    }).addTo(map);
  }

  function drawSources() {
    if (dots) { dots.remove(); dots = null; }
    if (!form.sources.checked) return;
    const max = Math.max(1, ...agencies.map((a) => a.n_docs));
    dots = L.layerGroup(agencies.filter((a) => a.lat != null).map((a) => {
      const tt = a.type === "think-tank" || a.type === "commercial";
      return L.circleMarker([a.lat, a.lon], {
        radius: 2.5 + 9 * Math.sqrt(a.n_docs / max), weight: 1.2, color: tt ? (CRED[a.credibility] || CRED.unassessed) : LINE.ink,
        fillColor: tt ? (CRED[a.credibility] || CRED.unassessed) : LINE.panel, fillOpacity: tt ? 0.55 : 0.75, dashArray: tt ? "2 2" : null,
      }).bindTooltip(`<div class="tip-h"><b>${esc(a.agency)}</b><span class="muted">${esc(a.country_name || "")}</span></div>
          ${a.name_en && a.name_en !== a.agency ? `<div class="tip-sub">${esc(a.name_en)}</div>` : ""}
          <div class="small" style="color:${tt ? CRED[a.credibility] || CRED.unassessed : LINE.muted}">${tt ? `${a.type === "commercial" ? "■ commercial analyst" : "◆ think tank"} · ${esc(a.credibility_label || "not assessed")}` : esc(a.type_name || "")}</div>
          <div class="tip-foot">${a.n_docs} report${a.n_docs === 1 ? "" : "s"} in the library${a.y0 ? ` · ${a.y0}–${a.y1}` : ""}
            <span class="hint">click for ${tt ? "its profile" : "its reports"}</span></div>`,
                     { className: "hq-tip country-tip", direction: "top", offset: [0, -6] })
        .on("click", () => { window.location.href = tt ? `/publisher/${a.id}` : `/documents?source=${a.id}`; });
    })).addTo(map);
  }

  function legend() {
    const key = measure(), y = year(), m = data.measures[key];
    let html;
    if (key === "vdem_regime") {
      const world = { 0: 0, 1: 0, 2: 0, 3: 0 }, lib = { 0: 0, 1: 0, 2: 0, 3: 0 };
      for (const c of Object.values(data.countries)) {
        const v = val(c, key, y);
        if (v == null) continue;
        world[Math.round(v)]++;
        if (c.library) lib[Math.round(v)]++;
      }
      html = `<table class="dm-reg"><tr><th></th><th class="n">world</th><th class="n">library states</th></tr>` +
        [3, 2, 1, 0].map((k) => `<tr><th><span class="rt-dot" style="background:${REGIME[k]}"></span>${esc(data.regimes[k])}</th>
          <td class="n">${world[k]}</td><td class="n">${lib[k]}</td></tr>`).join("") + "</table>";
    } else {
      const [lo, hi] = key === "change" ? [-CHANGE_MAX, CHANGE_MAX] : m.scale, b = better(key);
      const ramp = b ? (b === "low" ? [...RAMP].reverse() : RAMP) : SEQ;
      const ends = key === "change" ? ["decline " + lo, "+" + hi + " improvement"]
        : [fmt(key, lo) + (b === "high" ? " worse" : b === "low" ? " better" : ""), fmt(key, hi) + (b === "high" ? " better" : b === "low" ? " worse" : " (context, neither end is better)")];
      html = `<div class="dm-ramp">${ramp.map((c) => `<i style="background:${c}"></i>`).join("")}</div>
        <div class="dm-ramp-l"><span>${esc(ends[0])}</span><span>${esc(ends[1])}</span></div>`;
    }
    $("#legend").innerHTML = html + `<div class="small muted"><span class="rt-dot" style="background:${NODATA};outline:1px solid ${LINE.line}"></span>no rating · strong outline: the library's states</div>`;
    $("#year-label").textContent = y;
  }

  function list() {
    const key = measure(), y = year();
    const rows = Object.entries(data.countries).filter(([, c]) => c.library)
      .map(([iso, c]) => ({ iso, c, v: val(c, key, y), ldi: val(c, "vdem_libdem", y), ch: val(c, "change", y), n: reportsIn(iso, y) }))
      .sort(better(key) === "low" ? (a, b) => (a.v ?? 1e9) - (b.v ?? 1e9) || (b.ldi ?? -9) - (a.ldi ?? -9)
                                    : (a, b) => (b.v ?? -1e9) - (a.v ?? -1e9) || (b.ldi ?? -9) - (a.ldi ?? -9));
    $("#list-note").textContent = `${rows.length} · ${y}`;
    $("#list").innerHTML = rows.map((r) => `<li class="dm-row" data-iso="${r.iso}">
        <img src="/static/flags/${r.iso.toLowerCase()}.svg" alt="" width="18" height="13">
        <span class="dm-name">${esc(r.c.name)}</span>
        ${spark(r.c, y, 70, 16, key)}
        <span class="dm-v" style="--c:${colour(key, r.v)}" title="${esc(fmt(key, r.v))}"><i></i>${esc(key === "vdem_regime" && r.v != null ? SHORT[Math.round(r.v)] : fmt(key, r.v))}</span>
        <span class="dm-ch ${groupOf(key) !== "democracy" || r.ch == null ? "" : r.ch < -0.02 ? "down" : r.ch > 0.02 ? "up" : ""}" title="Liberal Democracy Index change since ${y - CHANGE_SPAN}">${groupOf(key) !== "democracy" || r.ch == null ? "" : r.ch < -0.02 ? "▼" : r.ch > 0.02 ? "▲" : "▬"}</span>
        ${r.n ? `<a class="dm-n" href="${docsUrl(r.iso, y)}" title="official reports from ${y}">${r.n}</a>` : '<span class="dm-n muted">0</span>'}
      </li>`).join("");
    for (const li of document.querySelectorAll(".dm-row")) {
      const l = byIso[li.dataset.iso];
      li.addEventListener("mouseenter", () => l && l.setStyle({ weight: 3, color: LINE.hover }));
      li.addEventListener("mouseleave", () => l && layer.resetStyle(l));
      li.querySelector(".dm-name").addEventListener("click", () => l && map.fitBounds(l.getBounds(), { maxZoom: 5 }));
    }
  }

  function sourcesNote() {
    const m = data.measures, k = measure() === "change" ? "vdem_libdem" : measure();
    $("#sources-note").innerHTML = `${esc(m[k].about)} Source: ${esc(m[k].citation || m[k].by)}
      (<a href="${esc(m[k].source)}" target="_blank" rel="noopener">data</a>, licence ${esc(m[k].license)}), retrieved ${esc(data.retrieved)}.
      Reports counted: official agencies of the state, by publication year. All states and sources:
      <a href="/ratings?group=${esc(groupOf(measure()))}">${esc(data.groups[groupOf(measure())] || "")} ratings</a>.`;
  }

  function redraw() {
    const page = new URL(window.location);
    page.search = new URLSearchParams({ measure: measure(), year: year(), sources: form.sources.checked ? "1" : "0",
                                        only: form.only.checked ? "1" : "0" }).toString();
    history.replaceState(null, "", page);
    drawCountries(); legend(); list(); sourcesNote();
  }

  $("#play").addEventListener("click", () => {
    if (playing) { clearInterval(playing); playing = null; $("#play").textContent = "▶"; return; }
    if (year() >= data.years[data.years.length - 1]) form.year.value = data.years[0];
    $("#play").textContent = "❚❚";
    playing = setInterval(() => {
      if (year() >= data.years[data.years.length - 1]) { clearInterval(playing); playing = null; $("#play").textContent = "▶"; return; }
      form.year.value = year() + 1; redraw();
    }, 700);
  });

  (async () => {
    [geo, data] = await Promise.all([fetch("/static/geo/countries.geojson").then((r) => r.json()),
                                     fetch("/api/ratings/map").then((r) => r.json())]);
    form.year.min = data.years[0];
    form.year.max = data.years[data.years.length - 1];
    if (!url.searchParams.get("year")) form.year.value = lastYear(measure());
    form.addEventListener("input", (e) => { if (e.target.name === "year") redraw(); });
    form.addEventListener("change", (e) => {
      if (e.target.name === "sources") drawSources();
      if (e.target.name === "measure" && !hasYear(measure(), year())) form.year.value = lastYear(measure());   // not an empty map
      redraw();
    });
    redraw();
    agencies = (await fetch("/api/map").then((r) => r.json())).agencies;
    drawSources();
  })();
})();
