/* VERONICA service worker: makes the web app installable (Add to Home screen). Always network - live ERP data is never cached. */
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.mode === "navigate") e.respondWith(fetch(e.request).catch(() => new Response(
    "<meta name=viewport content='width=device-width'><body style='background:#02060d;color:#a9e3ff;font:16px sans-serif;display:grid;place-items:center;height:100vh'>VERONICA is offline - check the internet / tunnel and try again.</body>",
    { headers: { "Content-Type": "text/html" } })));
});
