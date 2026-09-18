/* Read-only dashboard fragment refresh; no CDN or build step required. */
(function () {
  "use strict";

  function start(element) {
    var url = element.dataset.liveUrl;
    var interval = Number(element.dataset.liveIntervalMs || 10000);
    if (!url || !Number.isFinite(interval) || interval < 1000) return;

    async function refresh() {
      try {
        var response = await fetch(url, {
          headers: { "Accept": "text/html", "X-Dashboard-Refresh": "1" },
          cache: "no-store"
        });
        if (!response.ok) return;
        element.innerHTML = await response.text();
      } catch (_error) {
        /* A stale status panel is safer than making a control action fail. */
      }
    }

    window.setInterval(refresh, interval);
  }

  document.querySelectorAll("[data-live-url]").forEach(start);
}());
