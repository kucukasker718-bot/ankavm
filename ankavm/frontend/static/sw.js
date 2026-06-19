/* ankavm Service Worker
 * Strategy:
 *  - Static assets (JS/CSS/img/fonts): cache-first
 *  - API requests: network-only (never cache, always fresh)
 *  - HTML navigation: network-first with offline fallback
 */

const CACHE_VERSION = "ankavm-v2.5.3";
const STATIC_CACHE  = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

const STATIC_ASSETS = [
  "/static/manifest.json",
  "/static/img/sadeceikon.png",
  "/static/xterm.min.css",
  "/static/xterm.min.js",
  "/static/addon-fit.min.js",
  "/static/chart.umd.min.js",
  "/static/socket.io.min.js",
];

// â”€â”€ Install: precache static â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(STATIC_ASSETS).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

// â”€â”€ Activate: cleanup old caches â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => !k.startsWith(CACHE_VERSION))
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// â”€â”€ Fetch: route by request type â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Only GET
  if (request.method !== "GET") return;
  // Same origin only
  if (url.origin !== self.location.origin) return;

  // API: network-only (never cache live data)
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/socket.io/")) {
    return; // browser handles
  }

  // Static assets: cache-first
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((resp) => {
          if (resp && resp.status === 200) {
            const copy = resp.clone();
            caches.open(RUNTIME_CACHE).then((c) => c.put(request, copy));
          }
          return resp;
        }).catch(() => cached);
      })
    );
    return;
  }

  // HTML navigation: network-first, fallback to cache
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).then((resp) => {
        if (resp && resp.status === 200) {
          const copy = resp.clone();
          caches.open(RUNTIME_CACHE).then((c) => c.put(request, copy));
        }
        return resp;
      }).catch(() => caches.match(request).then((c) => c || caches.match("/")))
    );
  }
});

// â”€â”€ Push notifications (opsiyonel) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
self.addEventListener("push", (event) => {
  try {
    const data = event.data ? event.data.json() : {};
    const title = data.title || "ankavm";
    const opts  = {
      body: data.body || "",
      icon: "/static/img/sadeceikon.png",
      badge: "/static/img/sadeceikon.png",
      tag:  data.tag || "ankavm-notification",
      data: data.url || "/",
    };
    event.waitUntil(self.registration.showNotification(title, opts));
  } catch (_) {}
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((clients) => {
      for (const c of clients) {
        if (c.url.includes(url) && "focus" in c) return c.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});






