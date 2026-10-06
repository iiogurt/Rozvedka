/* Data exchange page: folder picker, export and import with progress, log and result.
   Everything runs on the server (the Raspberry Pi); this page only starts jobs; static/jobs.js shows their progress. */
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const {api, esc, gb, dur} = rzJobs.util;

  // ---------------------------------------------------------------- folder picker
  function Picker(el, onChange) {
    let cur = null;
    async function go(path) {
      let d;
      try { d = await api("/api/data/folders?path=" + encodeURIComponent(path || "")); }
      catch (e) { if (path) return go(""); el.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
      cur = d;
      const roots = d.roots.map((r) => `<button type="button" class="dx-root ${d.path && (d.path === r.path || d.path.startsWith(r.path + "/")) ? "on" : ""}" data-go="${esc(r.path)}">${esc(r.name)}${r.free != null ? ` <span class="muted">${gb(r.free)} free</span>` : ""}</button>`).join("");
      let body;
      if (!d.path) {
        body = `<p class="muted small">Choose where to start: a USB disk appears under <code>/media</code> when it is plugged in.</p>`;
      } else {
        const crumbs = d.parents.map((p, i) => `<button type="button" class="dx-crumb" data-go="${esc(p.path)}">${esc(i ? p.name : p.path)}</button>`).join("<span class=\"muted\">/</span>");
        const dirs = d.dirs.length ? d.dirs.map((x) => `<li><button type="button" data-go="${esc(x.path)}">📁 ${esc(x.name)}</button></li>`).join("") : `<li class="muted small">no subfolders</li>`;
        body = `<div class="dx-crumbs">${crumbs}</div>
          <div class="dx-here small"><b>${esc(d.path)}</b> · ${gb(d.free)} free of ${gb(d.total)}${d.writable ? "" : " · <span class=\"err\">read-only for the portal</span>"}${d.datasets.length ? ` · ${d.datasets.length} dataset${d.datasets.length > 1 ? "s" : ""}` : ""}</div>
          <ul class="dx-dirs">${d.parents.length > 1 ? `<li><button type="button" data-go="${esc(d.parents[d.parents.length - 2].path)}">⤴ up</button></li>` : ""}${dirs}</ul>
          ${d.writable ? `<form class="dx-mkdir"><input name="name" placeholder="new folder" aria-label="New folder name" maxlength="60"><button>Create</button></form>` : ""}`;
      }
      el.innerHTML = `<div class="dx-roots">${roots}</div>${body}`;
      el.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));
      const mk = $(".dx-mkdir", el);
      if (mk) mk.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try { const r = await api("/api/data/folders", {parent: d.path, name: mk.name.value}); go(r.path); }
        catch (e) { alert(e.message); }
      });
      onChange(d);
    }
    go(el.dataset.start || "");
    return {current: () => cur, refresh: () => { if (cur) go(cur.path); }};
  }

  // ---------------------------------------------------------------- export
  let estimate = null, exportDir = null;
  async function updateEstimate() {
    const what = $("input[name=what]:checked").value, since = $("#since").value;
    for (const w of ["all", "catalogue", "since"]) {
      try {
        const e = await api(`/api/data/estimate?what=${w}&since=${encodeURIComponent(w === "since" ? since : "")}`);
        $(`.dx-size[data-for=${w}]`).textContent = w === "since" && !since ? "" : `about ${gb(e.total)}` + (e.files ? ` · ${e.files} report files` : "");
        if (w === what) estimate = e;
      } catch (e) { /* shown when exporting */ }
    }
    updateSpace();
  }
  function updateSpace() {
    const btn = $("#export-go"), out = $("#space");
    const what = $("input[name=what]:checked").value;
    if (!exportDir || !exportDir.path) { btn.disabled = true; out.textContent = "Choose a folder."; return; }
    if (!exportDir.writable) { btn.disabled = true; out.innerHTML = `<span class="err">The portal may not write into this folder.</span>`; return; }
    if (what === "since" && !$("#since").value) { btn.disabled = true; out.textContent = "Choose the day from which report files are included."; return; }
    const need = estimate ? estimate.total : 0, free = exportDir.free;
    const ok = need <= free;
    const parts = Math.max(1, Math.ceil(need / (Number($("#part-size").value) * 1e6)));
    out.innerHTML = `<meter min="0" max="${free}" value="${Math.min(need, free)}" low="${free * 0.7}" high="${free * 0.9}" optimum="0"></meter>
      Needs about <b>${gb(need)}</b> (${parts} file${parts > 1 ? "s" : ""} + manifest) – ${gb(free)} free in <b>${esc(exportDir.path)}</b>.
      ${ok ? "" : `<span class="err">Not enough space.</span>`}`;
    btn.disabled = !ok;
    btn.textContent = `Export to ${exportDir.path}`;
  }

  // ---------------------------------------------------------------- import: datasets in the chosen folder
  function showDatasets(d) {
    const box = $("#datasets");
    if (!d.path) { box.innerHTML = ""; return; }
    if (!d.datasets.length) { box.innerHTML = `<p class="muted">No dataset in this folder (looking for <code>*.manifest.json</code>).</p>`; return; }
    box.innerHTML = d.datasets.map((s) => `<article class="dx-ds">
      <div><b>${esc(s.label || s.id)}</b> <span class="muted small">${esc(s.name)}</span></div>
      <div class="small">made ${esc((s.created || "").slice(0, 16).replace("T", " "))} UTC by installation <code>${esc(s.installation)}</code> with Rozvedka ${esc(s.app_version)}
        · ${s.documents ?? "?"} reports, last crawl ${esc((s.last_crawl || "never").slice(0, 10))}
        · ${s.with_files === false ? "catalogue only" : `${s.files} report files${s.since ? " since " + esc(s.since) : ""}`} · ${gb(s.bytes)}</div>
      <div class="small">${s.complete ? `<span class="ok">✓ ${s.parts > 1 ? `all ${s.parts} files` : "the file"} present</span>` : `<span class="err">✗ ${s.parts_present} of ${s.parts} files present – copy the missing ones into this folder</span>`}</div>
      <button type="button" class="dx-primary" data-starts-job data-check="${esc(s.manifest)}" ${s.complete ? "" : "disabled"}>Check and compare</button>
    </article>`).join("");
    box.querySelectorAll("[data-check]").forEach((b) => b.addEventListener("click", () => startJob("/api/data/check", {manifest: b.dataset.check})));
  }

  // ---------------------------------------------------------------- jobs (the panel is static/jobs.js)
  let lastManifest = null;
  const startJob = (url, form) => rzJobs.start(url, form).then((ok) => { if (ok && form.manifest) lastManifest = form.manifest; });
  rzJobs.onRender((j, info) => {
    const imp = $("#job-import");
    imp.hidden = !(j && j.kind === "check" && j.status === "done" && !j.error);
    if (!imp.hidden) {
      lastManifest = j.params.path;
      const c = j.result && j.result.compare;
      $("#job-import-go").textContent = c && c.empty_here ? "Import as this library's starting point" : c && c.verdict === "older" ? "Import anyway (adds nothing new)" : "Import this dataset";
    }
    if (j && info && info.justFinished && j.status === "done" && j.kind !== "check" && refreshedFor !== j.id) {
      refreshedFor = j.id;                     // a new dataset or new files: show them in the pickers
      pickers.forEach((pk) => pk.refresh());
    }
  });
  let refreshedFor = null;

  const pickers = [];
  document.addEventListener("DOMContentLoaded", () => {
    // tabs
    document.querySelectorAll("input[name=tab]").forEach((r) => r.addEventListener("change", () => {
      const v = $("input[name=tab]:checked").value;
      $("#tab-export").hidden = v !== "export";
      $("#tab-import").hidden = v !== "import";
    }));
    pickers.push(Picker($("#picker-export"), (d) => { exportDir = d; updateSpace(); }));
    pickers.push(Picker($("#picker-import"), showDatasets));
    document.querySelectorAll("input[name=what]").forEach((r) => r.addEventListener("change", updateEstimate));
    $("#since").addEventListener("change", () => { $("input[name=what][value=since]").checked = true; updateEstimate(); });
    $("#part-size").addEventListener("change", updateSpace);
    $("#export-go").addEventListener("click", () => startJob("/api/data/export", {
      dest: exportDir.path, what: $("input[name=what]:checked").value, since: $("#since").value,
      part_size: $("#part-size").value, name: $("#label").value}));
    $("#job-import-go").addEventListener("click", () => {
      if (!confirm("Import the dataset into this library now? A safety copy of the database is made first.")) return;
      startJob("/api/data/import", {manifest: lastManifest, prefer: $("input[name=prefer]:checked").value});
    });
    updateEstimate();
  });
})();
