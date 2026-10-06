/* Update page: choose what to do and which sources, see the plan (pages, time), start; tick sources in the table or
   check one now. The progress panel is static/jobs.js. */
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const {api, esc, dur} = rzJobs.util;
  const ticked = () => [...document.querySelectorAll(".tick:checked")].map((c) => c.value);

  function form() {
    return {action: $("input[name=action]:checked").value, scope: $("input[name=scope]:checked").value,
            country: $("#country").value, sources: ticked().join(","), stale_days: $("#stale-days").value,
            retry_failed: $("#retry").checked ? "1" : ""};
  }

  let seq = 0, reloaded = false;
  async function plan() {
    const f = form(), mine = ++seq, out = $("#plan"), go = $("#update-go");
    $("#ticked-n").textContent = `(${ticked().length})`;
    if (f.scope === "country" && !f.country) { out.textContent = "Choose a country."; go.disabled = true; return; }
    if (f.scope === "sources" && !f.sources) { out.textContent = "Tick sources in the table below."; go.disabled = true; return; }
    let p;
    try { p = await api("/api/update/plan?" + new URLSearchParams(f)); } catch (e) { out.textContent = e.message; return; }
    if (mine !== seq) return;
    const parts = [];
    if (f.action !== "download") {
      parts.push(`Checks <b>${p.pages}</b> report page${p.pages !== 1 ? "s" : ""} of <b>${p.sources}</b> source${p.sources !== 1 ? "s" : ""}`
        + (p.manual ? ` (${p.manual} collected by hand are skipped – <a href="/collect">To collect</a>)` : ""));
    }
    if (f.action !== "check") parts.push(`${f.action === "full" ? "then downloads the new reports and" : "downloads"} <b>${p.waiting}</b> report${p.waiting !== 1 ? "s" : ""} already waiting`);
    if (f.action === "full") parts.push("and indexes them");
    out.innerHTML = parts.join(", ") + `. About <b>${dur(p.seconds) || "a few seconds"}</b>${p.note ? " " + esc(p.note) : ""}`
      + ` <span class="muted">(${p.seconds_per_page} s per page${p.measured ? ", measured on the last checks" : ", an estimate until enough pages have been measured"})</span>.`;
    go.disabled = (f.action !== "download" && !p.pages) || (f.action === "download" && !p.waiting);
    go.textContent = {full: "Start the update", check: "Check for new reports", download: "Download"}[f.action];
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("input[name=action], input[name=scope], #retry").forEach((el) => el.addEventListener("change", plan));
    $("#stale-days").addEventListener("input", () => { $("input[name=scope][value=stale]").checked = true; plan(); });
    $("#country").addEventListener("change", () => { $("input[name=scope][value=country]").checked = true; plan(); });
    document.querySelectorAll(".tick").forEach((c) => c.addEventListener("change", () => {
      if (ticked().length) $("input[name=scope][value=sources]").checked = true;
      plan();
    }));
    $("#tick-all").addEventListener("change", (e) => {
      document.querySelectorAll(".tick").forEach((c) => { c.checked = e.target.checked; });
      if (e.target.checked) $("input[name=scope][value=sources]").checked = true;
      plan();
    });
    $("#update-go").addEventListener("click", async () => {
      if (await rzJobs.start("/api/update", form())) window.scrollTo({top: $("#job").offsetTop - 70, behavior: "smooth"});
    });
    document.querySelectorAll(".upd-now").forEach((b) => b.addEventListener("click", async () => {
      if (await rzJobs.start("/api/update", {action: "check", scope: "sources", sources: b.dataset.source})) {
        window.scrollTo({top: $("#job").offsetTop - 70, behavior: "smooth"});
      }
    }));
    rzJobs.onRender((j, info) => {         // a finished update changes the table: reload it once
      if (j && info && info.justFinished && j.kind === "update" && !reloaded) {   // only for a run seen on this page
        reloaded = true;
        location.reload();
      }
    });
    plan();
  });
})();
