"use strict";
const VERSION = "v1.0.0";
const PREFIX = `lowfly:${new URL(self.registration.scope).pathname}:`;
const SHELL_CACHE = PREFIX + "shell-" + VERSION;
const DATA_CACHE = PREFIX + "data-" + VERSION;
const SHELL = ["./", "./index.html", "./style.css", "./config.js", "./utils.js", "./app.js",
  "./manifest.webmanifest", "./icons/icon.svg", "./icons/icon-192.png", "./icons/icon-512.png"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(SHELL_CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith(PREFIX) && ![SHELL_CACHE, DATA_CACHE].includes(key)).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || !url.href.startsWith(self.registration.scope)) return;
  const relative = url.pathname.slice(new URL(self.registration.scope).pathname.length);
  if (/^data\/(summary|pairs|history|alerts)\.json$/.test(relative)) {
    event.respondWith((async () => {
      const cache = await caches.open(DATA_CACHE);
      try {
        const response = await fetch(request, {signal: AbortSignal.timeout(10000)});
        if (!response.ok) throw new Error("資料請求失敗");
        await response.clone().json();
        await cache.put(request, response.clone());
        return response;
      } catch {
        const saved = await cache.match(request);
        if (!saved) return new Response(JSON.stringify({error:"尚無離線資料"}), {status:503, headers:{"Content-Type":"application/json"}});
        const headers = new Headers(saved.headers);
        headers.set("X-LowFly-Cache", "offline");
        return new Response(await saved.arrayBuffer(), {status:200, headers});
      }
    })());
  } else if (SHELL.some(path => new URL(path, self.registration.scope).pathname === url.pathname) || request.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      const saved = await cache.match(request);
      if (saved) return saved;
      try {
        const response = await fetch(request);
        if (response.ok) await cache.put(request, response.clone());
        return response;
      } catch {
        return await cache.match(new URL("./index.html", self.registration.scope).href) || Response.error();
      }
    })());
  }
});
