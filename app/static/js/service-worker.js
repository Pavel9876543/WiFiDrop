const CACHE_PREFIX = "wifidrop-shell-";

self.addEventListener("install", () => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((names) => Promise.all(
                names.filter((name) => name.startsWith(CACHE_PREFIX)).map((name) => caches.delete(name)),
            ))
            .then(() => self.clients.claim()),
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    // WiFiDrop работает только при доступном локальном сервере, поэтому
    // HTML/CSS/JS всегда берём с сервера. Так разные версии фронтенда
    // никогда не смешиваются из старого PWA-кэша.
    event.respondWith(fetch(request));
});
