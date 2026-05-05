const CACHE_NAME = "ambifo-crm-v3";
const APP_SHELL = [
  "/",
  "/login",
  "/static/css/styles.css",
  "/static/ambifologo.png",
  "/manifest.webmanifest"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).catch(() => Promise.resolve())
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") {
    return;
  }

  const url = new URL(req.url);
  const isSameOrigin = url.origin === self.location.origin;
  const isStaticAsset = isSameOrigin && url.pathname.startsWith("/static/");
  const isAppShellAsset = isSameOrigin && (url.pathname === "/" || url.pathname === "/login" || url.pathname === "/manifest.webmanifest");

  // Cache only static/app-shell resources. Keep dynamic pages/API network-first without SW cache writes.
  if (!isStaticAsset && !isAppShellAsset) {
    event.respondWith(fetch(req));
    return;
  }

  event.respondWith(
    fetch(req)
      .then((response) => {
        if (!response || response.status !== 200) {
          return response;
        }
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        return response;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match("/login")))
  );
});
