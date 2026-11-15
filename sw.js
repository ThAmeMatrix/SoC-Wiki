/* Service worker for the hosted (GitHub Pages) copy of the archive.
 *
 * GitHub Pages serves every file with a 10-minute cache lifetime, so a repeat
 * visit re-validates hundreds of images. Image / font / icon files under
 * assets/ are content-addressed (hash file names) or practically immutable, so
 * they are served cache-first; files without a hash name are refreshed in the
 * background. HTML, scripts, styles and data are NOT intercepted — the browser
 * cache and ETag revalidation keep them fresh after every site update.
 * The offline file:// build never registers this worker.
 */
'use strict';
const ASSET_CACHE = 'socwiki-assets-v1';
const HASHED = /\/(?:[0-9a-f]{16,}|range-[0-9a-f]+|sprite-[0-9a-f]+)\.(?:webp|png|jpe?g|gif|svg)$/i;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) if (name.startsWith('socwiki-') && name !== ASSET_CACHE) await caches.delete(name);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET' || req.headers.has('range')) return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || !url.pathname.includes('/assets/')) return;
  event.respondWith((async () => {
    const cache = await caches.open(ASSET_CACHE);
    const hit = await cache.match(req);
    const refresh = fetch(req).then(res => {
      if (res.ok && res.type === 'basic') cache.put(req, res.clone()).catch(() => {});
      return res;
    });
    if (hit) {
      if (!HASHED.test(url.pathname)) event.waitUntil(refresh.catch(() => {}));
      return hit;
    }
    return refresh;
  })());
});
