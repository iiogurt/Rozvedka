/* Who reports on whom: countries shaded by the share of reports that name a country. Every country opens its documents. */
(function () {
  "use strict";
  // hover cards fully opaque while open; Leaflet sets 0 when one closes, so only the card under the pointer shows
  L.Tooltip.mergeOptions({ opacity: 1 });
  const $ = (s) => document.querySelector(s);
  const form = $("#scope");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v) => (v == null ? "–" : (v * 100 >= 10 ? (v * 100).toFixed(0) : (v * 100).toFixed(1)) + "%");
  // sequential blue for a dark surface: near zero recedes toward the background
  const RAMP = ["#1b2a3d", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"];
  const NODATA = "#161b22";
  const FEW = 10;     // fewer reports than this: a share of 4 out of 4 says little – drawn grey, off the colour scale
  const THIN = "#4a515b";

  const url = new URL(window.location);
  for (const el of form.elements) {
    const v = url.searchParams.get(el.name);
    if (v == null) continue;
    if (el.type === "radio") el.checked = el.value === v; else el.value = v;
  }
  const mode = () => form.querySelector("input[name=mode]:checked").value;

  const map = L.map("map", { worldCopyJump: true, maxZoom: 8, minZoom: 1, zoomSnap: 0.5 }).setView([30, 10], 2);
  map.attributionControl.addAttribution('Country outlines: <a href="https://www.naturalearthdata.com/">Natural Earth</a>');
  let geo = null, layer = null, data = null, max = 0.05;

  function colour(v) {
    if (v == null) return NODATA;
    const i = Math.min(RAMP.length - 1, Math.floor((v / max) * (RAMP.length - 1) + 0.0001));
    return RAMP[Math.max(0, i)];
  }

  function draw() {
    const rows = Object.fromEntries(data.rows.map((r) => [r.iso, r]));
    max = Math.max(0.05, ...data.rows.filter((r) => !r.own && r.of >= FEW).map((r) => r.share || 0));
    data.rows.sort((a, b) => (a.of < FEW) - (b.of < FEW) || (b.share || 0) - (a.share || 0));
    if (layer) layer.remove();
    layer = L.geoJSON(geo, {
      style: (f) => {
        const r = rows[f.properties.iso];
        return { color: "#30363d", weight: 0.6, fillOpacity: r ? 0.9 : 0.6,
                 fillColor: r ? (r.of < FEW ? THIN : colour(r.share)) : NODATA };
      },
      onEachFeature: (f, l) => {
        const r = rows[f.properties.iso];
        l.bindTooltip(() => r
          ? `<b>${esc(r.name)}</b><br>${r.docs} of ${r.of} reports · <b>${pct(r.share)}</b>${r.of < FEW ? "<br><i>few reports – read with care</i>" : ""}${r.own ? "<br><i>member of the selection</i>" : ""}<br><span class="muted">click for the reports</span>`
          : `<b>${esc(f.properties.name)}</b><br><span class="muted">${mode() === "about" ? "no reports from here in the library" : "not named"}</span>`,
          { sticky: true, className: "hq-tip country-tip" });
        if (r) l.on("click", () => { window.location.href = r.link; });
        l.on("mouseover", () => l.setStyle({ weight: 2, color: "#9fd0ff" }));
        l.on("mouseout", () => layer.resetStyle(l));
      },
    }).addTo(map);
    $("#maxshare").textContent = pct(max);
    $("#how").textContent = data.how || "";
    $("#list").innerHTML = data.rows.slice(0, 120).map((r) => `<li class="ml-row">
        <span class="ml-name">${r.actor ? `<a href="${esc(r.actor)}" title="Actor page">${esc(r.name)}</a>` : esc(r.name)}${r.own ? ' <span class="muted small">(member)</span>' : ""}${r.of < FEW ? ` <span class="muted small" title="fewer than ${FEW} reports">(${r.of} reports)</span>` : ""}</span>
        <span class="bar"><i style="width:${Math.min(100, ((r.share || 0) / max) * 100).toFixed(1)}%;background:${r.of < FEW ? THIN : colour(r.share)}"></i></span>
        <a class="ml-n" href="${esc(r.link)}" title="${r.docs} of ${r.of} reports">${pct(r.share)}</a></li>`).join("")
      || '<li class="muted">Nothing in this selection.</li>';
  }

  async function load() {
    const m = mode();
    $("#about-pick").hidden = m !== "about";
    $("#from-pick").hidden = m !== "from";
    const q = new URLSearchParams({ mode: m, target: m === "about" ? form.about.value : form.from.value });
    for (const k of ["year_from", "year_to", "type"]) if (form[k].value) q.set(k, form[k].value);
    const page = new URL(window.location);
    page.search = new URLSearchParams({ mode: m, [m]: q.get("target"),
      ...Object.fromEntries([...q].filter(([k]) => !["mode", "target"].includes(k))) }).toString();
    history.replaceState(null, "", page);
    $("#permalink").href = page.toString();
    $("#csv").href = `/api/mentions?${q}&format=csv`;
    data = await (await fetch(`/api/mentions?${q}`)).json();
    if (!form.about.options.length) {
      form.about.innerHTML = data.countries.map((c) => `<option value="${esc(c.key)}">${esc(c.label)}</option>`).join("");
      form.about.value = url.searchParams.get("about") || (data.countries.find((c) => c.iso === "RU") || {}).key || "";
      if (m === "about" && form.about.value !== q.get("target")) return load();
    }
    draw();
  }

  (async () => {
    geo = await fetch("/static/geo/countries.geojson").then((r) => r.json());
    form.addEventListener("change", load);
    load();
  })();
})();
