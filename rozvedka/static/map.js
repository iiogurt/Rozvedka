/* Rozvedka world map: agency HQ pins, clustered, with countries shaded by report count. */
(function () {
  "use strict";

  const TYPE_COLORS = {
    "intelligence-civil": "#1f4e79", "intelligence-military": "#4f6b2a", "cyber": "#6a3d9a",
    "civil-protection": "#c05a12", "police-ct": "#a3202a", "eu-body": "#2456b8", "nato": "#004990", "other": "#5b6b7c",
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const PRECISION = { address: "exact building address", street: "street-level (house not matched)", city: "city only – exact address not published" };

  // maxZoom must be set on the map itself: without a tile layer Leaflet reports Infinity and
  // markercluster then loops forever building clusters for every zoom level (froze the offline view)
  const map = L.map("map", { worldCopyJump: true, minZoom: 2, maxZoom: 18 }).setView([50.5, 12], 4);
  map.createPane("countries"); map.getPane("countries").style.zIndex = 350;

  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const cluster = L.markerClusterGroup({
    showCoverageOnHover: false, maxClusterRadius: 40, spiderfyOnMaxZoom: true,
    // neutral bubbles: the default green/yellow/red would read as a rating
    iconCreateFunction: (c) => {
      const n = c.getChildCount(), size = n < 5 ? 30 : n < 15 ? 36 : 42;
      return L.divIcon({ html: `<span>${n}</span>`, className: "cluster", iconSize: [size, size] });
    },
  });
  map.addLayer(cluster);

  let agencies = [], markers = [], shading = null, coalitionNames = {}, countryStats = {};

  function pinIcon(a) {
    const color = TYPE_COLORS[a.type] || TYPE_COLORS.other;
    const hollow = a.hq_precision !== "address";
    return L.divIcon({
      className: "pin",
      html: `<span class="pin-dot${hollow ? " hollow" : ""}" style="--c:${color}"></span>`,
      iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -8],
    });
  }

  function popupHtml(a) {
    const logo = a.logo ? `<img class="pop-logo" src="${esc(a.logo)}" alt="">` : "";
    const local = a.name_local && a.name_local !== a.name_en ? `<div class="pop-local">${esc(a.name_local)}</div>` : "";
    const years = a.y0 ? ` · ${a.y0}–${a.y1}` : "";
    const home = a.homepage ? `<a href="${esc(a.homepage)}" target="_blank" rel="noopener">⌂ home page</a>` : "";
    return `<div class="pop">
      <div class="pop-head">${logo}<div><img class="pop-flag" src="${esc(a.flag)}" alt=""> <b>${esc(a.agency)}</b>
        <div class="pop-en">${esc(a.name_en)}</div>${local}</div></div>
      <div class="pop-type" style="--c:${TYPE_COLORS[a.type] || "#555"}">${esc(a.type_name)} · ${esc(a.country_name)}</div>
      <div class="pop-coal">${a.coalitions.map((k) => `<span class="ctag ctag-${esc(k)}">${esc((coalitionNames[k] || {}).short || k)}</span>`).join(" ")}</div>
      <p class="pop-desc">${esc(a.description)}</p>
      <div class="pop-addr"><b>HQ:</b> ${esc(a.hq_address)}<br><span class="muted">${esc(PRECISION[a.hq_precision] || "")}</span></div>
      <div class="pop-links"><a href="/?source=${a.id}"><b>${a.n_docs}</b> documents${years}</a>
        <a href="/sources#s-${a.id}">profile</a>${home}</div></div>`;
  }

  function checkedTypes() {
    return new Set([...document.querySelectorAll('input[name=type]:checked')].map((i) => i.value));
  }

  function render() {
    const types = checkedTypes();
    const q = document.getElementById("find").value.trim().toLowerCase();
    cluster.clearLayers();
    const list = document.getElementById("list");
    list.innerHTML = "";
    const coal = document.getElementById("coalition").value;
    const visible = markers.filter(({ a }) => types.has(a.type) && (!coal || a.coalitions.includes(coal)) &&
      (!q || [a.agency, a.name_en, a.name_local, a.country_name].join(" ").toLowerCase().includes(q)));
    cluster.addLayers(visible.map((v) => v.m));
    visible.sort((x, y) => (x.a.country_name + x.a.agency).localeCompare(y.a.country_name + y.a.agency));
    for (const { a, m } of visible) {
      const li = document.createElement("li");
      li.innerHTML = `<img src="${esc(a.flag)}" alt="" width="18" height="13"> <b>${esc(a.agency)}</b>
        <span class="muted">${esc(a.name_en)}</span>`;
      li.addEventListener("click", () => cluster.zoomToShowLayer(m, () => m.openPopup()));
      list.appendChild(li);
    }
  }

  function shadeColor(n, max) {
    if (!n) return "#e7e5de";
    const t = Math.sqrt(n / max);               // sqrt keeps small publishers visible next to big ones
    const lightness = 88 - t * 52;
    return `hsl(210, 45%, ${lightness}%)`;
  }

  async function loadCountries(stats) {
    const geo = await fetch("/static/geo/countries.geojson").then((r) => r.json());
    const max = Math.max(1, ...Object.values(stats).map((c) => c.docs));
    shading = L.geoJSON(geo, {
      pane: "countries",
      style: (f) => {
        const coal = document.getElementById("coalition").value;
        const c = stats[f.properties.iso] && (!coal || stats[f.properties.iso].coalitions.includes(coal))
          ? stats[f.properties.iso] : null;
        return c ? { fillColor: shadeColor(c.docs, max), fillOpacity: 0.55, color: "#6b7f95", weight: 1 }
                 : { fillOpacity: 0, color: "#b9b7ae", weight: 0.4 };   // no sources: outline only
      },
      onEachFeature: (f, layer) => {
        const c = stats[f.properties.iso];
        if (!c) return;
        const tags = c.coalitions.map((k) => esc((coalitionNames[k] || {}).short || k)).join(" · ");
        layer.bindTooltip(`<b>${esc(c.name)}</b><br>${c.agencies} agencies · ${c.docs} documents` +
                          (tags ? `<br><span class="muted">${tags}</span>` : ""), { sticky: true });
        layer.on("click", () => { window.location.href = `/?country=${encodeURIComponent(f.properties.iso)}`; });
        layer.on("mouseover", () => layer.setStyle({ weight: 2.5, color: "#1f4e79" }));
        layer.on("mouseout", () => { shading.resetStyle(layer); fadeShading(); });
      },
    }).addTo(map);
    fadeShading();
  }

  // country shading helps at continent scale but hides streets when zoomed in
  function fadeShading() {
    if (!shading) return;
    const z = map.getZoom(), k = z <= 5 ? 1 : z >= 8 ? 0.08 : 1 - (z - 5) / 3.3;
    shading.eachLayer((l) => { if (l.options.fillOpacity) l.setStyle({ fillOpacity: 0.55 * k }); });
  }
  map.on("zoomend", fadeShading);

  const initialCoalition = new URLSearchParams(window.location.search).get("coalition");
  if (initialCoalition && document.querySelector(`#coalition option[value="${CSS.escape(initialCoalition)}"]`)) {
    document.getElementById("coalition").value = initialCoalition;
  }

  if (new URLSearchParams(window.location.search).get("tiles") === "0") {   // e.g. offline use
    map.removeLayer(tiles);
    document.getElementById("tiles").checked = false;
  }

  fetch("/api/map").then((r) => r.json()).then(async (data) => {
    agencies = data.agencies;
    coalitionNames = data.coalitions;
    countryStats = data.countries;
    markers = agencies.map((a) => {
      const m = L.marker([a.lat, a.lon], { icon: pinIcon(a), title: `${a.agency} – ${a.name_en}`, keyboard: true });
      m.bindPopup(popupHtml(a), { maxWidth: 340, minWidth: 260 });
      return { a, m };
    });
    for (const el of document.querySelectorAll(".cnt")) {
      el.textContent = `(${agencies.filter((a) => a.type === el.dataset.type).length})`;
    }
    render();
    if (!window.location.hash) map.fitBounds(L.latLngBounds(markers.map(({ m }) => m.getLatLng())), { padding: [30, 30] });
    focusFromHash();
    try { await loadCountries(data.countries); } catch (e) { console.warn("country shapes unavailable", e); }
  });

  // /map#s-<source id> zooms to that agency and opens its popup (linked from the Sources page)
  function focusFromHash() {
    const m = /^#s-(\d+)$/.exec(window.location.hash);
    if (!m) return;
    const hit = markers.find(({ a }) => String(a.id) === m[1]);
    if (hit) cluster.zoomToShowLayer(hit.m, () => { map.setView(hit.m.getLatLng(), Math.max(map.getZoom(), 12)); hit.m.openPopup(); });
  }
  window.addEventListener("hashchange", focusFromHash);

  const VIEWS = { world: [[-47, -130], [66, 178]], europe: [[34, -12], [71, 35]], americas: [[24, -128], [60, -52]],
                  asia: [[-47, 110], [46, 180]] };
  document.querySelectorAll("[data-view]").forEach((b) =>
    b.addEventListener("click", () => map.fitBounds(VIEWS[b.dataset.view], { padding: [10, 10] })));

  document.querySelectorAll("input[name=type]").forEach((i) => i.addEventListener("change", render));
  document.getElementById("find").addEventListener("input", render);
  document.getElementById("coalition").addEventListener("change", () => {
    render();
    if (shading) { shading.setStyle(shading.options.style); fadeShading(); }
  });
  document.getElementById("shade").addEventListener("change", (e) => {
    if (!shading) return;
    e.target.checked ? shading.addTo(map) : map.removeLayer(shading);
  });
  document.getElementById("tiles").addEventListener("change", (e) => {
    e.target.checked ? tiles.addTo(map) : map.removeLayer(tiles);
  });
})();
