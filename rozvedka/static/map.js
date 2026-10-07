/* Rozvedka world map (dark): agency HQ pins with hover cards, clusters, countries shaded by report count. */
(function () {
  "use strict";

  // agency-type colours, tuned to stay readable on a dark basemap
  const TYPE_COLORS = {
    "intelligence-civil": "#5aa9ff", "intelligence-military": "#9ccc65", "cyber": "#c792ea",
    "civil-protection": "#ffab40", "police-ct": "#ff6b6b", "eu-body": "#82b1ff", "nato": "#4dd0e1", "other": "#b0bec5",
    "think-tank": "#f0e442",   // independent publishers: also a diamond instead of a dot, so shape tells them apart too
  };
  // a think tank's diamond takes the colour of its credibility rating (rozvedka/publishers.py)
  const CREDIBILITY = { transparent: "#2ec4a0", partial: "#f0e442", concerns: "#e69f00", redflag: "#ff7a3d", unassessed: "#9aa1ab" };
  const PRECISION = { address: "exact building address", street: "street-level (house not matched)",
                      city: "city only – exact address not published" };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const firstSentence = (s, max = 170) => {
    const t = String(s || ""), cut = t.indexOf(". ");
    const one = cut > 40 && cut < max ? t.slice(0, cut + 1) : t;
    return one.length > max ? one.slice(0, max - 1).trimEnd() + "…" : one;
  };
  const params = new URLSearchParams(window.location.search);

  // maxZoom must be set on the map itself: without a tile layer Leaflet reports Infinity and
  // markercluster then loops forever building clusters for every zoom level (froze the offline view)
  const map = L.map("map", { worldCopyJump: true, minZoom: 2, maxZoom: 18 }).setView([35, 10], 2);
  map.createPane("countries"); map.getPane("countries").style.zIndex = 350;

  // standard OpenStreetMap tiles, darkened in the browser by a CSS filter (.dark-tiles) – no API key needed
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, className: "dark-tiles",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // ── clusters: neutral bubbles, hover lists what is inside ──
  const cluster = L.markerClusterGroup({
    showCoverageOnHover: false, maxClusterRadius: 40, spiderfyOnMaxZoom: true,
    iconCreateFunction: (c) => {
      const n = c.getChildCount(), size = n < 5 ? 30 : n < 15 ? 36 : 42;
      return L.divIcon({ html: `<span>${n}</span>`, className: "cluster", iconSize: [size, size] });
    },
  });
  map.addLayer(cluster);
  cluster.on("clustermouseover", (e) => {
    const inside = e.layer.getAllChildMarkers().map((m) => m.options.agency)
      .sort((a, b) => (a.country_name + a.agency).localeCompare(b.country_name + b.agency));
    const rows = inside.slice(0, 10).map((a) =>
      `<li><img src="${esc(a.flag)}" alt=""><span class="dot solid" style="--c:${TYPE_COLORS[a.type] || "#aaa"}"></span>
       <b title="${esc(a.name_en)}">${esc(a.agency)}</b><span class="muted">${esc(a.country_name)}</span></li>`).join("");
    const more = inside.length > 10 ? `<li class="muted">+ ${inside.length - 10} more – click to zoom in</li>` : "";
    e.layer.bindTooltip(`<div class="cl-card"><div class="cl-h">${inside.length} agencies here</div><ul>${rows}${more}</ul></div>`,
      { direction: "top", offset: [0, -14], className: "hq-tip", opacity: 1 }).openTooltip();
  });
  cluster.on("clustermouseout", (e) => e.layer.unbindTooltip());

  let markers = [], shading = null, coalitionNames = {}, countryStats = {}, ratingsData = null;
  const REGIME = { 3: "#0072b2", 2: "#56b4e9", 1: "#e69f00", 0: "#d55e00" };
  // the state's regime type in the latest rated year (V-Dem, /api/ratings/map), for shading and the agency cards
  function regimeOf(iso) {
    const c = ratingsData && ratingsData.countries[iso];
    const arr = c && c.values.vdem_regime;
    if (!arr) return null;
    for (let i = arr.length - 1; i >= 0; i--) if (arr[i] != null) return { v: Math.round(arr[i]), year: ratingsData.years[i] };
    return null;
  }
  const shadeMode = () => document.getElementById("shade").value;

  function pinIcon(a) {
    const hollow = a.hq_precision !== "address";
    return L.divIcon({
      className: "pin",
      html: `<span class="pin-dot${hollow ? " hollow" : ""}${a.type === "think-tank" ? " diamond" : ""}" style="--c:${(a.type === "think-tank" && CREDIBILITY[a.credibility]) || TYPE_COLORS[a.type] || TYPE_COLORS.other}"></span>`,
      iconSize: [18, 18], iconAnchor: [9, 9], popupAnchor: [0, -8], tooltipAnchor: [0, -10],
    });
  }

  const coalitionChips = (a) => a.coalitions.map((k) =>
    `<span class="ctag ctag-${esc(k)}">${esc((coalitionNames[k] || {}).short || k)}</span>`).join("");
  const years = (a) => (!a.y0 ? "" : a.y0 === a.y1 ? ` · ${a.y0}` : ` · ${a.y0}–${a.y1}`);

  // compact card shown on hover
  function hoverCard(a) {
    const logo = a.logo ? `<img class="hc-logo" src="${esc(a.logo)}" alt="">`
                        : `<span class="hc-logo hc-initials">${esc(a.agency.slice(0, 4))}</span>`;
    const local = a.name_local && a.name_local !== a.name_en ? `<div class="hc-local">${esc(a.name_local)}</div>` : "";
    return `<div class="hc">
      <div class="hc-head">${logo}<div class="hc-names">
        <div class="hc-acr"><img class="hc-flag" src="${esc(a.flag)}" alt=""> ${esc(a.agency)}</div>
        <div class="hc-en">${esc(a.name_en)}</div>${local}</div></div>
      <div class="hc-type" style="--c:${TYPE_COLORS[a.type] || "#aaa"}"><span class="dot solid"></span>${esc(a.type_name)} · ${esc(a.country_name)}</div>
      ${(() => { const r = regimeOf(a.country); return r ? `<div class="hc-regime"><span class="rt-dot" style="background:${REGIME[r.v]}"></span>${esc(ratingsData.regimes[r.v])} <span class="muted">(V-Dem ${r.year})</span></div>` : ""; })()}
      ${a.type === "think-tank" ? `<div class="pub-note">◆ Independent think tank – not run by a state · credibility: ${esc(a.credibility_label || "not assessed")}</div>` : ""}
      ${a.coalitions.length ? `<div class="hc-coal">${coalitionChips(a)}</div>` : ""}
      <p class="hc-desc">${esc(firstSentence(a.description))}</p>
      <div class="hc-foot"><span><b>${a.n_docs}</b> documents${years(a)}</span>
        <span class="hc-prec">${a.hq_precision === "address" ? "● exact HQ" : "○ approximate HQ"}</span></div>
      <div class="hc-hint">Click for details and links</div></div>`;
  }

  // full card on click
  function popupHtml(a) {
    const logo = a.logo ? `<img class="pop-logo" src="${esc(a.logo)}" alt="">` : "";
    const local = a.name_local && a.name_local !== a.name_en ? `<div class="pop-local">${esc(a.name_local)}</div>` : "";
    const home = a.homepage ? `<a href="${esc(a.homepage)}" target="_blank" rel="noopener">⌂ home page</a>` : "";
    return `<div class="pop">
      <div class="pop-head">${logo}<div><img class="pop-flag" src="${esc(a.flag)}" alt=""> <b>${esc(a.agency)}</b>
        <div class="pop-en">${esc(a.name_en)}</div>${local}</div></div>
      <div class="pop-type" style="--c:${TYPE_COLORS[a.type] || "#aaa"}">${esc(a.type_name)} · ${esc(a.country_name)}</div>
      ${a.coalitions.length ? `<div class="pop-coal">${coalitionChips(a)}</div>` : ""}
      <p class="pop-desc">${esc(a.description)}</p>
      <div class="pop-addr"><b>HQ:</b> ${esc(a.hq_address)}<br><span class="muted">${esc(PRECISION[a.hq_precision] || "")}</span></div>
      <div class="pop-links"><a href="/documents?source=${a.id}"><b>${a.n_docs}</b> documents${years(a)}</a>
        <a href="/sources#s-${a.id}">profile</a>${home}</div></div>`;
  }

  function checkedTypes() {
    return new Set([...document.querySelectorAll("input[name=type]:checked")].map((i) => i.value));
  }

  function render() {
    const types = checkedTypes();
    const coal = document.getElementById("coalition").value;
    const q = document.getElementById("find").value.trim().toLowerCase();
    const visible = markers.filter(({ a }) => types.has(a.type) && (!coal || a.coalitions.includes(coal)) &&
      (!q || [a.agency, a.name_en, a.name_local, a.country_name].join(" ").toLowerCase().includes(q)));
    cluster.clearLayers();
    cluster.addLayers(visible.map((v) => v.m));
    const list = document.getElementById("list");
    list.innerHTML = "";
    visible.sort((x, y) => (x.a.country_name + x.a.agency).localeCompare(y.a.country_name + y.a.agency));
    for (const { a, m } of visible) {
      const li = document.createElement("li");
      li.innerHTML = `<img src="${esc(a.flag)}" alt="" width="18" height="13"> <b>${esc(a.agency)}</b>
        <span class="muted">${esc(a.name_en)}</span>`;
      li.addEventListener("click", () => cluster.zoomToShowLayer(m, () => m.openPopup()));
      // hovering the list highlights the pin (when it is not hidden inside a cluster)
      li.addEventListener("mouseenter", () => m.getElement()?.classList.add("pin-hot"));
      li.addEventListener("mouseleave", () => m.getElement()?.classList.remove("pin-hot"));
      list.appendChild(li);
    }
  }

  // ── country shading: brighter = more reports ──
  function shadeColor(n, max) {
    const t = Math.sqrt(n / max);                 // sqrt keeps small publishers visible next to big ones
    return `hsl(205, 70%, ${24 + t * 34}%)`;
  }
  function countryStyle(f) {
    const coal = document.getElementById("coalition").value;
    if (shadeMode() === "regime") {             // every country by its regime type; the library's states outlined
      const r = regimeOf(f.properties.iso), st = countryStats[f.properties.iso];
      return r ? { fillColor: REGIME[r.v], fillOpacity: 0.5, color: st && st.docs ? "#d0d7de" : "#3a434e", weight: st && st.docs ? 1 : 0.4 }
               : { fillOpacity: 0, color: "#3a434e", weight: 0.4 };
    }
    const st = countryStats[f.properties.iso];
    const c = st && st.docs > 0 && (!coal || st.coalitions.includes(coal)) ? st : null;
    const max = Math.max(1, ...Object.values(countryStats).map((x) => x.docs));
    return c ? { fillColor: shadeColor(c.docs, max), fillOpacity: 0.5, color: "#6aa7d8", weight: 1 }
             : { fillOpacity: 0, color: "#3a434e", weight: 0.4 };   // no sources: outline only
  }
  function fadeShading() {       // shading helps at continent scale but hides streets when zoomed in
    if (!shading) return;
    const z = map.getZoom(), k = z <= 5 ? 1 : z >= 8 ? 0.1 : 1 - (z - 5) / 3.3;
    shading.eachLayer((l) => { if (l.options.fillOpacity) l.setStyle({ fillOpacity: 0.5 * k }); });
  }
  map.on("zoomend", fadeShading);

  async function loadCountries() {
    const geo = await fetch("/static/geo/countries.geojson").then((r) => r.json());
    shading = L.geoJSON(geo, {
      pane: "countries", style: countryStyle,
      onEachFeature: (f, layer) => {
        if (!countryStats[f.properties.iso] && !regimeOf(f.properties.iso)) return;
        layer.bindTooltip(() => {
          const c = countryStats[f.properties.iso] || { name: f.properties.name, agencies: 0, docs: 0, coalitions: [] };
          const tags = c.coalitions.map((k) => esc((coalitionNames[k] || {}).short || k)).join(" · ");
          const topicName = document.getElementById("topic").selectedOptions[0]?.text;
          const r = regimeOf(f.properties.iso);
          return `<b>${esc(c.name)}</b><br>${c.agencies} agencies · ${c.docs} documents` +
                 (document.getElementById("topic").value ? ` on <i>${esc(topicName)}</i>` : "") +
                 (r ? `<br><span class="rt-dot" style="background:${REGIME[r.v]}"></span>${esc(ratingsData.regimes[r.v])} (V-Dem ${r.year})` : "") +
                 (tags ? `<br><span class="muted">${tags}</span>` : "");
        }, { sticky: true, className: "hq-tip country-tip" });
        layer.on("click", () => {
          if (!countryStats[f.properties.iso]) return;
          const t = document.getElementById("topic").value;
          window.location.href = `/documents?country=${encodeURIComponent(f.properties.iso)}${t ? `&topic=${encodeURIComponent(t)}` : ""}`;
        });
        layer.on("mouseover", () => layer.setStyle({ weight: 2.5, color: "#9fd0ff" }));
        layer.on("mouseout", () => { shading.resetStyle(layer); fadeShading(); });
      },
    }).addTo(map);
    fadeShading();
  }

  // /map#s-<source id> zooms to that agency and opens its card (linked from the Sources page)
  function focusFromHash() {
    const m = /^#s-(\d+)$/.exec(window.location.hash);
    if (!m) return;
    const hit = markers.find(({ a }) => String(a.id) === m[1]);
    if (hit) cluster.zoomToShowLayer(hit.m, () => { map.setView(hit.m.getLatLng(), Math.max(map.getZoom(), 12)); hit.m.openPopup(); });
  }
  window.addEventListener("hashchange", focusFromHash);

  // ── controls ──
  const VIEWS = { world: [[-47, -130], [66, 178]], europe: [[34, -12], [71, 35]], americas: [[24, -128], [60, -52]],
                  asia: [[-47, 110], [46, 180]] };
  document.querySelectorAll("[data-view]").forEach((b) =>
    b.addEventListener("click", () => map.fitBounds(VIEWS[b.dataset.view], { padding: [10, 10] })));
  document.querySelectorAll("input[name=type]").forEach((i) => i.addEventListener("change", render));
  document.getElementById("find").addEventListener("input", render);
  document.getElementById("coalition").addEventListener("change", () => {
    render();
    if (shading) { shading.setStyle(countryStyle); fadeShading(); }
  });
  const shadeSel = document.getElementById("shade");
  if (["reports", "regime", ""].includes(params.get("shade"))) shadeSel.value = params.get("shade");
  shadeSel.addEventListener("change", (e) => {
    const url = new URL(window.location);
    e.target.value === "reports" ? url.searchParams.delete("shade") : url.searchParams.set("shade", e.target.value);
    history.replaceState(null, "", url);
    document.getElementById("legend-reports").hidden = e.target.value !== "reports";
    document.getElementById("legend-regime").hidden = e.target.value !== "regime";
    if (!shading) return;
    if (!e.target.value) { map.removeLayer(shading); return; }
    shading.addTo(map); shading.setStyle(countryStyle); fadeShading();
  });
  document.getElementById("tiles").addEventListener("change", (e) => {
    e.target.checked ? tiles.addTo(map) : map.removeLayer(tiles);
  });
  const initialCoalition = params.get("coalition");
  if (initialCoalition && document.querySelector(`#coalition option[value="${CSS.escape(initialCoalition)}"]`)) {
    document.getElementById("coalition").value = initialCoalition;
  }
  if (params.get("tiles") === "0") {            // e.g. offline use: country outlines only
    map.removeLayer(tiles);
    document.getElementById("tiles").checked = false;
  }

  // ── data ──
  let firstLoad = true;
  async function load(topic) {
    if (!ratingsData) ratingsData = await fetch("/api/ratings/map").then((r) => r.json()).catch(() => null);
    const data = await fetch(`/api/map${topic ? `?topic=${encodeURIComponent(topic)}` : ""}`).then((r) => r.json());
    coalitionNames = data.coalitions;
    countryStats = data.countries;
    const sel = document.getElementById("topic");
    if (sel.options.length === 1) {                       // fill the topic list once, grouped by category
      let group = null;
      for (const t of data.topic_list) {
        if (!group || group.label !== t.category) { group = document.createElement("optgroup"); group.label = t.category; sel.appendChild(group); }
        group.appendChild(new Option(t.name, t.key));
      }
      if (topic) sel.value = topic;
    }
    // with a topic, agencies without reports on it are hidden
    const agencies = topic ? data.agencies.filter((a) => a.n_docs > 0) : data.agencies;
    markers = agencies.map((a) => {
      const m = L.marker([a.lat, a.lon], { icon: pinIcon(a), keyboard: true, agency: a, riseOnHover: true,
                                           alt: `${a.agency} – ${a.name_en}` });
      // hover: compact agency card; click: full card with links (the hover card closes while the popup is open)
      m.bindTooltip(hoverCard(a), { direction: "top", offset: [0, -4], className: "hq-tip", opacity: 1 });
      m.bindPopup(popupHtml(a), { maxWidth: 340, minWidth: 270, className: "dark-popup" });
      m.on("popupopen", () => m.closeTooltip());
      return { a, m };
    });
    for (const el of document.querySelectorAll(".cnt")) {
      el.textContent = `(${data.agencies.filter((a) => a.type === el.dataset.type).length})`;
    }
    render();
    if (firstLoad) {
      if (!window.location.hash && markers.length) map.fitBounds(L.latLngBounds(markers.map(({ m }) => m.getLatLng())), { padding: [30, 30] });
      focusFromHash();
      try { await loadCountries(); } catch (e) { console.warn("country shapes unavailable", e); }
      if (shadeSel.value !== "reports") shadeSel.dispatchEvent(new Event("change"));
      firstLoad = false;
    } else if (shading) {
      shading.setStyle(countryStyle); fadeShading();
    }
  }
  const initialTopic = params.get("topic") || "";
  load(initialTopic);
  document.getElementById("topic").addEventListener("change", (e) => {
    const url = new URL(window.location);
    e.target.value ? url.searchParams.set("topic", e.target.value) : url.searchParams.delete("topic");
    history.replaceState(null, "", url);
    load(e.target.value);
  });
})();
