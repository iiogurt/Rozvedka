/* Democracy over time: every country coloured by a democracy measure for a chosen year (V-Dem, Freedom House,
   World Bank), the library's states listed with their course since 1990, and the library's sources on top.
   All years come in one request (/api/ratings/map); the slider and the play button only redraw. Every report count
   opens /documents?country=…&year=…&type=official. Colours: blue = more democratic, orange = more autocratic
   (Okabe–Ito, colour-blind safe), always with a label. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const form = $("#dm");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const REGIME = { 3: "#0072b2", 2: "#56b4e9", 1: "#e69f00", 0: "#d55e00" };
  const RAMP = ["#a63f00", "#d55e00", "#e69f00", "#bfb08a", "#8fc3e8", "#56b4e9", "#0072b2"];   // autocratic → democratic
  const NODATA = "#161b22";
  const CHANGE_SPAN = 10, CHANGE_MAX = 0.25;     // years compared; ±0.25 LDI saturates the colour
  const CRED = { transparent: "#2ec4a0", partial: "#f0e442", concerns: "#e69f00", redflag: "#ff7a3d", unassessed: "#9aa1ab" };

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
  function colour(key, v) {
    if (v == null) return NODATA;
    if (key === "vdem_regime") return REGIME[Math.round(v)];
    let t;
    if (key === "change") t = (Math.max(-CHANGE_MAX, Math.min(CHANGE_MAX, v)) + CHANGE_MAX) / (2 * CHANGE_MAX);
    else { const [lo, hi] = data.measures[key].scale; t = (v - lo) / (hi - lo); }
    return RAMP[Math.max(0, Math.min(RAMP.length - 1, Math.round(t * (RAMP.length - 1))))];
  }
  const fmt = (key, v) => v == null ? "–" : key === "vdem_regime" ? data.regimes[Math.round(v)]
    : key === "change" ? (v >= 0 ? "+" : "") + v.toFixed(2) : key === "fh_score" ? v.toFixed(0)
    : key === "wgi_va" ? (v >= 0 ? "+" : "") + v.toFixed(2) : v.toFixed(2);
  const SHORT = { 3: "liberal dem.", 2: "electoral dem.", 1: "electoral aut.", 0: "closed aut." };   // the list's narrow column
  const reportsIn = (iso, y) => (data.reports[iso] || {})[String(y)] || 0;
  const docsUrl = (iso, y) => `/documents?country=${encodeURIComponent(iso)}&year=${y}&type=official`;

  // a small line of the Liberal Democracy Index since 1990, the chosen year marked
  function spark(c, y) {
    const arr = c.values.vdem_libdem || [], w = 70, h = 16, n = arr.length;
    const pts = arr.map((v, i) => v == null ? null : `${(i / (n - 1) * w).toFixed(1)},${(h - 1 - v * (h - 2)).toFixed(1)}`).filter(Boolean);
    const x = (idx(y) / (n - 1) * w).toFixed(1);
    return `<svg class="dm-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
      <polyline points="${pts.join(" ")}" fill="none" stroke="#8fc3e8" stroke-width="1.3"/>
      <line x1="${x}" x2="${x}" y1="0" y2="${h}" stroke="#f0f0f0" stroke-width="1" stroke-dasharray="2 2"/></svg>`;
  }

  // ── drawing ──
  function tooltip(f) {
    const c = data.countries[f.properties.iso], y = year();
    if (!c) return `<b>${esc(f.properties.name)}</b><br><span class="muted">no rating</span>`;
    const row = (k, label) => `<tr><th>${label}</th><td>${esc(fmt(k, val(c, k, y)))}</td></tr>`;
    const n = reportsIn(f.properties.iso, y);
    return `<b>${esc(c.name)}</b> · ${y}<table class="dm-tip">
      ${row("vdem_regime", "regime")}${row("vdem_libdem", "V-Dem LDI")}${row("change", `LDI change since ${y - CHANGE_SPAN}`)}
      ${row("fh_score", "Freedom House")}${row("wgi_va", "World Bank VA")}</table>
      ${c.library ? `<span class="${n ? "" : "muted"}">${n} official report${n === 1 ? "" : "s"} from ${y} in the library${n ? " – click to list them" : ""}</span>`
                  : '<span class="muted">not a reporting state of the library</span>'}`;
  }

  function style(f) {
    const c = data.countries[f.properties.iso], key = measure(), only = form.only.checked;
    const lib = c && c.library;
    return { fillColor: colour(key, val(c, key, year())), fillOpacity: only && !lib ? 0.12 : c ? 0.88 : 0.5,
             color: lib ? "#d0d7de" : "#30363d", weight: lib ? 1.1 : 0.5 };
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
        l.on("mouseover", () => l.setStyle({ weight: 2.4, color: "#ffffff" }));
        l.on("mouseout", () => layer.resetStyle(l));
      },
    }).addTo(map);
  }

  function drawSources() {
    if (dots) { dots.remove(); dots = null; }
    if (!form.sources.checked) return;
    const max = Math.max(1, ...agencies.map((a) => a.n_docs));
    dots = L.layerGroup(agencies.filter((a) => a.lat != null).map((a) => {
      const tt = a.type === "think-tank";
      return L.circleMarker([a.lat, a.lon], {
        radius: 2.5 + 9 * Math.sqrt(a.n_docs / max), weight: 1.2, color: tt ? (CRED[a.credibility] || "#f0e442") : "#ffffff",
        fillColor: tt ? (CRED[a.credibility] || "#f0e442") : "#0d1117", fillOpacity: tt ? 0.55 : 0.75, dashArray: tt ? "2 2" : null,
      }).bindTooltip(`<b>${esc(a.agency)}</b>${tt ? " ◆ think tank" : ""}<br>${esc(a.name_en || "")}<br>${a.n_docs} reports in the library`,
                     { className: "hq-tip" })
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
      const [lo, hi] = key === "change" ? [-CHANGE_MAX, CHANGE_MAX] : m.scale;
      html = `<div class="dm-ramp">${RAMP.map((c) => `<i style="background:${c}"></i>`).join("")}</div>
        <div class="dm-ramp-l"><span>${key === "change" ? "decline " + lo : lo}</span><span>${key === "change" ? "+" + hi + " improvement" : hi}</span></div>`;
    }
    $("#legend").innerHTML = html + `<div class="small muted"><span class="rt-dot" style="background:${NODATA};outline:1px solid #444"></span>no rating · white outline: the library's states</div>`;
    $("#year-label").textContent = y;
  }

  function list() {
    const key = measure(), y = year();
    const rows = Object.entries(data.countries).filter(([, c]) => c.library)
      .map(([iso, c]) => ({ iso, c, v: val(c, key, y), ldi: val(c, "vdem_libdem", y), ch: val(c, "change", y), n: reportsIn(iso, y) }))
      .sort((a, b) => (b.v ?? -9) - (a.v ?? -9) || (b.ldi ?? -9) - (a.ldi ?? -9));
    $("#list-note").textContent = `${rows.length} · ${y}`;
    $("#list").innerHTML = rows.map((r) => `<li class="dm-row" data-iso="${r.iso}">
        <img src="/static/flags/${r.iso.toLowerCase()}.svg" alt="" width="18" height="13">
        <span class="dm-name">${esc(r.c.name)}</span>
        ${spark(r.c, y)}
        <span class="dm-v" style="--c:${colour(key, r.v)}" title="${esc(fmt(key, r.v))}"><i></i>${esc(key === "vdem_regime" && r.v != null ? SHORT[Math.round(r.v)] : fmt(key, r.v))}</span>
        <span class="dm-ch ${r.ch == null ? "" : r.ch < -0.02 ? "down" : r.ch > 0.02 ? "up" : ""}" title="Liberal Democracy Index change since ${y - CHANGE_SPAN}">${r.ch == null ? "" : r.ch < -0.02 ? "▼" : r.ch > 0.02 ? "▲" : "▬"}</span>
        ${r.n ? `<a class="dm-n" href="${docsUrl(r.iso, y)}" title="official reports from ${y}">${r.n}</a>` : '<span class="dm-n muted">0</span>'}
      </li>`).join("");
    for (const li of document.querySelectorAll(".dm-row")) {
      const l = byIso[li.dataset.iso];
      li.addEventListener("mouseenter", () => l && l.setStyle({ weight: 3, color: "#ffffff" }));
      li.addEventListener("mouseleave", () => l && layer.resetStyle(l));
      li.querySelector(".dm-name").addEventListener("click", () => l && map.fitBounds(l.getBounds(), { maxZoom: 5 }));
    }
  }

  function sourcesNote() {
    const m = data.measures, k = measure() === "change" ? "vdem_libdem" : measure();
    $("#sources-note").innerHTML = `${esc(m[k].about)} Source: ${esc(m[k].citation || m[k].by)}
      (<a href="${esc(m[k].source)}" target="_blank" rel="noopener">data</a>, licence ${esc(m[k].license)}), retrieved ${esc(data.retrieved)}.
      Reports counted: official agencies of the state, by publication year. All states and sources: <a href="/ratings">Democracy ratings</a>.`;
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
    if (!url.searchParams.get("year")) form.year.value = form.year.max;
    form.addEventListener("input", (e) => { if (e.target.name === "year") redraw(); });
    form.addEventListener("change", (e) => { if (e.target.name === "sources") drawSources(); redraw(); });
    redraw();
    agencies = (await fetch("/api/map").then((r) => r.json())).agencies;
    drawSources();
  })();
})();
