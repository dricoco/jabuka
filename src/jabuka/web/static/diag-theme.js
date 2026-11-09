// Diag night theme before the first paint (G-4-R10): a classic (non-module) script in the <head> of
// diag.html, right after diag.css, puts html.theme-night from the helm's stored theme so the Diag
// tab (or a standalone diag tab) never flashes a non-red page at night. diag.js follows later
// switches (storage event) and app.js propagates them into the Diag frame. External file, not
// inline: the CSP allows 'self' scripts only (same pattern as lock-early.js).
(function () {
  try {
    if (localStorage.getItem("jabuka.theme") === "night") {
      document.documentElement.classList.add("theme-night");
    }
  } catch (e) {
    /* private mode: no stored theme, day variant */
  }
})();
