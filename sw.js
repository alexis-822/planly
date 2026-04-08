const CACHE_NAME = 'planly-v8';

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
    }).then(function() { return clients.claim(); })
  );
});

self.addEventListener('fetch', function(e) {
  var url = e.request.url;
  // Cache images agressivement
  if (url.match(/\.(jpg|jpeg|png|webp)$/i)) {
    e.respondWith(
      caches.match(e.request).then(function(cached) {
        if (cached) return cached;
        return fetch(e.request).then(function(resp) {
          var clone = resp.clone();
          caches.open(CACHE_NAME).then(function(c) { c.put(e.request, clone); });
          return resp;
        });
      })
    );
  } else {
    // Network first pour le HTML/JS
    e.respondWith(
      fetch(e.request).catch(function() { return caches.match(e.request); })
    );
  }
});
