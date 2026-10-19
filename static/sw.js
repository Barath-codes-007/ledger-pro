/*
 * Ledger service worker.
 * Scope: makes the app installable and speeds up repeat loads of static
 * assets (CSS/JS/icons/fonts). It deliberately does NOT cache any page
 * that reads or writes financial data (dashboard, expenses, income,
 * accounts, API routes, etc.) - those always go to the network, so you
 * never see stale or offline financial figures. When fully offline and a
 * page can't be reached, it falls back to a plain "you're offline" page
 * rather than claiming to work without a connection.
 */
const CACHE_NAME = "ledger-static-v2";
const STATIC_ASSETS = [
  "/static/css/style.css",
  "/static/js/main.js",
  "/static/js/charts.js",
  "/static/js/voice-assistant.js",
  "/static/js/receipt-camera.js",
  "/static/js/vendor/chart.umd.min.js",
  "/static/manifest.webmanifest",
  "/static/img/icon-192.png",
  "/static/img/icon-512.png",
  "/static/offline.html",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Only ever serve static assets from cache; everything else (pages,
  // /api/*, receipts) always goes to the network - financial data is
  // never served stale or offline.
  const isStaticAsset = url.pathname.startsWith("/static/") && event.request.method === "GET";

  if (!isStaticAsset) {
    event.respondWith(
      fetch(event.request).catch(() => {
        if (event.request.mode === "navigate") {
          return caches.match("/static/offline.html");
        }
        return Response.error();
      })
    );
    return;
  }

  // Network-first for static assets: always try for the latest copy so an
  // updated script or stylesheet reaches people straight away, and only fall
  // back to the cache when offline. (The earlier cache-first strategy kept
  // serving old JS/CSS after updates until the cache was cleared by hand.)
  event.respondWith(
    fetch(event.request)
      .then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return resp;
      })
      .catch(() => caches.match(event.request))
  );
});
