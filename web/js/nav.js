// Sections du tableau de bord : UNE liste, partagée par index.html (app.js) et chat.html
// (chat.js) — la page Coach recopiait la sienne et ratait chaque nouvelle section.

// `roadbook` : entrée « Roadbook » juste avant Trail Shape, seulement quand un plan de course
// existe pour la prochaine course (`/api/summary.next_race_plan`, #187).
export function navItems(settings, { roadbook = false } = {}) {
  const nutrition = settings?.agents?.includes("nutritionist");
  return [
    ["", "Aujourd'hui"], ["forme", "Forme & charge"], ["analyse", "Analyse"], ["sante", "Santé"], ["semaine", "Semaine"],
    ["seances", "Séances"], ["performance", "Performance"], ["materiel", "Matériel"], ...(roadbook ? [["roadbook", "Roadbook"]] : []), ["trail-shape", "Trail Shape"], ["calendrier", "Calendrier"],
    ["decisions", "Décisions"], ["rapports", "Rapports"], ...(nutrition ? [["nutrition", "Nutrition"]] : []),
    ["hypotheses", "Hypothèses"], ["synchro", "Synchro"],
  ];
}

// Version du moteur sous le nom, dans l'en-tête des deux pages, et pastille « nouvelle version »
// quand une release plus récente existe (`arc_update_check.py`, vérifiée au plus une fois par
// jour côté serveur). Absente (`null`) ou serveur plus ancien sans `/api/version` : rien n'est affiché.
export async function showVersion() {
  const box = document.getElementById("version");
  if (!box) return;
  try {
    const res = await fetch("api/version", { headers: { Accept: "application/json" } });
    const { version, update } = res.ok ? await res.json() : {};
    if (version) {
      box.textContent = version;
      box.hidden = false;
    }
    const pill = document.getElementById("update");
    if (pill && update && update.latest) {
      pill.href = update.url;
      pill.title = `Notes de version ${update.latest} — pour mettre à jour : ${update.command} dans votre assistant, ou scripts/update-coach.sh`;
      pill.replaceChildren(update.latest, Object.assign(document.createElement("span"),
        { className: "update-pill__long", textContent: " disponible" }));
      pill.hidden = false;
    }
  } catch { /* information de confort : jamais bloquante */ }
}

// Pastille « synchro » de l'en-tête (`/api/sync-status`) : n'apparaît que si la synchronisation
// automatique demande de l'attention (en retard, en échec, Garmin injoignable) ; renvoie vers la
// vue Synchro. Serveur plus ancien sans cette route : rien n'est affiché.
const SYNC_ALERT = { late: "Synchro en retard", failing: "Synchro en échec", degraded: "Synchro dégradée" };
export async function showSyncPill() {
  const pill = document.getElementById("sync-pill");
  if (!pill) return;
  try {
    const res = await fetch("api/sync-status", { headers: { Accept: "application/json" } });
    const st = res.ok ? await res.json() : {};
    if (!SYNC_ALERT[st.verdict]) return;
    pill.textContent = SYNC_ALERT[st.verdict];
    pill.title = st.reason || "";
    pill.hidden = false;
  } catch { /* information de confort : jamais bloquante */ }
}
