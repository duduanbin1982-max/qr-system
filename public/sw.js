// Service Worker cache revision is independent from the application version.
const CACHE_REVISION = "20260829.2";
const CACHE_NAME = "qr-system-cache-" + CACHE_REVISION;
// Pre-cache only immutable/large assets (NOT HTML)
const ASSETS = [
  "/offline.html",
  "/jsQR.js",
  "/style.css",
  "/css/mobile.css?v=19",
  "/css/inspection.css?v=3",
  "/js/mobile/mobile-api.js?v=9",
  "/js/mobile/mobile-utils.js?v=31",
  "/js/mobile/mobile-auth.js?v=31",
  "/js/mobile/mobile-scan.js?v=27",
  "/js/mobile/mobile-order.js?v=43",
  "/js/mobile/mobile-quality-evaluation.js?v=8",
  "/js/mobile/mobile-init.js?v=36",
  "/js/mobile/inspection.js?v=9",
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

  // API: network-only
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(event.request).catch(function() {
        return new Response(JSON.stringify({
          error: "当前离线，业务提交未保存，请恢复网络后重新提交",
          code: "offline",
          action: "retry_online",
          offline: true
        }), {
          status: 503,
          headers: {"Content-Type": "application/json"}
        });
      })
    );
    return;
  }

  // HTML: network-first (never serve stale HTML)
  if (event.request.mode === "navigate" || url.pathname.endsWith(".html")) {
    event.respondWith(
      fetch(event.request).then(function(response) {
        var clone = response.clone();
        caches.open(CACHE_NAME).then(function(cache) {
          cache.put(event.request, clone);
        });
        return response;
      }).catch(function() {
        return caches.match(event.request).then(function(cached) {
          return cached || caches.match("/offline.html");
        });
      })
    );
    return;
  }

  // Mobile business JS: network-first to avoid stale scan/report logic
  if (url.pathname.startsWith("/js/mobile/")) {
    event.respondWith(
      fetch(event.request).then(function(response) {
        if (response && response.status === 200) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, clone);
          });
        }
        return response;
      }).catch(function() {
        return caches.match(event.request);
      })
    );
    return;
  }

  // Static assets (JS/CSS/images): cache-first, network update in background
  event.respondWith(
    caches.match(event.request).then(function(cached) {
      var fetchPromise = fetch(event.request).then(function(response) {
        if (response && response.status === 200) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, clone);
          });
        }
        return response;
      }).catch(function() {});
      
      return cached || fetchPromise;
    })
  );
});
