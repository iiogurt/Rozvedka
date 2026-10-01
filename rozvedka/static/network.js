/* Network: clusters of actors the reports name together, an association matrix and a details panel.
   Association = NPMI of two actors being named in the same passage; every number links to its passages or reports. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const form = $("#scope");
  const kindBox = $("#kinds");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const pct = (v) => Math.round(v * 100) + "%";
  const flag = (c) => `/static/flags/${String(c || "other").toLowerCase()}.svg`;
  // sequential blue: weak association recedes toward the surface in both modes
  const RAMP = { light: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
                 dark: ["#1b2a3d", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"] };

  // ── state in the URL ──
  const url = new URL(window.location);
  for (const el of form.elements) { const v = url.searchParams.get(el.name); if (v != null) el.value = v; }
  const kindsInUrl = url.searchParams.getAll("kind");
  if (kindsInUrl.length) kindBox.querySelectorAll("input").forEach((i) => { i.checked = kindsInUrl.includes(i.value); });
  function query() {
    const q = new URLSearchParams();
    for (const el of form.elements) if (el.name && el.value) q.set(el.name, el.value);
    const kinds = [...kindBox.querySelectorAll("input:checked")].map((i) => i.value);
    kinds.filter((k) => k !== "country").forEach((k) => q.append("kind", k));
    if (kinds.includes("country")) q.set("countries_too", "1");
    return q;
  }

  let data = null, byKey = {};
  const chart = echarts.init($("#matrix"), null, { renderer: "canvas" });
  window.addEventListener("resize", () => chart.resize());
  darkQuery.addEventListener("change", () => data && drawMatrix());

  // ── cluster cards ──
  function spark(years) {
    if (!years.length) return "";
    const y0 = years[0][0], y1 = years[years.length - 1][0], n = y1 - y0 + 1;
    const counts = Object.fromEntries(years), max = Math.max(...years.map((y) => y[1]));
    const w = 150, h = 26, bw = w / n;
    const bars = Array.from({ length: n }, (_, i) => {
      const c = counts[y0 + i] || 0, bh = c ? Math.max(2, (c / max) * h) : 0;
      return `<rect x="${(i * bw + 0.5).toFixed(1)}" y="${(h - bh).toFixed(1)}" width="${Math.max(1, bw - 1).toFixed(1)}" height="${bh.toFixed(1)}" rx="1"><title>${y0 + i}: ${c} reports</title></rect>`;
    }).join("");
    return `<span class="spark"><svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">${bars}</svg>
      <span class="spark-x"><span>${y0}</span><span>${y1}</span></span></span>`;
  }
  function bar(v, cls = "") { return `<span class="mbar ${cls}"><i style="width:${Math.min(100, v * 100).toFixed(0)}%"></i></span>`; }

  function drawClusters() {
    const c = data.clusters;
    const inClusters = c.reduce((n, x) => n + x.members.length, 0);
    $("#summary").innerHTML = `<b>${c.length}</b> clusters of <b>${inClusters}</b> actors in <b>${data.n_docs}</b> reports
      <span class="muted">· ${data.unclustered} of the ${data.actors.length} actors have no strong tie to the others · clusters sorted by size</span>`;
    $("#clusters").innerHTML = c.map((cl, i) => `<article class="cluster-card">
      <header><span class="cl-no">${i + 1}</span><h3>${esc(cl.name)}${cl.members.length > 3 ? ` <span class="muted">+${cl.members.length - 3}</span>` : ""}</h3></header>
      <p class="cl-meta"><a href="${esc(cl.docs_link)}"><b>${cl.docs}</b> reports</a> name two of them in one passage ·
        cohesion ${cl.cohesion.toFixed(2)}</p>
      <div class="cl-members">${cl.members.map((m) => `<a class="mchip" href="/actors/${esc(m.key)}" title="${esc(data.kinds[m.kind] || m.kind)} · named in ${m.docs} reports">
        <i class="kdot kind-${esc(m.kind)}"></i>${esc(m.label)} <span class="muted">${m.docs}</span></a>`).join("")}</div>
      <div class="cl-cols">
        <div><h4>Strongest ties</h4><ul class="cl-list">${cl.ties.map((t) => `<li><span class="cl-l" title="${esc(t.la)} – ${esc(t.lb)}">${esc(t.la)} – ${esc(t.lb)}</span>
          ${bar(t.npmi)}<a href="${esc(t.link)}" title="passages naming both">${t.docs}</a></li>`).join("")}</ul></div>
        <div><h4>Main topics of these reports</h4><ul class="cl-list">${cl.topics.map((t) => `<li><span class="cl-l" title="${esc(t.name)}">${esc(t.name)}</span>
          ${bar(t.share, "topic")}<a href="${esc(t.link)}" title="reports with this among their main topics">${t.docs}</a></li>`).join("") || '<li class="muted">–</li>'}</ul></div>
      </div>
      <footer><div>${spark(cl.years)}</div>
        <div class="cl-ag">${cl.agencies.map((a) => `<a href="${esc(a.link)}" title="${a.docs} of these reports"><img class="flag-sm" src="${flag(a.country)}" alt=""> ${esc(a.agency)} <span class="muted">${a.docs}</span></a>`).join("")}</div>
      </footer></article>`).join("") || '<p class="muted">No cluster in this selection – try “loose” clusters, fewer reports per tie, or a wider period.</p>';
  }

  // ── matrix ──
  function drawMatrix() {
    const ink = css("--ink"), muted = css("--muted"), line = css("--line"), panel = css("--panel"), chip = css("--chip");
    const ramp = RAMP[darkQuery.matches ? "dark" : "light"];
    const keys = data.actors.map((a) => a.key);
    const idx = Object.fromEntries(keys.map((k, i) => [k, i]));
    const strong = [], weak = [];
    for (const c of data.cells) {
      const i = idx[c.a], j = idx[c.b];
      if (i == null || j == null) continue;
      const target = c.docs >= data.min_pair ? strong : weak;
      const v = c.docs >= data.min_pair ? c.npmi : 0;
      target.push({ value: [i, j, v], c }, { value: [j, i, v], c });
    }
    const starts = new Set(data.actors.map((a, i) => (i === 0 || a.cluster !== data.actors[i - 1].cluster ? i : -1)));
    const n = keys.length, cell = n > 70 ? 11 : 13, left = 210, top = 180;
    const el = $("#matrix");
    el.style.width = left + n * cell + 20 + "px";
    el.style.height = top + n * cell + 10 + "px";
    chart.resize();
    const lab = (k) => { const a = byKey[k]; const t = a.label.length > 30 ? a.label.slice(0, 29) + "…" : a.label;
      return a.cluster != null ? `${t}  ${a.cluster + 1}` : t; };
    const axis = (pos) => ({
      type: "category", data: keys, position: pos, triggerEvent: true,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { color: ink, fontSize: pos === "top" ? 10 : 11, interval: 0, formatter: lab, ...(pos === "top" ? { rotate: 90 } : {}) },
      splitArea: { show: true, interval: (i) => starts.has(i + 1), areaStyle: { color: [panel, chip] } },
      splitLine: { show: true, interval: (i) => starts.has(i + 1), lineStyle: { color: line } },
    });
    chart.setOption({
      animation: false, textStyle: { fontFamily: "system-ui, sans-serif" },
      grid: { left, top, width: n * cell, height: n * cell },
      xAxis: axis("top"), yAxis: { ...axis("left"), inverse: true },
      tooltip: { backgroundColor: panel, borderColor: line, textStyle: { color: ink, fontSize: 12 },
        formatter: (p) => {
          if (!p.data || !p.data.c) return "";
          const c = p.data.c, a = byKey[c.a], b = byKey[c.b];
          return `<b>${esc(a.label)}</b> and <b>${esc(b.label)}</b><br>named together in ${c.docs} reports
            (${esc(a.label)}: ${a.docs}, ${esc(b.label)}: ${b.docs})<br>association ${c.npmi.toFixed(2)}${c.docs < data.min_pair ? " – below the tie threshold" : ""}<br><span style="color:${muted}">click for details</span>`;
        } },
      visualMap: { show: false, seriesIndex: 0, min: 0, max: 0.8, inRange: { color: ramp } },
      series: [
        { type: "heatmap", data: strong, itemStyle: { borderColor: panel, borderWidth: 1 }, emphasis: { itemStyle: { borderColor: ink, borderWidth: 1.5 } } },
        { type: "heatmap", data: weak, itemStyle: { color: line, borderColor: panel, borderWidth: 1 } },
      ],
    }, true);
  }

  // ── details panel ──
  function egoPanel(key) {
    const a = byKey[key];
    const mine = data.cells.filter((c) => c.a === key || c.b === key)
      .map((c) => ({ ...c, other: c.a === key ? c.b : c.a }));
    const row = (c) => `<li><a href="#" data-key="${esc(c.other)}" class="cl-l">${esc(byKey[c.other].label)}</a>
      ${bar(c.npmi)}<a href="${esc(c.link)}" title="passages naming both">${c.docs}</a></li>`;
    const strongest = mine.filter((c) => c.docs >= data.min_pair).sort((x, y) => y.npmi - x.npmi).slice(0, 12);
    const frequent = [...mine].sort((x, y) => y.docs - x.docs).slice(0, 12);
    $("#panel").innerHTML = `<h3><i class="kdot kind-${esc(a.kind)}"></i>${esc(a.label)}</h3>
      <p class="small">${esc(data.kinds[a.kind] || a.kind)} · named in <a href="${esc(a.docs_link)}">${a.docs} reports</a>
        ${a.cluster != null ? ` · cluster ${a.cluster + 1}` : ""} · <a href="${esc(a.link)}">actor page →</a></p>
      <h4>Most strongly associated</h4><ul class="cl-list">${strongest.map(row).join("") || '<li class="muted">no tie above the threshold</li>'}</ul>
      <h4>Named together most often</h4><ul class="cl-list">${frequent.map(row).join("") || '<li class="muted">–</li>'}</ul>
      <p class="muted small">Bar = association (NPMI, 0–1); number = reports naming both in one passage – opens them.</p>`;
  }
  function pairPanel(c) {
    const a = byKey[c.a], b = byKey[c.b];
    const expected = (a.docs * b.docs) / data.n_docs;
    $("#panel").innerHTML = `<h3>${esc(a.label)} <span class="muted">and</span> ${esc(b.label)}</h3>
      <table class="facts-t small"><tr><th>Named in one passage</th><td><a href="${esc(c.link)}"><b>${c.docs}</b> reports</a></td></tr>
      <tr><th>${esc(a.label)}</th><td><a href="${esc(a.docs_link)}">${a.docs} reports</a></td></tr>
      <tr><th>${esc(b.label)}</th><td><a href="${esc(b.docs_link)}">${b.docs} reports</a></td></tr>
      <tr><th>Expected by chance</th><td>${expected.toFixed(1)} reports (of ${data.n_docs})</td></tr>
      <tr><th>Association</th><td>${c.npmi.toFixed(2)}${c.docs < data.min_pair ? " (below the tie threshold)" : ""}</td></tr></table>
      <p class="small"><a href="${esc(c.link)}">Read the passages →</a></p>
      <p class="small"><a href="#" data-key="${esc(c.a)}">${esc(a.label)}'s ties</a> · <a href="#" data-key="${esc(c.b)}">${esc(b.label)}'s ties</a></p>`;
  }
  $("#panel").addEventListener("click", (e) => {
    const k = e.target.closest("[data-key]");
    if (k) { e.preventDefault(); egoPanel(k.dataset.key); }
  });
  chart.on("click", (p) => {
    if (p.componentType === "xAxis" || p.componentType === "yAxis") egoPanel(p.value);
    else if (p.data && p.data.c) pairPanel(p.data.c);
  });

  function drawProvenance() {
    const p = data.provenance;
    $("#prov").innerHTML = `<p>${esc(p.how)}</p><ul class="prov-list">
      <li><b>Actors</b> come from the actor index (Wikidata, MITRE ATT&amp;CK, sources/actors.yaml; retrieved ${esc(p.gazetteer || "–")})
        and are found by name – see <a href="/actors">Actors</a> and <a href="/actors/names">the names used</a>.</li>
      <li><b>Main topics</b> of a cluster's reports: the 3 topics with the highest keyword score in each report.</li>
      <li><b>Cohesion</b>: average association between the members of a cluster.</li>
      <li class="muted">Computed ${esc(p.generated)} from the local database.</li></ul>`;
  }

  async function load() {
    const q = query();
    const page = new URL(window.location); page.search = q.toString();
    history.replaceState(null, "", page); $("#permalink").href = page.toString();
    document.body.classList.add("loading");
    data = await (await fetch(`/api/network?${q}`)).json();
    document.body.classList.remove("loading");
    byKey = Object.fromEntries(data.actors.map((a) => [a.key, a]));
    drawClusters(); drawMatrix(); drawProvenance();
    if (data.actors.length) egoPanel(data.actors[0].key);
  }
  form.addEventListener("change", load);
  kindBox.addEventListener("change", load);
  load();
})();
