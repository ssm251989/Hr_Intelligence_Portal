// Part 14 section 10: service-worker registration (production builds only -- the Vite dev
// server must never be cached) and the logout hook that wipes the offline "me" cache.

export function registerServiceWorker(): void {
  if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}

export function clearOfflineData(): void {
  if ("serviceWorker" in navigator && navigator.serviceWorker.controller) {
    navigator.serviceWorker.controller.postMessage({ type: "logout" });
  }
}
