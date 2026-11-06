// Restored lock before anything else runs (IN-08): a classic (non-module) script right after
// #lock-overlay in index.html, so a reloaded or restored tab is covered while app.js, helm.js,
// the WebSocket and the map are still loading. lock.js takes over (padlock, long-press unlock)
// once it is imported. External file, not inline: the CSP allows 'self' scripts only.
(function () {
  try {
    if (localStorage.getItem("jabuka.locked") !== "1") return;
    var overlay = document.getElementById("lock-overlay");
    if (overlay) overlay.hidden = false;
    document.body.classList.add("locked");
  } catch (e) {
    /* private mode: no stored lock */
  }
})();
