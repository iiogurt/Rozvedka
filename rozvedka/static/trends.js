/* Trends pages: topic shares over time, term trends, and the agency × topic matrix.
   Every mark links to the Documents page filtered to exactly the documents it counts (the API sends the links). */
(function () {
  "use strict";
  const VIEW = window.TREND_VIEW;
  const NAMES = window.TOPIC_NAMES;
  const $ = (s) => document.querySelector(s);
  const form = $("#scope");
  const url = new URL(window.location);

  // Categorical palette (validated light/dark, see dataviz reference), assigned to series by stable slot.
  const PALETTE = {
    light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
  };
  // Sequential blue for the matrix: near zero recedes toward the surface in both modes.
  const SEQ = {
    light: ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    dark: ["#1b2a3d", "#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"],
  };
  const darkQuery = window.rzDark;
  const mode = () => (darkQuery.matches ? "dark" : "light");
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const ink = () => ({ text: css("--ink"), muted: css("--muted"), line: css("--line"), panel: css("--panel") });

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (v) => (v == null ? "–" : (v * 100 >= 10 ? (v * 100).toFixed(0) : (v * 100).toFixed(1)) + "%");

  // ── state in the URL, so every view has a permalink ──
  const MULTI = VIEW === "topics" ? "topic" : "term";
  const DEFAULTS = {
    topic: ["russia", "hybrid-threats", "drones-and-new-warfare", "right-wing-extremism"],
    term: ['drone OR Drohne OR dron', 'sabotage', 'disinformation OR Desinformation OR dezinformace OR désinformation',
           '"artificial intelligence" OR "künstliche Intelligenz" OR "umělá inteligence"'],
  };
  let items = url.searchParams.getAll(MULTI);
  if (!items.length && VIEW !== "matrix") items = DEFAULTS[MULTI].slice();
  const slots = new Map();
  function assignSlots() {
    for (const k of [...slots.keys()]) if (!items.includes(k)) slots.delete(k);
    for (const k of items) {
      if (slots.has(k)) continue;
      const used = new Set(slots.values());
      let s = 0; while (used.has(s)) s++;
      slots.set(k, s);
    }
  }
  assignSlots();

  for (const el of form.elements) {
    const v = url.searchParams.get(el.name);
    if (v == null) continue;
    if (el.type === "radio") el.checked = el.value === v;
    else if (el.type === "checkbox") el.checked = v !== "0";
    else el.value = v;
  }
  if (VIEW === "matrix" && !url.searchParams.get("year_to")) {
    const now = new Date().getFullYear();
    form.year_to.value = String(now - 1);
    form.year_from.value = String(now - 3);
  }
  const val = (name) => (form.elements[name] ? (form.elements[name].value ?? "") : "");
  const radio = (name) => (form.querySelector(`input[name=${name}]:checked`) || {}).value || "";

  function query(forApi) {
    const q = new URLSearchParams();
    for (const k of ["country", "coalition", "type", "year_from", "year_to"]) if (val(k)) q.set(k, val(k));
    if (VIEW === "matrix") q.set("by", radio("by"));
    else {
      items.forEach((i) => q.append(MULTI, i));
      if (!forApi) {
        if (radio("measure") !== "docs") q.set("measure", radio("measure"));
        if (val("since")) q.set("since", val("since"));
        if (!form.events.checked) q.set("events", "0");
      }
    }
    return q;
  }
  function syncUrl() {
    const page = new URL(window.location);
    page.search = query(false).toString();
    history.replaceState(null, "", page);
    $("#permalink").href = page.toString();
    const api = VIEW === "topics" ? "topics" : VIEW === "terms" ? "terms" : "matrix";
    $("#csv").href = `/api/trends/${api}?${query(true)}&format=csv`;
  }

  // ── charts ──
  const chart = echarts.init($("#chart"), null, { renderer: "svg" });
  const den = $("#chart-den") ? echarts.init($("#chart-den"), null, { renderer: "svg" }) : null;
  let data = null;
  [chart, den].forEach((c) => c && c.on("click", (p) => { if (p.data && p.data.link) window.location.href = p.data.link; }));
  window.addEventListener("resize", () => { chart.resize(); den && den.resize(); });
  darkQuery.addEventListener("change", () => data && render());

  function axisCommon(c) {
    return {
      axisLine: { lineStyle: { color: c.line } }, axisTick: { show: false },
      axisLabel: { color: c.muted, fontSize: 11 }, splitLine: { lineStyle: { color: c.line, width: 1 } },
    };
  }

  function lowRanges(years, counts) {
    const out = []; let start = null;
    years.forEach((y, i) => {
      const low = counts[i] < data.provenance.low_sample;
      if (low && start == null) start = y;
      if ((!low || i === years.length - 1) && start != null) {
        out.push([{ xAxis: String(start) }, { xAxis: String(low ? y : years[i - 1]) }]); start = null;
      }
    });
    return out;
  }

  // first index shown: the chosen year, or the first year with enough reports to read a share from
  function startIndex() {
    const since = val("since");
    if (since === "all") return 0;
    if (since) return Math.max(0, data.years.indexOf(Number(since)));
    // from the first year after which every year has enough reports (the running year may still be short)
    const d = data.denominator.docs, low = data.provenance.low_sample;
    let i = d.length - 1;
    if (i > 0 && d[i] < low) i--;
    while (i > 0 && d[i - 1] >= low) i--;
    return d[i] >= low ? i : 0;
  }

  function renderSeries() {
    const c = ink(), pal = PALETTE[mode()];
    const s0 = startIndex();
    const cut = (arr) => (arr || []).slice(s0);
    const measure = radio("measure") || "docs";
    const shareKey = measure === "docs" ? "share_docs" : "share_agencies";
    const numKey = measure === "docs" ? "docs" : "agencies";
    const yearsN = data.years.slice(s0);
    const years = yearsN.map(String);
    const denCounts = cut(data.denominator[numKey]);
    const denDocs = cut(data.denominator.docs), denLinks = cut(data.denominator.links), denAg = cut(data.denominator.agencies);
    const byYear = {};
    (form.events.checked ? data.events : []).forEach((e) => { (byYear[e.year] = byYear[e.year] || []).push(e.label); });
    const few = data.series.length <= 4;
    const evYears = new Set(Object.keys(byYear));
    const series = data.series.map((s, i) => ({
      name: s.name, type: "line", smooth: false, connectNulls: false,
      symbol: "circle", symbolSize: 8, showSymbol: true,
      lineStyle: { width: 2, color: pal[slots.get(s.key)] },
      itemStyle: { color: pal[slots.get(s.key)], borderColor: c.panel, borderWidth: 2 },
      emphasis: { focus: "series" },
      labelLayout: { moveOverlap: "shiftY" },
      endLabel: few ? { show: true, color: c.text, fontSize: 11, formatter: (p) => p.seriesName, distance: 6,
                        width: 150, overflow: "truncate", ellipsis: "…" } : { show: false },
      data: cut(s[shareKey]).map((v, j) => ({ value: v, link: cut(s.links)[j], n: cut(s[numKey])[j], of: denCounts[j] })),
      markArea: i === 0 ? { silent: true, itemStyle: { color: mode() === "dark" ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.035)" },
                            label: { show: true, position: "insideTop", color: c.muted, fontSize: 10, formatter: "few reports" },
                            data: lowRanges(yearsN, denDocs) } : undefined,
      markLine: i === 0 && Object.keys(byYear).length ? {
        silent: true, symbol: "none", animation: false,
        lineStyle: { color: c.muted, width: 1, type: "solid", opacity: 0.6 },
        label: { show: false },
        data: Object.keys(byYear).filter((y) => years.includes(y)).map((y) => ({ xAxis: y })),
      } : undefined,
    }));
    chart.setOption({
      animation: false, textStyle: { fontFamily: "system-ui, sans-serif" },
      grid: { left: 48, right: few ? 170 : 24, top: data.series.length > 1 ? 40 : 16, bottom: 40 },
      legend: { show: data.series.length > 1, top: 0, left: 0, icon: "circle", itemWidth: 10, itemHeight: 10,
                textStyle: { color: c.text, fontSize: 12 } },
      tooltip: {
        trigger: "axis", backgroundColor: c.panel, borderColor: c.line, textStyle: { color: c.text, fontSize: 12 },
        axisPointer: { type: "line", lineStyle: { color: c.muted, width: 1 } },
        formatter: (ps) => {
          const y = ps[0].axisValue;
          const ev = (byYear[y] || []).map((t) => `<div class="tt-ev">◆ ${esc(t)}</div>`).join("");
          const lowNote = ps[0].data && ps[0].data.of < data.provenance.low_sample ? `<div class="tt-low">few reports this year – read with care</div>` : "";
          return `<b>${esc(y)}</b>` + ps.map((p) => `<div class="tt-row"><span class="tt-dot" style="background:${p.color}"></span>
            ${esc(p.seriesName)} <b>${pct(p.data.value)}</b> <span class="tt-n">${p.data.n} of ${p.data.of}</span></div>`).join("") + lowNote + ev;
        },
      },
      xAxis: { type: "category", data: years, ...axisCommon(c), splitLine: { show: false },
               axisLabel: { color: c.muted, fontSize: 11, formatter: (y) => (evYears.has(y) ? y + "\n◆" : y) } },
      yAxis: { type: "value", min: 0, ...axisCommon(c), axisLabel: { color: c.muted, fontSize: 11, formatter: (v) => Math.round(v * 100) + "%" },
               axisLine: { show: false } },
      series,
    }, true);

    den.setOption({
      animation: false, grid: { left: 48, right: few ? 170 : 24, top: 8, bottom: 24 },
      tooltip: { trigger: "item", backgroundColor: c.panel, borderColor: c.line, textStyle: { color: c.text, fontSize: 12 },
                 formatter: (p) => `<b>${esc(p.name)}</b>: ${p.data.value} reports from ${p.data.agencies} agencies in scope` },
      xAxis: { type: "category", data: years, ...axisCommon(c), splitLine: { show: false } },
      yAxis: { type: "value", ...axisCommon(c), axisLine: { show: false }, splitNumber: 2 },
      series: [{ type: "bar", barCategoryGap: "20%",
                 data: denDocs.map((v, j) => ({ value: v, link: denLinks[j], agencies: denAg[j],
                   itemStyle: { color: v < data.provenance.low_sample ? c.line : c.muted, borderRadius: [4, 4, 0, 0] } })) }],
    }, true);

    const what = VIEW === "topics" ? "reports tagged with each topic" : "reports containing each term";
    $("#viz-sub").textContent = (measure === "docs" ? `Share of ${what}, per year` :
      `Share of publishing agencies with at least one of the ${what}, per year`) +
      ` · ${denDocs.reduce((a, b) => a + b, 0)} reports in scope, ${years[0]}–${years[years.length - 1]}` +
      ` · shaded years have fewer than ${data.provenance.low_sample} reports · ◆ reference event (hover for its name)`;

    // table view
    const head = `<tr><th>Year</th><th>In scope</th>${data.series.map((s) => `<th>${esc(s.name)}</th>`).join("")}</tr>`;
    const body = data.years.map((y, j) => `<tr><td>${y}</td><td><a href="${data.denominator.links[j]}">${data.denominator[numKey][j]}</a></td>` +
      data.series.map((s) => `<td><a href="${s.links[j]}">${s[numKey][j]}</a> <span class="muted">${pct(s[shareKey][j])}</span></td>`).join("") + "</tr>").reverse().join("");
    $("#table").innerHTML = `<table class="vt">${head}${body}</table>`;
  }

  function renderMatrix() {
    const c = ink();
    const rows = data.rows, tops = data.topics;
    const rowIdx = new Map(rows.map((r, i) => [r.key, i]));
    const topIdx = new Map(tops.map((t, i) => [t.key, i]));
    const max = Math.max(0.05, ...data.cells.map((x) => x.share));
    const el = $("#chart");
    el.style.width = Math.max(el.parentElement.clientWidth - 2, 290 + rows.length * 26) + "px";
    el.style.height = 150 + tops.length * 18 + "px";
    chart.resize();
    chart.setOption({
      animation: false, textStyle: { fontFamily: "system-ui, sans-serif" },
      grid: { left: 280, right: 16, top: 130, bottom: 10 },
      tooltip: { backgroundColor: c.panel, borderColor: c.line, textStyle: { color: c.text, fontSize: 12 },
        formatter: (p) => {
          const r = rows[p.data.value[0]], t = tops[p.data.value[1]];
          return `<b>${esc(r.label)}</b><br>${esc(t.name)} <span class="tt-n">(${esc(t.category)})</span><br>
                  <b>${p.data.n}</b> of ${r.docs} reports · <b>${pct(p.data.value[2])}</b><br><span class="tt-n">click for the list</span>`;
        } },
      xAxis: { type: "category", position: "top", data: rows.map((r) => `${r.label} (${r.docs})`), ...axisCommon(c),
               axisLabel: { color: c.muted, fontSize: 11, rotate: 50, interval: 0 }, splitLine: { show: false } },
      yAxis: { type: "category", inverse: true, data: tops.map((t) => t.name), ...axisCommon(c),
               axisLabel: { color: c.text, fontSize: 11, interval: 0, width: 260, overflow: "truncate" }, splitLine: { show: false } },
      visualMap: { show: false, min: 0, max, inRange: { color: SEQ[mode()] } },
      series: [{ type: "heatmap", itemStyle: { borderColor: c.panel, borderWidth: 2, borderRadius: 2 },
                 data: data.cells.map((x) => ({ value: [rowIdx.get(x.row), topIdx.get(x.topic), x.share], n: x.n, link: x.link })) }],
    }, true);
    $("#viz-sub").innerHTML = `Share of each ${data.by === "country" ? "country's" : "agency's"} reports from ${data.year_from}–${data.year_to}
      tagged with each topic · darker = larger share (0 – ${pct(max)}) · empty cell = no report tagged ·
      ${rows.length} ${data.by === "country" ? "countries" : "agencies"} with at least 5 reports
      <span class="legend-ramp" aria-hidden="true">${SEQ[mode()].map((col) => `<i style="background:${col}"></i>`).join("")}</span>`;
    const cell = new Map(data.cells.map((x) => [x.row + "|" + x.topic, x]));
    const head = `<tr><th>Topic</th>${rows.map((r) => `<th><a href="${r.link}">${esc(r.label)}</a> (${r.docs})</th>`).join("")}</tr>`;
    $("#table-wrap").ontoggle = () => {
      if (!$("#table-wrap").open || $("#table").dataset.done) return;
      $("#table").innerHTML = `<div class="vt-scroll"><table class="vt">${head}${tops.map((t) => `<tr><th>${esc(t.name)}</th>${rows.map((r) => {
        const x = cell.get(r.key + "|" + t.key);
        return x ? `<td><a href="${x.link}">${x.n}</a> <span class="muted">${pct(x.share)}</span></td>` : "<td class=\"muted\">0</td>";
      }).join("")}</tr>`).join("")}</table></div>`;
      $("#table").dataset.done = "1";
    };
  }

  function renderProvenance() {
    const p = data.provenance, x = p.excluded;
    const f = Object.entries(p.filters).map(([k, v]) => `${esc(k)} = ${esc(v)}`).join(", ") || "none (whole library)";
    $("#prov").innerHTML = `<p>${esc(p.how)}</p>
      <ul class="prov-list">
        <li><b>Documents:</b> the reports in this library (Documents page), each from an official agency page listed on
            <a href="/sources">Sources</a>. Filters: ${f}.</li>
        <li><b>Publishers:</b> ${x.independent ? `official agencies and <a href="/documents?${new URLSearchParams({...p.filters, type: "think-tank"})}">${x.independent} reports of independent think tanks</a> (◆) – choose “Official agencies only” to leave them out` : "official agencies only"}.</li>
        <li><b>Left out:</b> ${x.undated} undated, ${x.unclassified} not yet text-indexed, ${x.before_min_year} from before 2000
            – of ${x.listed} listed documents in this filter; not counted as reports at all:
            <a href="/documents?${new URLSearchParams({...p.filters, doc_type: "all"})}">${x.not_reports} statements, laws, finance tables and forms</a>; counted once:
            <a href="/documents?${new URLSearchParams({...p.filters, all_files: 1})}">${x.other_files} other language versions and summaries</a> of the same reports.</li>
        <li><b>Years:</b> from the title or address; for ${x.estimated || 0} reports found in their first pages – a report
            heading, or a publication date (shown as ≈ on the Documents page, with the evidence on hover).</li>
        <li><b>Topic tags:</b> keyword index <code>${esc(p.taxonomy.file)}</code> (version ${esc(p.taxonomy.hash)}); see
            <a href="/topics">Topics</a> for the terms behind each topic.</li>
        <li><b>Caveat:</b> more mentions means more attention, not necessarily a larger threat; agencies publish
            different kinds of reports at different rhythms, and recent years hold more reports.</li>
        <li class="muted">Computed ${esc(p.generated)} from the local database · <a href="${$("#csv").href}">CSV with a source link on every row</a></li>
      </ul>`;
    const evs = $("#events");
    if (evs) evs.innerHTML = (data.events || []).map((e) => `<li><b>${esc(e.date)}</b> ${esc(e.label)} –
      <a href="${esc(e.wikipedia_url)}" rel="noopener">Wikipedia</a> ·
      <a href="${esc(e.wikidata_url)}" rel="noopener">Wikidata ${esc(e.wikidata)}</a> <span class="muted">(${esc(e.date_property)}, retrieved ${esc(e.retrieved)})</span></li>`).join("");
  }

  function render() {
    if (VIEW === "matrix") renderMatrix(); else renderSeries();
    renderProvenance();
  }

  async function load() {
    syncUrl();
    if (VIEW !== "matrix" && !items.length) { chart.clear(); den.clear(); $("#viz-sub").textContent = "Choose at least one series."; return; }
    document.body.classList.add("loading");
    const api = VIEW === "topics" ? "topics" : VIEW === "terms" ? "terms" : "matrix";
    const res = await fetch(`/api/trends/${api}?${query(true)}`);
    data = await res.json();
    document.body.classList.remove("loading");
    render();
  }

  async function loadRising() {
    const q = query(true); q.delete("topic");
    const r = await (await fetch(`/api/trends/rising?${q}`)).json();
    $("#rising-sub").textContent = r.how + ` Based on ${r.docs_earlier} and ${r.docs_recent} reports.`;
    const li = (x) => `<li><span class="r-name"><a href="#" data-add="${esc(x.key)}" title="Add to the chart">${esc(x.name)}</a></span>
      <span class="r-pp ${x.change_pp >= 0 ? "up" : "down"}">${x.change_pp >= 0 ? "▲ +" : "▼ "}${x.change_pp} pp</span>
      <span class="r-n muted"><a href="${x.link_earlier}">${x.n_earlier}</a> → <a href="${x.link_recent}">${x.n_recent}</a> reports
      (${pct(x.earlier)} → ${pct(x.recent)})</span></li>`;
    $("#rising").innerHTML = r.rising.map(li).join("");
    $("#falling").innerHTML = r.falling.map(li).join("");
  }

  // ── controls ──
  function renderChips() {
    const box = $("#chips"); if (!box) return;
    const pal = PALETTE[mode()];
    box.innerHTML = items.map((k) => `<button type="button" class="topic-chip on" data-del="${esc(k)}" title="Remove">
      <span class="tt-dot" style="background:${pal[slots.get(k)]}"></span>${esc(NAMES[k] || k)} ✕</button>`).join("");
  }
  function addTopic(k) {
    if (!k || items.includes(k) || items.length >= 8) return;
    items.push(k); assignSlots(); renderChips(); load();
  }
  if (VIEW === "topics") {
    $("#add-topic").addEventListener("change", (e) => { addTopic(e.target.value); e.target.value = ""; });
    $("#chips").addEventListener("click", (e) => {
      const b = e.target.closest("[data-del]"); if (!b) return;
      items = items.filter((k) => k !== b.dataset.del); assignSlots(); renderChips(); load();
    });
    document.addEventListener("click", (e) => {
      const a = e.target.closest("[data-add]"); if (!a) return;
      e.preventDefault(); addTopic(a.dataset.add); window.scrollTo({ top: 0, behavior: "smooth" });
    });
    renderChips();
  }
  if (VIEW === "terms") {
    $("#terms").value = items.join("\n");
    $("#terms-go").addEventListener("click", () => {
      items = $("#terms").value.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 8);
      assignSlots(); load();
    });
  }
  form.addEventListener("change", (e) => {
    if (["measure", "events", "since"].includes(e.target.name)) { syncUrl(); data && render(); return; }
    load(); if (VIEW === "topics") loadRising();
  });

  load();
  if (VIEW === "topics") loadRising();
})();
