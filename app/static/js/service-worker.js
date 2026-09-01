const CACHE_NAME = "wifidrop-shell-v11";
const APP_SHELL = [
    "/",
    "/static/manifest.webmanifest",
    "/static/css/theme.css",
    "/static/css/base.css",
    "/static/css/components.css",
    "/static/css/animations.css",
    "/static/css/desktop.css",
    "/static/css/tablet.css",
    "/static/css/mobile.css",
    "/static/js/app.js",
    "/static/js/browser-launch.js",
    "/static/js/connection.js",
    "/static/js/drop-zone.js",
    "/static/js/file-list.js",
    "/static/js/notifications.js",
    "/static/js/pwa.js",
    "/static/js/queue-state.js",
    "/static/js/theme.js",
    "/static/js/uploader.js",
    "/static/js/utils.js",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(APP_SHELL))
            .then(() => self.skipWaiting()),
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((names) => Promise.all(
                names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name)),
            ))
            .then(() => self.clients.claim()),
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (request.mode === "navigate") {
        event.respondWith(networkFirst(request, "/"));
        return;
    }

    if (url.pathname.startsWith("/static/")) {
        event.respondWith(networkFirst(request));
    }
});

async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) return cached;

    const response = await fetch(request);
    if (response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put(request, response.clone());
    }
    return response;
}

async function networkFirst(request, fallbackUrl) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(CACHE_NAME);
            await cache.put(request, response.clone());
        }
        return response;
    } catch {
        return (await caches.match(request)) || (await caches.match(fallbackUrl));
    }
}
