/* HRMS service worker (docs/HRMS_COMPLETE_SPEC.txt Part 14 section 10; decision L5 "PWA,
 * no native apps"): installable app shell, offline read of the signed-in user's OWN letters
 * and documents, and push/in-app notification display.
 *
 * Privacy: only the two "me" endpoints are cached (never lists of other people), the cache
 * is wiped on logout (the app posts {type: "logout"}), and nothing is cached for requests
 * that fail. */

const SHELL_CACHE = "hrms-shell-v1";
const DATA_CACHE = "hrms-me-v1";
const SHELL = ["/", "/index.html", "/favicon.svg", "/manifest.webmanifest"];
const OFFLINE_READ = [/\/api\/v1\/me\/letters$/, /\/api\/v1\/me\/documents$/];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => ![SHELL_CACHE, DATA_CACHE].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "logout") {
    event.waitUntil(caches.delete(DATA_CACHE));
  }
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  if (OFFLINE_READ.some((re) => re.test(url.pathname))) {
    // network-first; fall back to the last copy when offline
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(DATA_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request).then((hit) => hit || new Response(JSON.stringify([]), { headers: { "Content-Type": "application/json" } }))),
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/index.html")));
    return;
  }

  if (url.origin === self.location.origin && url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })),
    );
  }
});

self.addEventListener("push", (event) => {
  let payload = { title: "Notification", body: "", url: "/" };
  try {
    payload = { ...payload, ...event.data.json() };
  } catch (e) {
    /* plain-text push */
  }
  event.waitUntil(self.registration.showNotification(payload.title, { body: payload.body, data: { url: payload.url }, icon: "/favicon.svg" }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => w.url.includes(self.location.origin));
      return open ? open.focus().then((w) => w.navigate(target)) : self.clients.openWindow(target);
    }),
  );
});
