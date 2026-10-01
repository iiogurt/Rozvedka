/* Light/dark theme. Dark is the default; the viewer's choice is remembered in this browser (localStorage).
   Loaded in <head> so the saved theme applies before the page is drawn. Charts listen through window.rzDark,
   which behaves like matchMedia("(prefers-color-scheme: dark)") but follows the toggle. */
(function () {
  "use strict";
  const KEY = "rz-theme";
  const root = document.documentElement;
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* storage blocked: use the default */ }
  root.dataset.theme = saved === "light" ? "light" : "dark";

  const listeners = [];
  window.rzDark = {
    get matches() { return root.dataset.theme === "dark"; },
    addEventListener(type, fn) { if (type === "change") listeners.push(fn); },
  };
  window.rzSetTheme = function (theme) {
    root.dataset.theme = theme;
    try { localStorage.setItem(KEY, theme); } catch (e) { /* not remembered, still applied */ }
    listeners.forEach((fn) => fn({ matches: theme === "dark" }));
    document.querySelectorAll(".theme-toggle").forEach(label);
  };
  function label(btn) {
    const dark = root.dataset.theme === "dark";
    btn.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    btn.title = btn.getAttribute("aria-label");
    btn.setAttribute("aria-pressed", String(dark));
  }
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".theme-toggle").forEach((btn) => {
      label(btn);
      btn.addEventListener("click", () => window.rzSetTheme(root.dataset.theme === "dark" ? "light" : "dark"));
    });
  });
})();
