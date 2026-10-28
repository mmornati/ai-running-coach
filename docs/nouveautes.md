# Nouveautés

Ce qui s'est ajouté depuis la version 1.3.0, par thème. Chaque point renvoie à sa page de détail.
Pour mettre à jour une installation existante : [Passer de la 1.3 à la 1.4](update.md#passer-de-la-13-a-la-14).

## Sources de données

- **COROS, source complète.** `./install.sh --source coros` en fait votre source de données, comme Garmin :
  activités et FIT, bilan matinal (HRV, FC de repos, récupération COROS toujours nommée ainsi), séances envoyées à
  la montre, surveillance. `./install.sh --coros` branche la montre à côté d'une autre source. Une seule connexion
  (`python3 scripts/arc_coros_auth.py login`) pour toutes les IA. Voir [Montres COROS](coros.md).
- **Fiche Pace Strategy.** Pour une course, `python3 scripts/arc_coros_workout.py pace-strategy` prépare la fiche à recopier
  dans l'app COROS (le MCP n'a aucun outil de parcours). Voir [Montres COROS](coros.md) et [Planification COROS](skills/coros-workout-scheduling.md).
- **Splits par km pour toutes les sources.** `python3 scripts/arc_index.py splits <id>` les calcule depuis le FIT,
  de la même façon avec Garmin, COROS, Intervals.icu ou Strava.
- **Nuits COROS lues telles quelles.** `python3 scripts/arc_coros_sleep.py` ne garde que le sommeil principal
  (les siestes ne sont jamais additionnées) et signale une nuit que COROS semble avoir coupée en deux : le coach
  vous donne les deux morceaux et votre déclaration prime. Voir [Le bilan matinal avec COROS](coros.md#le-bilan-matinal-avec-coros).
- **FIT COROS lisibles.** Un FIT dont un champ a une taille incohérente (cas réel d'une montre COROS) est relu
  au lieu d'être refusé en entier ; `download_fit.py --refresh-dynamics` relit aussi les FIT COROS déjà téléchargés.
  Voir [Téléchargement FIT](skills/fit-download.md).
- **Surveillance sans LLM.** `scripts/watch.py` (ex-`garmin_watch.py`) sonde Garmin ou COROS et ne lance la
  synchronisation que s'il y a du neuf. Voir [Le coach dans la poche](mobile.md).

## Choisir son IA

- **OpenRouter en un clic**, sans clé à copier (`./install.sh --llm openrouter --connect`), et **essai gratuit**
  limité avec des modèles `:free` (`--llm openrouter-free`, confidentialité dite honnêtement).
- **Abonnements ChatGPT Plus/Pro et GitHub Copilot** : `--llm chatgpt` ou `--llm copilot`, sans clé API.
  Sur une installation existante, la synchronisation automatique garde son exécuteur, sauf avec
  `--sync-subscription`.
- **Changer la synchronisation seule** : `python3 scripts/arc_llm.py sync …` ; avec l'API Anthropic, elle
  tourne par défaut sur Claude Haiku 5.5. **Tester la connexion** : `python3 scripts/arc_llm.py check --probe`
  ou le bouton « Tester la connexion » de l'application Mac et de la page du chat.
  Voir [Choisir son IA](choisir-son-ia.md).
- **Une vidéo de plus** : « Zéro euro pour démarrer », l'essai gratuit en moins de deux minutes. Voir [Vidéos](videos.md).

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
- **Roadbook plus lisible.** Points de passage « Détaillé » (ravitos et repères espacés d'au moins 15 min,
  approximation du projet) ou « Ravitaillements uniquement » (`?passages=detailed|aid_stations`) ; un ravito
  déclaré à l'arrivée n'ajoute plus d'arrêt fictif ; allure moyenne par section. Le matériel passif (sifflet,
  couverture de survie…) n'est plus signalé « jamais utilisé à l'entraînement ». Voir [Roadbook](dashboard/views.md#roadbook).
- **Application installable (PWA)**, polices embarquées, semaine avec appariement planifié ↔ réalisé.
- **Image Docker publiée sur GHCR** (`:latest`, `:edge`, `:X.Y.Z`) ; le compose du projet la construit encore
  localement. Voir [Docker](dashboard/docker.md#images-publiees-ghcr).

- **Captures reproductibles.** Les images de la documentation sont produites par `scripts/docs_capture.py`
  depuis le workspace fictif de Camille, dans le design roadbook. Voir [Captures de la documentation](videos.md#captures-de-la-documentation).

## Chat et machine coach

- **Recherche dans l'historique.** `python3 scripts/arc_index.py search "<mots-clés>"` retrouve le bon passage
  parmi les séances, bilans, décisions, rapports, `resources/` et les conversations du chat, sans relire les
  fichiers entiers : les agents s'en servent avant tout grep. Voir [Recherche dans l'historique](search.md).
- **Fournisseur saturé reconnu.** Une erreur 503 d'OpenRouter (`provider_overloaded`) s'affiche comme un
  fournisseur saturé à réessayer, dans le chat comme dans la synchronisation.
- **Chat sur téléphone** : plus de saut du fil vers le haut après « Appliquer », puces repliées entières.
- **Journal de Remote Control borné.** `scripts/coach-remote.sh rotate-log` fait tourner `logs/remote-control.log`
  au-delà de 10 Mo, planifié à l'installation. Voir [Le coach dans la poche](mobile.md).

## Application Mac

- **Mises à jour dans l'application** : les nouvelles versions sont proposées par l'app (Sparkle, signature
  vérifiée), même pour le DMG sans signature Apple. Une dernière installation manuelle du DMG reste nécessaire
  depuis une version qui n'avait pas ce mécanisme. Voir [Mises à jour macOS](macos.md#mises-a-jour).

## Releases

- **Tests verts d'abord.** L'image `:edge` et les releases n'avancent qu'après des tests réussis ; « Tag a release »
  ne pousse plus rien sur `main` (seul le tag part). Le fichier `VERSION` n'est plus qu'un repli pour un moteur
  sans `.git` : il se met à jour par une PR ordinaire.

## En vidéo

Quatre nouvelles étapes du « Sentier », en français et en anglais, sous-titrées :

- **22 · [Une autre montre](video/montre-coros/index.html)** : COROS par le MCP officiel, le même bilan matinal (récupération COROS nommée sans conversion), les séances envoyées à la montre après un « oui », la fiche Pace Strategy.
- **23 · [La paire suivante](video/paire-suivante/index.html)** : fiche de caractéristiques sourcée, retours de chaussant, profil d'usage, plages cibles, puis `/shoes` : la continuité d'abord, le confort décide.
- **24 · [Le nouveau roadbook](video/roadbook/index.html)** : le tableau de bord lu comme un roadbook de course, design par défaut de la 1.4, application installable.
- **25 · [Votre IA, votre forfait](video/votre-ia/index.html)** : ChatGPT ou GitHub Copilot sans clé API, une connexion unique, la synchronisation choisie explicitement, « Tester la connexion ».

L'étape 05, « Tour du propriétaire », montre encore l'ancien design du tableau de bord. Toute la série :
[Vidéos](videos.md).

## Mettre à jour

Rien à migrer à la main pour la plupart des installations : [Passer de la 1.3 à la 1.4](update.md#passer-de-la-13-a-la-14).
