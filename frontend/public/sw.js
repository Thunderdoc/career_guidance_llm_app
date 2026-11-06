/* Career Guidance AI service worker (Phase 8, v4).
 *
 * Caching rules, exactly as shipped:
 *   • Install: precache the offline fallback, icons and manifest
 *     (all-or-nothing), plus the app-shell entry pages `/` and `/explore`
 *     (best-effort — a shell page failing to precache must not kill the
 *     worker; the navigation handler below caches them at runtime too).
 *   • /_next/static/**, icons, fonts and images → cache-first (hashed /
 *     immutable assets), populated at runtime.
 *   • Navigations → network-first; a successful response is stored in the
 *     shell cache, and offline a navigation falls back to its cached copy,
 *     finally to /sw-offline.html (a dependency-free static file — NOT the
 *     /offline React route, whose exported offline.html would need the JS
 *     bundle; the two files' wording is kept in sync by hand).
 *   • /api/** → NEVER cached, never replayed: recommendations, profiles,
 *     shared reports and résumés are per-account (or per-token) data and
 *     must always come from the server (or fail visibly). Non-GET requests
 *     and cross-origin requests are left completely alone.
 *   • Updates: the worker does NOT skipWaiting on install. When a new
 *     version is installed alongside an old controller it waits; the page
 *     (components/pwa-register.tsx) shows an "update available" toast and
 *     posts {type: "SKIP_WAITING"} only when the user accepts the reload.
 *     A first install (no existing controller) activates immediately.
 */

const VERSION = "cg-v4";
const SHELL_CACHE = `${VERSION}-shell`;
const STATIC_CACHE = `${VERSION}-static`;
const OFFLINE_URL = "/sw-offline.html";
const PRECACHE_CRITICAL = [
  OFFLINE_URL,
  "/icon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/manifest.webmanifest",
];
const PRECACHE_SHELL = ["/", "/explore"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_CRITICAL))
      .then(() => caches.open(SHELL_CACHE))
      .then((cache) =>
        Promise.all(PRECACHE_SHELL.map((url) => cache.add(url).catch(() => undefined))),
      ),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Personal / per-token data — straight to the network, never cached.
  if (url.pathname.startsWith("/api/")) return;

  if (url.pathname.startsWith("/_next/static/") || /\.(png|svg|webp|woff2?|ico)$/.test(url.pathname)) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() =>
          caches
            .match(request)
            .then((hit) => hit || caches.match(OFFLINE_URL))
            .then((hit) => hit || Response.error()),
        ),
    );
  }
});
