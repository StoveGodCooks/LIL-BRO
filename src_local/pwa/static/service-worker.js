"use strict";

const CACHE = "lilbro-shell-v1";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/manifest.webmanifest",
  "/static/icon.svg",
];

self.addEventListener("install", (ev) => {
  ev.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (ev) => {
  ev.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (ev) => {
  const url = new URL(ev.request.url);
  // Network-first for API endpoints (fresh data), cache-first for the shell.
  if (url.pathname.startsWith("/api/")) {
    ev.respondWith(fetch(ev.request).catch(() =>
      new Response(JSON.stringify({ error: "offline" }), {
        headers: { "Content-Type": "application/json" },
      }),
    ));
    return;
  }
  ev.respondWith(
    caches.match(ev.request).then((cached) =>
      cached || fetch(ev.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(ev.request, copy)).catch(() => {});
        return resp;
      }).catch(() => caches.match("/")),
    ),
  );
});
