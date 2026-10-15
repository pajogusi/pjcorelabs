const CACHE = 'blessed-offline-v5';
const STATIC = [
  '/static/style.css',
  '/static/sidebar.css',
  '/static/marcacao.css',
  '/static/agenda-offline.js',
  '/static/offline-bookings.js',
  '/static/blessed-diagnostico.js',
  '/static/clientes-offline.js',
  '/static/clientes-marcacao.js'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(STATIC).catch(() => {})));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname === '/logout') {
    event.respondWith(fetch(req).then(resp => {
      caches.delete(CACHE);
      return resp;
    }));
    return;
  }

  if (req.method !== 'GET') return;

  if (req.mode === 'navigate' && url.pathname === '/semana') {
    event.respondWith(
      fetch(req).then(resp => {
        if (resp.ok) {
          const copia = resp.clone();
          caches.open(CACHE).then(cache => cache.put(req, copia));
        }
        return resp;
      }).catch(async () => {
        const cache = await caches.open(CACHE);
        return (await cache.match(req)) ||
               (await cache.match('/semana')) ||
               new Response('Blessed offline: abre a agenda uma vez com internet antes de a usar offline.', {
                 status: 503,
                 headers: {'Content-Type': 'text/plain; charset=utf-8'}
               });
      })
    );
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      fetch(req).then(resp => {
        if (resp.ok) caches.open(CACHE).then(cache => cache.put(req, resp.clone()));
        return resp;
      }).catch(async () => {
        const cache = await caches.open(CACHE);
        return (await cache.match(req)) ||
               (await cache.match(url.pathname)) ||
               Response.error();
      }))
    );
  }
});