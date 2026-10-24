# Nouveautés

Ce qui s'est ajouté depuis la version 1.3.0, par thème. Chaque point renvoie à sa page de détail.
Pour mettre à jour une installation existante : [Passer de la 1.3 à la 1.4](update.md#passer-de-la-13-a-la-14).

## Sources de données

- **COROS, source complète.** `./install.sh --source coros` en fait votre source de données, comme Garmin :
  activités et FIT, bilan matinal (HRV, FC de repos, récupération COROS toujours nommée ainsi), séances envoyées à
  la montre, surveillance. `./install.sh --coros` branche la montre à côté d'une autre source. Une seule connexion
  (`python3 scripts/arc_coros_auth.py login`) pour toutes les IA. Voir [Montres COROS](coros.md).
- **Fiche Pace Strategy.** Pour une course, `scripts/arc_coros_workout.py pace-strategy` prépare la fiche à recopier
  dans l'app COROS (le MCP n'a aucun outil de parcours). Voir [Montres COROS](coros.md) et [Planification COROS](skills/coros-workout-scheduling.md).
- **Splits par km pour toutes les sources.** `python3 scripts/arc_index.py splits <id>` les calcule depuis le FIT,
  de la même façon avec Garmin, COROS, Intervals.icu ou Strava.
- **Surveillance sans LLM.** `scripts/watch.py` (ex-`garmin_watch.py`) sonde Garmin ou COROS et ne lance la
  synchronisation que s'il y a du neuf. Voir [Le coach dans la poche](mobile.md).

## Choisir son IA

- **OpenRouter en un clic**, sans clé à copier (`./install.sh --llm openrouter --connect`), et **essai gratuit**
  limité avec des modèles `:free` (`--llm openrouter-free`, confidentialité dite honnêtement).
- **Abonnements ChatGPT Plus/Pro et GitHub Copilot** : `--llm chatgpt` ou `--llm copilot`, sans clé API ;
  la synchronisation n'y passe qu'avec votre accord (`--sync-subscription`).
- **Changer la synchronisation seule** : `python3 scripts/arc_llm.py sync …` ; **tester la connexion** :
  `python3 scripts/arc_llm.py check` ou le bouton « Tester la connexion » de l'application et du chat.
  Voir [Choisir son IA](choisir-son-ia.md).

## Chaussures

- **Épopée chaussures.** Fiche de caractéristiques sourcée de chaque paire, retours de chaussant saisis avec `/log`,
  profil d'usage, besoins pour la prochaine paire, puis `/shoes` pour choisir. Une paire retirée dans Garmin est
  retirée immédiatement du suivi. Voir [Choisir ses chaussures](shoes.md), [Fiche des chaussures](skills/shoe-specs.md),
  [Choisir une paire (/shoes)](skills/shoes.md) et [Choix des chaussures](skills/shoe-selection.md).

## Export vers l'Apple Watch

- **Export Vanoor (opt-in).** Avec `[vanoor].export = "on"`, les séances de course de la semaine et le plan de
  course sont écrits au format de l'app Vanoor, prêts à importer : un export, pas un push. Voir
  [Export Vanoor](skills/vanoor-export.md) et [Apple Watch](apple-watch.md).

## Plusieurs athlètes sur une machine

- **Un workspace par athlète**, avec ses jetons Garmin (`--garmin-tokens`), ses identifiants intervals.icu
  (`--intervals-dir`) et sa propre planification de synchronisation ; `--replace-schedule` pour migrer la
  planification de la racine du moteur. Voir [Votre workspace privé](workspace.md#plusieurs-workspaces-et-plusieurs-athletes).
- **Migration d'une installation existante** : `scripts/migrate-sync-127.sh` (sans doubler ni arrêter la
  synchronisation). Voir [Mettre à jour](update.md).
- **Mode famille** : un seul tableau de bord et un seul chat pour plusieurs athlètes. Voir [Mode famille](family.md).

## Tableau de bord

- **Le design « roadbook » devient le design par défaut** (l'ancien reste accessible avec `?design=classic`
  jusqu'à la 1.5). Voir [Tableau de bord](dashboard/index.md) et [Les vues](dashboard/views.md).
- **Application installable (PWA)**, polices embarquées, semaine avec appariement planifié ↔ réalisé.
- **Image Docker publiée sur GHCR** (`:latest`, `:edge`, `:X.Y.Z`). Voir [Docker](dashboard/docker.md#images-publiees-ghcr).

## Mettre à jour

Rien à migrer à la main pour la plupart des installations : [Passer de la 1.3 à la 1.4](update.md#passer-de-la-13-a-la-14).
