/* Sources page: show only countries (and flags) belonging to the chosen coalition. */
(function () {
  "use strict";
  const buttons = document.querySelectorAll(".cf");
  const items = document.querySelectorAll("section.country, .flagbar a");
  function apply(key) {
    buttons.forEach((b) => b.classList.toggle("on", b.dataset.coalition === key));
    items.forEach((el) => {
      el.hidden = key !== "" && !(el.dataset.coalitions || "").split(" ").includes(key);
    });
    document.querySelectorAll(".flagsep").forEach((s) => { s.hidden = key !== ""; });
    // hide region headings whose countries are all hidden
    document.querySelectorAll("h2.region").forEach((h) => {
      let el = h.nextElementSibling, any = false;
      while (el && !el.matches("h2.region")) {
        if (el.matches("section.country") && !el.hidden) any = true;
        el = el.nextElementSibling;
      }
      h.hidden = !any;
    });
    const url = new URL(window.location);
    key ? url.searchParams.set("coalition", key) : url.searchParams.delete("coalition");
    history.replaceState(null, "", url);
  }
  buttons.forEach((b) => b.addEventListener("click", () => apply(b.dataset.coalition)));
  const initial = new URLSearchParams(window.location.search).get("coalition");
  if (initial) apply(initial);
})();
