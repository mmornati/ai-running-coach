// Chargé en script classique dans le <head> de chaque page, AVANT le premier rendu (la CSP
// interdit le script en ligne) : choisit le design et enregistre le service worker de la PWA.
//
// Design : le « roadbook » est le design par défaut (v1.4). L'ancien design reste joignable
// jusqu'à la 1.5 par `?design=classic`, mémorisé par navigateur (`localStorage`, clé
// `arc-design-v14`, qui ne stocke QUE ce choix explicite). `?design=roadbook` (ou l'ancien
// `?design=beta`) revient au défaut et efface le choix. La clé `arc-design` de la période
// d'essai est supprimée : tout le monde passe au roadbook. Le paramètre est retiré de l'URL
// aussitôt lu. Sans stockage (navigation privée), le paramètre vaut pour la page courante.
// Toutes les règles du roadbook sont portées par `[data-design="roadbook"]`.
(function () {
  var KEY = "arc-design-v14";
  var OLD_KEY = "arc-design";
  var root = document.documentElement;
  var url = new URL(location.href);
  var asked = url.searchParams.get("design");
  var known = asked === "classic" || asked === "roadbook" || asked === "beta";
  var classic = false;
  try {
    localStorage.removeItem(OLD_KEY);
    if (asked === "classic") localStorage.setItem(KEY, "classic");
    else if (known) localStorage.removeItem(KEY);
    classic = localStorage.getItem(KEY) === "classic";
  } catch (e) { /* stockage indisponible : le paramètre seul décide */ }
  if (known) {
    classic = asked === "classic";
    url.searchParams.delete("design");
    history.replaceState(history.state, "", url.pathname + url.search + url.hash);
  }
  if (!classic) root.dataset.design = "roadbook";

  // Service worker : coque de l'application seulement (HTML, CSS, JS, icônes), jamais les
  // données (`/api/`, `/media/`). Contexte sécurisé obligatoire : 127.0.0.1 / localhost, ou
  // HTTPS derrière le reverse proxy du déploiement serveur.
  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function () { /* PWA indisponible : la page marche sans */ });
    });
  }
})();
