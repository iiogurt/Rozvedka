// A thing's page as tabs: sections marked data-tab are shown one tab at a time; the tab bar is <nav data-tabs> with links
// to #tab-<name>. A link to a part of the page (#passages, #sanctions) opens the tab that part is on, so every address
// that worked on the long page still works. Without scripts the page is the long page it was.
(function () {
  const nav = document.querySelector("[data-tabs]");
  if (!nav) return;
  const parts = Array.from(document.querySelectorAll("[data-tab]"));
  const links = Array.from(nav.querySelectorAll("a[href^='#tab-']"));
  for (const a of links) {                                   // a tab with nothing on it is not offered
    if (!parts.some((p) => p.dataset.tab === a.hash.slice(5))) a.remove();
  }
  const first = (nav.querySelector("a[href^='#tab-']") || {}).hash;
  if (!first) { nav.hidden = true; return; }
  function tabOf(hash) {
    if (!hash || hash.length < 2) return [first.slice(5), null];
    let id = hash.slice(1);
    try { id = decodeURIComponent(id); } catch (e) { /* a stray % – taken as it is */ }
    if (id.startsWith("tab-")) return [parts.some((p) => p.dataset.tab === id.slice(4)) ? id.slice(4) : first.slice(5), null];
    const el = document.getElementById(id);
    const part = el && el.closest("[data-tab]");
    return [part ? part.dataset.tab : first.slice(5), part ? el : null];
  }
  function show() {
    const [tab, target] = tabOf(location.hash);
    for (const p of parts) p.hidden = p.dataset.tab !== tab;
    for (const a of nav.querySelectorAll("a[href^='#tab-']")) {
      const on = a.hash.slice(5) === tab;
      a.classList.toggle("on", on);
      if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
    }
    window.dispatchEvent(new Event("resize"));               // charts on a tab that was hidden take their size now
    if (target) target.scrollIntoView();
  }
  nav.addEventListener("click", (e) => {                      // a tab opens in place: the page does not jump to the top
    const a = e.target.closest("a[href^='#tab-']");
    if (!a) return;
    e.preventDefault();
    history.replaceState(null, "", a.hash);
    show();
  });
  window.addEventListener("hashchange", show);
  show();
})();
