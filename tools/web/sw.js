const CACHE = "hap-revival-v1";
const ASSETS = [
  "/pwa/icon-192.png", "/pwa/icon-512.png",
  "/pwa/icon-maskable-512.png", "/pwa/apple-touch-icon.png",
  "/manifest.webmanifest"
];
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;  // never cache device state
  if (url.pathname.startsWith("/pwa/") || url.pathname === "/manifest.webmanifest") {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
