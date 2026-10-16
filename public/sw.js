// Only the service-stopped page is cached. Research and tracker requests always
// go directly to the local service; writes are never queued or replayed.
const CACHE = 'deck-recovery-v2';
const FALLBACK = '/offline.html';

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add(new Request(FALLBACK, { cache: 'reload' }))));
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => (name.startsWith('kalshi-deck-recovery-') || name.startsWith('deck-recovery-')) && name !== CACHE).map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || event.request.mode !== 'navigate'
      || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  event.respondWith((async () => {
    try {
      return await fetch(event.request);
    } catch {
      const cache = await caches.open(CACHE);
      return await cache.match(FALLBACK) ?? new Response('Reconnect to Deck and reload. For local installations, run bash scripts/start.sh.', {
        status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      });
    }
  })());
});
