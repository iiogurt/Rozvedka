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
  // chart colours live in style.css (--cat-1…8, --seq-1…7, --nodata, --thin) – one place, both themes; read at draw time
  const tok = (name) => getComputedStyle(root).getPropertyValue(name).trim();
  const run = (prefix, n) => Array.from({ length: n }, (_, i) => tok(prefix + (i + 1)));
  window.rzTokens = { cat: () => run("--cat-", 8), seq: () => run("--seq-", 7), get: tok };
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
