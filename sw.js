const CACHE_NAME = 'planly-v202606010839'; // mis à jour automatiquement par inject_pois.py

self.addEventListener('install', function(e) {
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE_NAME; })
             .map(function(n) { return caches.delete(n); })
      );
    }).then(function() { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function(e) {
  var url = e.request.url;
  // Images locales : cache-first (invalidé par CACHE_NAME à chaque deploy)
  if (url.includes('planly_scraper/images/')) {
    e.respondWith(
      caches.match(e.request).then(function(cached) {
        if (cached) return cached;
        return fetch(e.request).then(function(resp) {
          if (resp.ok) {
            var clone = resp.clone();
            caches.open(CACHE_NAME).then(function(c) { c.put(e.request, clone); });
          }
          return resp;
        });
      })
    );
  } else {
    // Network-first pour HTML, JS, etc.
    e.respondWith(
      fetch(e.request).catch(function() { return caches.match(e.request); })
    );
  }
});
