// Lists with a preview pane (Reports, Actors): a row can be selected (click, ↑ ↓ or j k) and previewed in a pane
// beside the list (space, or its button) without leaving the list; enter opens its page. A row says where its preview
// (data-pv) and its page (data-open) are; a report's preview gets the list's own search, so it shows the passage
// that made the report match.
(() => {
  const rows = [...document.querySelectorAll("tbody tr[data-pv]")];
  const pane = document.getElementById("pv");
  if (!rows.length || !pane) return;
  const cache = new Map();
  let sel = -1, open = false, timer = 0;
  const want = new URLSearchParams(location.search);
  const qs = new URLSearchParams();
  if (pane.dataset.search !== undefined) for (const k of ["q", "exact", "indexed", "actor"]) if (want.get(k)) qs.set(k, want.get(k));
  const what = pane.dataset.what || "report";
  const kicker = `<p class="pv-kicker"><span>Preview · ${what}</span></p>`;

  function show(i) {
    const id = rows[i].dataset.pv;
    const put = (html) => { if (rows[sel] && rows[sel].dataset.pv === id) { pane.innerHTML = html; pane.scrollTop = 0; } };
    if (cache.has(id)) return put(cache.get(id));
    pane.innerHTML = kicker + '<p class="muted small">Loading…</p>';
    fetch(`${id}?${qs}`).then((r) => r.ok ? r.text() : Promise.reject(r.status))
      .then((html) => { cache.set(id, html); put(html); })
      .catch(() => put(kicker + '<p class="muted small">The preview could not be loaded.</p>'));
  }
  function setOpen(on) {
    open = on && sel >= 0;
    pane.hidden = !open;
    document.body.classList.toggle("pv-open", open);
    rows.forEach((r, i) => r.querySelector(".pv-btn")?.setAttribute("aria-pressed", String(open && i === sel)));
    if (open) show(sel);
  }
  function select(i, scroll) {
    if (i < 0 || i >= rows.length) return;
    rows[sel]?.classList.remove("sel");
    sel = i;
    rows[sel].classList.add("sel");
    if (scroll) rows[sel].scrollIntoView({ block: "nearest" });
    if (open) { clearTimeout(timer); timer = setTimeout(() => setOpen(true), 90); }   // holding ↓ does not fetch every row
  }

  rows.forEach((r, i) => {
    r.addEventListener("click", (e) => {
      const btn = e.target.closest(".pv-btn");
      if (btn) { const same = open && sel === i; select(i); setOpen(!same); return; }
      if (e.target.closest("a, button, input, select, textarea, summary, form, label")) return;
      if (String(getSelection())) return;                  // the reader is marking text, not picking the row
      select(i);
      setOpen(true);
    });
  });
  const first = /^#pv-([\w.:-]+)$/.exec(location.hash);    // an address ending #pv-<row id> opens with that preview
  const at = first ? rows.findIndex((r) => r.dataset.id === first[1]) : -1;
  if (at >= 0) { select(at, true); setOpen(true); }
  pane.addEventListener("click", (e) => { if (e.target.closest(".pv-close")) setOpen(false); });
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest?.("input, textarea, select, button, summary, [contenteditable]")) return;
    const k = e.key;
    if (k === "ArrowDown" || k === "j") select(sel < 0 ? 0 : sel + 1, true);
    else if (k === "ArrowUp" || k === "k") select(sel < 0 ? 0 : sel - 1, true);
    else if (k === " " && sel >= 0) setOpen(!open);
    else if (k === "Enter" && sel >= 0) location.href = rows[sel].dataset.open;
    else if (k === "Escape" && open) setOpen(false);
    else return;
    e.preventDefault();
  });
})();
