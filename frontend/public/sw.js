/* LivePaste service worker — offline-first app shell + paste cache.
 *
 * Strategy:
 *   - App shell (/, /assets/*):        cache-first, revalidate in background
 *   - GET /api/paste/*:                network-first, cached copy as fallback
 *   - other GET /api/*:                network-first, cache fallback
 *   - POST/PUT/DELETE, WebSocket:      never intercepted
 *
 * Bump CACHE_VERSION to invalidate everything.
 */
const CACHE_VERSION = "lp-v3.18.0";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
const DATA_CACHE = `${CACHE_VERSION}-data`;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(["/", "/manifest.webmanifest"])),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => !k.startsWith(CACHE_VERSION)).map((k) => caches.delete(k)),
      );
      await self.clients.claim();
    })(),
  );
});

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const fresh = await fetch(request);
    if (fresh && fresh.ok) cache.put(request, fresh.clone());
    return fresh;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirstRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const refresh = fetch(request)
    .then((fresh) => {
      if (fresh && fresh.ok) cache.put(request, fresh.clone());
      return fresh;
    })
    .catch(() => undefined);
  if (cached) return cached;
  const fresh = await refresh;
  if (fresh) return fresh;
  throw new Error("offline and not cached");
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return; // writes never intercepted
  const url = new URL(request.url);
  if (url.protocol !== "http:" && url.protocol !== "https:") return;

  // App shell: root, SPA routes (no extension), built assets
  const isAsset = url.pathname.startsWith("/assets/") || url.pathname === "/manifest.webmanifest";
  const isSpaRoute =
    url.pathname === "/" ||
    (!url.pathname.startsWith("/api/") && !url.pathname.includes(".") && request.headers.get("accept")?.includes("text/html"));

  if (isAsset || isSpaRoute) {
    event.respondWith(cacheFirstRevalidate(request, SHELL_CACHE));
    return;
  }

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      networkFirst(request, DATA_CACHE).catch(
        () =>
          new Response(
            JSON.stringify({ detail: "You are offline — showing the last cached state." }),
            { status: 503, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
  }
  // everything else: browser default
});
