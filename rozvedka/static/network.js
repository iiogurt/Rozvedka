/* Network: actors (nodes) linked when named in the same passage. Every node and link opens its source. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const form = $("#scope");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  // one fixed colour per kind (validated categorical palette, light/dark); "other" stays neutral
  const SLOT = { state: 0, armed: 1, person: 2, crime: 3, movement: 4, country: 5, cyber: 6, terror: 7 };
  const PALETTE = {
    light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
  };
  const color = (kind) => (kind in SLOT ? PALETTE[darkQuery.matches ? "dark" : "light"][SLOT[kind]] : css("--muted"));

  const url = new URL(window.location);
  for (const el of form.elements) {
    const v = url.searchParams.get(el.name);
    if (v == null) continue;
    if (el.type === "checkbox") el.checked = v === "1"; else el.value = v;
  }
  function query() {
    const q = new URLSearchParams();
    for (const el of form.elements) {
      if (!el.name) continue;
      if (el.type === "checkbox") { if (el.checked) q.set(el.name, "1"); } else if (el.value) q.set(el.name, el.value);
    }
    return q;
  }

  const chart = echarts.init($("#net"), null, { renderer: "canvas" });
  let data = null;
  chart.on("click", (p) => { if (p.data && p.data.href) window.location.href = p.data.href; });
  window.addEventListener("resize", () => chart.resize());
  darkQuery.addEventListener("change", () => data && render());

  function render() {
    const ink = css("--ink"), muted = css("--muted"), panel = css("--panel"), line = css("--line");
    const kinds = [...new Set(data.nodes.map((n) => n.kind))];
    const maxDocs = Math.max(1, ...data.nodes.map((n) => n.docs));
    const maxLink = Math.max(1, ...data.links.map((l) => l.docs));
    const labelled = new Set(data.nodes.slice(0, 30).map((n) => n.key));
    chart.setOption({
      animationDurationUpdate: 300,
      tooltip: { backgroundColor: panel, borderColor: line, textStyle: { color: ink, fontSize: 12 },
        formatter: (p) => p.dataType === "edge"
          ? `<b>${esc(p.data.la)}</b> and <b>${esc(p.data.lb)}</b><br>named in the same passage in ${p.data.docs} reports<br><span style="color:${muted}">click for the passages</span>`
          : `<b>${esc(p.data.name)}</b><br>${esc(data.kinds[p.data.kind] || p.data.kind)}<br>named in ${p.data.docs} reports<br><span style="color:${muted}">click for the actor page</span>` },
      legend: { top: 0, left: 0, icon: "circle", itemWidth: 10, itemHeight: 10, textStyle: { color: ink, fontSize: 12 },
                data: kinds.map((k) => data.kinds[k] || k) },
      series: [{
        type: "graph", layout: "force", roam: true, draggable: true, top: 40,
        categories: kinds.map((k) => ({ name: data.kinds[k] || k, itemStyle: { color: color(k) } })),
        force: { repulsion: 140, edgeLength: [40, 160], gravity: 0.08, friction: 0.15 },
        emphasis: { focus: "adjacency", lineStyle: { width: 3 } },
        label: { show: true, position: "right", fontSize: 11, color: ink,
                 formatter: (p) => (labelled.has(p.data.key) ? p.data.name : "") },
        labelLayout: { hideOverlap: true },
        lineStyle: { color: "source", opacity: 0.35, curveness: 0.12 },
        data: data.nodes.map((n) => ({ id: n.key, key: n.key, name: n.label, kind: n.kind, docs: n.docs, href: n.link,
          category: kinds.indexOf(n.kind), symbolSize: 6 + 30 * Math.sqrt(n.docs / maxDocs),
          itemStyle: { borderColor: panel, borderWidth: 1.5 } })),
        links: data.links.map((l) => ({ source: l.a, target: l.b, docs: l.docs, href: l.link,
          la: (data.nodes.find((n) => n.key === l.a) || {}).label, lb: (data.nodes.find((n) => n.key === l.b) || {}).label,
          lineStyle: { width: 0.6 + 4 * (l.docs / maxLink) } })),
      }],
    }, true);
    $("#net-sub").textContent = `${data.nodes.length} actors (size = reports naming them), ${data.links.length} links ` +
      `(width = reports naming both in one passage, at least ${form.min_link.value}).`;
    const label = Object.fromEntries(data.nodes.map((n) => [n.key, n.label]));
    const top = [...data.links].sort((x, y) => y.docs - x.docs).slice(0, 150);
    $("#table").innerHTML = `<table class="vt"><tr><th>Actor</th><th>Actor</th><th>Reports</th></tr>` +
      top.map((l) => `<tr><td><a href="/actors/${esc(l.a)}">${esc(label[l.a])}</a></td><td><a href="/actors/${esc(l.b)}">${esc(label[l.b])}</a></td>
        <td><a href="${esc(l.link)}">${l.docs}</a></td></tr>`).join("") + "</table>";
    const p = data.provenance, x = p.excluded;
    $("#prov").innerHTML = `<p>${esc(p.how)}</p><ul class="prov-list">
      <li><b>Actors</b> come from the actor index (Wikidata, MITRE ATT&amp;CK, sources/actors.yaml; retrieved ${esc(p.gazetteer || "–")}) and
        are found by name – see <a href="/actors">Actors</a> and <a href="/actors/names">the names used</a>.</li>
      <li><b>Reports in scope:</b> listed documents with indexed text matching the filters; ${x.undated} undated documents count
        only without a year filter. Reports dated before an actor was founded are not counted.</li>
      <li class="muted">Computed ${esc(p.generated)} from the local database.</li></ul>`;
  }

  async function load() {
    const q = query();
    const page = new URL(window.location); page.search = q.toString();
    history.replaceState(null, "", page); $("#permalink").href = page.toString();
    document.body.classList.add("loading");
    data = await (await fetch(`/api/network?${q}`)).json();
    document.body.classList.remove("loading");
    render();
  }
  form.addEventListener("change", load);
  load();
})();
