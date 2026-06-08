// Service Worker - QR System PWA v2 (enhanced)
const CACHE_NAME = "qr-system-v2.1";
const ASSETS = [
  "/mobile.html",
  "/offline.html",
  "/jsQR.js",
  "/style.css",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(ASSETS);
    }).then(function() {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function(event) {
  event.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) { return k !== CACHE_NAME; })
            .map(function(k) { return caches.delete(k); })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function(event) {
  var url = new URL(event.request.url);

  // API: network-first with offline queue
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(event.request).catch(function() {
        return new Response(JSON.stringify({error: "offline", offline: true}), {
          status: 503,
          headers: {"Content-Type": "application/json"}
        });
      })
    );
    return;
  }

  // Static: cache-first, fallback to offline page
  event.respondWith(
    caches.match(event.request).then(function(cached) {
      if (cached) return cached;
      return fetch(event.request).then(function(response) {
        if (response && response.status === 200) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, clone);
          });
        }
        return response;
      }).catch(function() {
        if (event.request.mode === "navigate") {
          return caches.match("/offline.html");
        }
        return new Response("Offline", {status: 503});
      });
    })
  );
});
