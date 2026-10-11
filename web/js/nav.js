// Sections du tableau de bord : UNE liste, partagée par index.html (app.js) et chat.html
// (chat.js) — la page Coach recopiait la sienne et ratait chaque nouvelle section.

export function navItems(settings) {
  const nutrition = settings?.agents?.includes("nutritionist");
  return [
    ["", "Aujourd'hui"], ["forme", "Forme & charge"], ["analyse", "Analyse"], ["sante", "Santé"], ["semaine", "Semaine"],
    ["seances", "Séances"], ["performance", "Performance"], ["materiel", "Matériel"], ["trail-shape", "Trail Shape"], ["calendrier", "Calendrier"],
    ["decisions", "Décisions"], ["rapports", "Rapports"], ...(nutrition ? [["nutrition", "Nutrition"]] : []),
    ["hypotheses", "Hypothèses"],
  ];
}

// Version du moteur sous le nom, dans l'en-tête des deux pages. Absente (`null`) ou
// serveur plus ancien sans `/api/version` : rien n'est affiché.
export async function showVersion() {
  const box = document.getElementById("version");
  if (!box) return;
  try {
    const res = await fetch("api/version", { headers: { Accept: "application/json" } });
    const { version } = res.ok ? await res.json() : {};
    if (!version) return;
    box.textContent = version;
    box.hidden = false;
  } catch { /* information de confort : jamais bloquante */ }
}
