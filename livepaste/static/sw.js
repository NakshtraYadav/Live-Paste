/* Cache only the versioned app shell. Private document state lives in Yjs
 * IndexedDB, never in a URL-only HTTP cache that bypasses password/expiry. */
const CACHE_VERSION = "lp-v4.0.0";
const SHELL_CACHE = `${CACHE_VERSION}-shell`;
self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    await cache.addAll(["/", "/manifest.webmanifest", "/favicon.svg", "/error-guard.js", "/runner-javascript.js", "/runner-python.js"]);
    const html = await (await cache.match("/")).text();
    const assets = [...html.matchAll(/(?:src|href)=["']([^"']+)["']/g)]
      .map(match => new URL(match[1], self.location.origin))
      .filter(url => url.origin === self.location.origin && url.pathname.startsWith("/assets/"));
    await cache.addAll(assets.map(url => url.href));
    await self.skipWaiting();
  })());
});
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith("lp-v") && key !== SHELL_CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (request.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      try {
        const response = await fetch(request);
        if (response.ok && response.headers.get("content-type")?.includes("text/html")) await cache.put("/", response.clone());
        return response;
      } catch {
        return (await cache.match("/")) || new Response("The app shell is not cached yet.", { status: 503 });
      }
    })());
  } else if (url.pathname.startsWith("/assets/") || ["/favicon.svg", "/error-guard.js", "/manifest.webmanifest", "/runner-javascript.js", "/runner-python.js"].includes(url.pathname)) {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      if (response.ok) await cache.put(request, response.clone());
      return response;
    })());
  }
});
