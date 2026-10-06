/* The progress panel of long jobs (templates/_jobpanel.html) – shared by the Update and Data exchange pages.
   One job runs at a time on the server; the panel polls /api/job, shows the steps, a progress bar with size, speed
   and time left, the live log and the result, and can cancel the job while that is safe. */
window.rzJobs = (function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const gb = (b) => (b == null ? "?" : b >= 1e9 ? (b / 1e9).toFixed(2) + " GB" : b >= 1e6 ? (b / 1e6).toFixed(0) + " MB" : (b / 1e3).toFixed(0) + " kB");
  const dur = (s) => (s == null ? "" : s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`);
  async function api(url, form) {
    const r = await fetch(url, form ? {method: "POST", body: new URLSearchParams(form)} : {});
    const data = await r.json().catch(() => ({error: `HTTP ${r.status}`}));
    if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }
  const CANCEL_TIP = {export: "Stop – the partial dataset is removed", update: "Stop – reports found and downloaded so far are kept",
                      check: "Stop – nothing is changed", import: "Stop – nothing in the library has been changed yet",
                      index: "Stop – indexing continues with the next update"};
  let timer = null, listeners = [], seenRunning = false;

  async function poll() {
    clearTimeout(timer);
    let j;
    try { j = (await api("/api/job")).job; } catch (e) { timer = setTimeout(poll, 3000); return; }
    render(j);
    if (j && j.status === "running") { seenRunning = true; timer = setTimeout(poll, 1000); }
  }

  function result(j) {
    const r = j.result;
    if (j.status === "done" && j.kind === "export" && r) {
      return `<p class="ok">✓ Dataset <code>${esc(r.dataset_id)}</code> written: ${r.parts.length} file${r.parts.length > 1 ? "s" : ""}, ${gb(r.bytes)}, ${r.scope.files_included} report files.</p>
        <p class="small">Copy or send these files together:</p><ul class="small mono">${r.parts.map((x) => `<li>${esc(x.name)} <span class="muted">${gb(x.size)}</span></li>`).join("")}<li>${esc(r.manifest_path.split("/").pop())}</li></ul>
        <p class="small muted">in ${esc(r.manifest_path.split("/").slice(0, -1).join("/"))}</p>`;
    }
    if (j.status === "done" && j.kind === "update" && r) {
      const found = r.crawl ? r.crawl.new_docs : null;
      return (found != null ? `<p class="${found ? "ok" : ""}"><b>${found ? `✓ ${found} new report${found > 1 ? "s" : ""} found` : "No new reports found"}</b></p>` : "")
        + `<pre class="dx-text">${esc(r.text)}</pre>`
        + `<p class="small"><a href="/new?day=${esc(r.day)}">What's new on ${esc(r.day)}</a> · <a href="/documents?added_from=${esc(r.day)}&amp;added_to=${esc(r.day)}&amp;sort=added">reports added on ${esc(r.day)}</a>`
        + (r.crawl && r.crawl.errors ? ` · <a href="/update?state=error#sources">sources with errors</a>` : "") + `</p>`;
    }
    if (r && r.text) {
      return `<pre class="dx-text">${esc(r.text)}</pre>` + (r.report_path ? `<p class="small muted">Full report: ${esc(r.report_path)}</p>` : "");
    }
    return `<p class="${j.status === "done" ? "ok" : "err"}">${esc(j.error || (j.status === "done" ? "✓ done" : j.status))}</p>`
      + (r && r.problems ? `<ul>${r.problems.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "");
  }

  function render(j) {
    const box = $("#job");
    if (!box) return;
    if (!j || box.dataset.closed === j.id) { box.hidden = true; listeners.forEach((f) => f(null)); return; }
    box.hidden = false;
    const running = j.status === "running";
    document.querySelectorAll("[data-starts-job]").forEach((b) => b.toggleAttribute("data-busy", running));
    $("#job-title").textContent = `${j.title || j.kind}${running ? "…" : j.status === "done" ? " – done" : j.status === "cancelled" ? " – cancelled" : " – failed"}`;
    box.className = `viz-card dx-job st-${j.status}`;
    $("#job-log-link").href = `/data/logs/${j.log_file}`;
    $("#job-steps").innerHTML = j.phases.map((p, i) => `<li class="${i < j.phases.length - 1 || !running ? "done" : "now"}">${esc(p)}</li>`).join("");
    const p = j.progress, bar = $("#job-bar");
    if (running && p.total) { bar.max = p.total; bar.value = p.done; $("#job-pct").textContent = Math.floor(100 * p.done / p.total) + " %"; }
    else if (running) { bar.removeAttribute("value"); $("#job-pct").textContent = ""; }
    else { bar.max = 1; bar.value = 1; $("#job-pct").textContent = ""; }
    const bytes = p.total > 1e6;
    $("#job-nums").textContent = [
      running ? p.phase : "",
      running && p.total ? (bytes ? `${gb(p.done)} of ${gb(p.total)}` : `${p.done} of ${p.total}`) : "",
      running && p.note ? p.note : "",
      running && j.rate && bytes ? `${gb(j.rate)}/s` : "",
      running && j.eta != null ? `about ${dur(j.eta)} left` : "",
      `${running ? "running" : "took"} ${dur(j.elapsed)}`].filter(Boolean).join(" · ");
    const cancel = $("#job-cancel");
    cancel.hidden = !running;
    cancel.disabled = !j.cancellable;
    cancel.title = j.cancellable ? (CANCEL_TIP[j.kind] || "Stop") : "The library is being changed: this step cannot be stopped";
    $("#job-close").hidden = running;
    const log = $("#job-log");
    const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 5;
    log.textContent = j.log.join("\n");
    if (atEnd) log.scrollTop = log.scrollHeight;
    const res = $("#job-result");
    res.hidden = running;
    if (!running) res.innerHTML = result(j);
    listeners.forEach((f) => f(j, {justFinished: !running && seenRunning}));
  }

  async function start(url, form) {
    try { await api(url, form); $("#job") && delete $("#job").dataset.closed; poll(); return true; }
    catch (e) { alert(e.message); return false; }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!$("#job")) return;
    $("#job-cancel").addEventListener("click", () => api("/api/job/cancel", {}).then(poll));
    $("#job-close").addEventListener("click", () => api("/api/job").then((r) => { if (r.job) $("#job").dataset.closed = r.job.id; $("#job").hidden = true; }));
    poll();
  });
  return {start, poll, onRender: (f) => listeners.push(f), util: {api, esc, gb, dur}};
})();
