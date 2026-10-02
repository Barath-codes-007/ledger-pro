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
const CACHE_NAME = "ledger-static-v1";
const STATIC_ASSETS = [
  "/static/css/style.css",
  "/static/js/main.js",
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

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return resp;
      });
    })
  );
});
