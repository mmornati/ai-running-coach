// Service worker du tableau de bord (PWA) : la COQUE de l'application, jamais les données.
//
// - `/api/…` et `/media/…` (santé, séances, photos) ne passent jamais par le cache : réseau seul.
// - Coque (pages, CSS, JS, polices, icônes) : réseau d'abord, toujours ; le cache ne sert que hors ligne.
//   Une mise à jour du moteur est donc visible au rechargement suivant, sans version à gérer.
// - Derrière un proxy qui authentifie (Authentik, déploiement serveur) : une réponse redirigée,
//   opaque ou en erreur n'est jamais mise en cache — on ne garde pas une page de connexion
//   à la place de l'application.
const CACHE = "arc-shell-v3";
const SHELL = [
  "./", "index.html", "chat.html", "manifest.webmanifest", "favicon.svg",
  "css/app.css", "css/chat.css", "css/beta.css", "css/fonts.css",
  "fonts/inter-latin-var.woff2", "fonts/sora-latin-var.woff2",
  "fonts/barlow-condensed-latin-500.woff2", "fonts/barlow-condensed-latin-600.woff2",
  "fonts/barlow-condensed-latin-700.woff2",
  "js/early.js", "js/app.js", "js/beta.js", "js/chat.js", "js/chart.js", "js/format.js",
  "js/map.js", "js/nav.js", "js/roadbook.js",
  "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png", "icons/apple-touch-icon.png",
];

const isData = (url) => /^\/(api|media)\//.test(url.pathname);
const cacheable = (res) => res && res.ok && !res.redirected && res.type === "basic";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // Un fichier manquant ne doit pas faire échouer l'installation entière.
    await Promise.all(SHELL.map(async (path) => {
      try {
        const res = await fetch(path, { cache: "no-cache", credentials: "same-origin" });
        if (cacheable(res)) await cache.put(path, res);
      } catch { /* hors ligne à l'installation : la coque se remplira au fil des visites */ }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k.startsWith("arc-shell-") && k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || isData(url)) return;   // réseau seul, navigateur par défaut
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const res = await fetch(req);
      if (cacheable(res)) cache.put(req, res.clone());
      return res;
    } catch (err) {
      const hit = await cache.match(req, { ignoreSearch: req.mode === "navigate" });
      if (hit) return hit;
      if (req.mode === "navigate") {
        const page = await cache.match(url.pathname.endsWith("chat.html") ? "chat.html" : "index.html");
        if (page) return page;
      }
      throw err;
    }
  })());
});
