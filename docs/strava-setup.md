# 🟠 Configuration Strava (source alternative, #164)

Cette page détaille la source de données **Strava** : la plus « universelle »
(toutes marques de montres — Garmin, COROS, Suunto, Polar, Apple… — publient
vers Strava, et beaucoup d'athlètes l'ont déjà). Elle est installée par
`./install.sh --source strava`, **à la place** de Garmin, pas en plus.

!!! info "Ceci ne change rien si vous utilisez Garmin ou Intervals.icu"
    Par défaut (`[data].source = "garmin"`, ou pas de clé du tout), rien dans
    ce projet ne change. `install.sh` ne touche jamais à `[data]` tant que vous
    n'avez pas passé `--source` vous-même, et un simple `./install.sh` relancé
    plus tard relit la source déjà configurée.

## Ce que Strava apporte — et ce qu'il n'apporte pas

| Disponible | Indisponible (dit explicitement, jamais simulé) |
|---|---|
| Activités récentes ou par période, détail d'une activité | **HRV, FC de repos, sommeil, readiness** : `[health].morning_check` se dégrade explicitement |
| **Flux par seconde** (temps, distance, altitude, FC, vitesse lissée, cadence, GPS) → les KPI du FIT : zones, GAP, découplage, VAM, descente, durabilité, énergie modèle | **Push de séances au calendrier**, upload de parcours (Strava n'a pas de calendrier d'entraînement) |
| Zones FC de l'athlète, chaussures (inventaire) | FC de récupération (HRR), splits par km, dénivelé négatif, dynamique de course |
| Aucune dépendance Python (stdlib) | Identifiant de matériel par séance (seul le **nom** est exposé) |

Le bilan matinal est donc toujours dit « indisponible — source Strava » : l'agent
planifie sur la charge, l'historique et **votre ressenti déclaré**. Une séance
annulée pour raison médicale reste annulée.

## Deux serveurs possibles

### Serveur communautaire `r-huijts/strava-mcp` (installé par `install.sh`)

C'est la voie supportée, y compris en **headless** (`garmin-daily-sync`, cron) et
dans le chat du tableau de bord.

- Paquet npm [`@r-huijts/strava-mcp-server`](https://github.com/r-huijts/strava-mcp),
  **épinglé à la version 1.2.1** (`STRAVA_MCP_PKG` dans `install.sh`), lancé par
  `npx` via un petit wrapper `~/.config/ai-running-coach/strava-mcp/run.sh`.
  Le code lu pour vérifier les noms d'outils est celui du commit
  `ac43cc7b0aad2f218b9c42bd639aee696dbee531` ; l'identité exacte entre ce commit et le
  tarball npm n'a **pas** été vérifiée octet pour octet : relisez avant de relever la version.
- **Prérequis : Node.js 18 ou plus.**
- Il utilise **votre propre application API Strava** (client id + secret) : un
  accès OAuth à votre compte, pour vous seul.
- Outils vérifiés dans son code source : `get-recent-activities`, `get-all-activities`,
  `get-activity-details`, `get-activity-streams`, `get-activity-laps`, `get-athlete-zones`,
  `get-athlete-shoes`, `get-athlete-profile`, `get-athlete-stats`, plus des outils de
  segments/itinéraires, et trois outils qui **agissent** : `connect-strava`,
  `disconnect-strava`, `star-segment` (écriture). La table de correspondance
  Garmin ↔ Strava est dans `AGENTS.md`.
- Les réponses sont du **texte formaté**, pas du JSON structuré : c'est pourquoi les
  KPI passent par les flux normalisés (voir plus bas) plutôt que par ce texte.

### Connecteur officiel Strava (alternative manuelle)

Strava a lancé le 1er juin 2026 un connecteur MCP officiel
(`https://mcp.strava.com/mcp`, distant, OAuth, **lecture seule**, abonnement payant),
utilisable dans Claude.ai, Cowork et Claude Code
([article d'aide Strava](https://support.strava.com/hc/articles/46190267796237)) :

```bash
claude mcp add --transport http strava-mcp https://mcp.strava.com/mcp
```

!!! warning "Non vérifié"
    L'authentification OAuth est requise pour lister ses outils : leurs **noms et formes de
    réponse n'ont pas pu être vérifiés** pour ce projet. La table de correspondance ne s'y
    applique donc pas ; l'agent lit la liste d'outils de la session et n'invente rien. Il
    n'est pas utilisable pour la synchronisation headless ni pour `download_fit.py` (qui
    s'authentifie avec les jetons du serveur communautaire). `install.sh` ne l'installe pas
    et ne supprime jamais une entrée `strava` que vous avez ajoutée à la main.

## Installation

```bash
./install.sh --source strava
```

Ce que fait le script : vérifie Node.js, écrit le wrapper, déclare le serveur `strava`
dans `.mcp.json` (et les autres IDE), écrit `[data].source = "strava"` dans
`config/workspace.user.toml`. Il n'installe pas `uv`/`garmin-mcp` et ne fait aucune
authentification (voir ci-dessous). Relancé, il est idempotent.

### Connecter votre compte (une seule fois)

1. Créez votre application API sur <https://www.strava.com/settings/api> avec
   **« Authorization Callback Domain » = `localhost`**.
2. Dans une session interactive de l'agent, demandez : « exécute l'outil connect-strava ».
   Il ouvre `http://localhost:8111/setup` dans le navigateur : saisissez le client id et le
   client secret, puis autorisez l'accès.
3. Les jetons sont écrits par le serveur dans `~/.config/strava-mcp/config.json`
   (`accessToken`, `refreshToken`, `expiresAt`, `clientId`, `clientSecret`).

!!! warning "Portées demandées et droits du fichier"
    Ce serveur demande les portées `profile:read_all`, `activity:read_all`, `activity:read` et
    **`profile:write`** (pour `star-segment`). Le projet n'appelle jamais `star-segment` en
    headless et le chat demande une approbation, mais le **jeton lui-même** garde cette portée
    d'écriture. Le serveur écrit ce fichier avec les droits par défaut : `coach-doctor`
    signale (⚠️) un fichier lisible par d'autres utilisateurs — corrigez avec
    `chmod 600 ~/.config/strava-mcp/config.json`. Ne committez jamais ce fichier.

Diagnostic : `python3 scripts/coach_doctor.py --check strava_connection` (Node.js, wrapper,
serveur déclaré, jetons présents — les valeurs ne sont jamais lues ni affichées ; aucun appel
réseau). Le jeton d'accès expire en 6 h environ : ce n'est pas une panne, il se rafraîchit
seul.

## Flux par seconde et KPI

`skills/fit-download/scripts/download_fit.py <s-id> --source strava` (la source est lue dans
`[data].source` par défaut) :

1. lit les jetons du serveur communautaire, rafraîchit le jeton d'accès s'il est expiré (le
   nouveau jeton de rafraîchissement, **rotatif**, est réécrit atomiquement dans le même
   fichier, droits 0600, autres clés conservées) ;
2. `GET /api/v3/activities/<id>` (sport) puis
   `GET /api/v3/activities/<id>/streams?keys=…&key_by_type=true` ;
3. normalise via `arc_samples.strava_streams_to_records` vers
   `activities/fit/s<chiffres>.json` — le même format que le FIT, donc les mêmes KPI
   (testés à égalité sur un jeu synthétique).

- **Identifiant** : l'API rend un entier nu, indiscernable d'un `garmin_activity_id`. Le projet
  utilise donc le préfixe `s` : `strava_activity_id: "s12345678901"` dans le bloc `arc`.
- **Hypothèse à vérifier** : la cadence est doublée pour les sports à pied (convention du FIT) ;
  la référence de l'API Strava documente `cadence` en RPM sans préciser un ou deux pieds. À
  confirmer sur une vraie séance ; sans effet sur les autres KPI.
- **Limites d'API** (valeurs par défaut de Strava, à vérifier pour votre application) :
  200 requêtes / 15 min, 2000 / jour. Le script fait 2 requêtes par séance ; un `HTTP 429`
  est expliqué, pas contourné — relancez plus tard.
- Une activité saisie à la main n'a pas de flux : `INDISPONIBLE`, la séance reste valide.

## Conditions d'usage de l'API Strava

L'[accord API Strava](https://www.strava.com/legal/api) (mis à jour le 1er juin 2026) dit,
en substance : les données d'un utilisateur ne peuvent être affichées qu'à cet utilisateur,
et, à la fin de l'accord, le développeur doit supprimer définitivement les données Strava.
Conséquences pour ce projet :

- vos données Strava restent dans **votre** espace de travail privé (`activities/`,
  `activities/fit/` gitignoré) ; ce dépôt public n'en contient aucune — les tests utilisent
  des flux **synthétiques** ;
- si vous révoquez l'accès ou fermez votre application API, supprimez
  `activities/fit/s*.json` et les fichiers qui en dérivent ;
- relecture automatisée et partielle de l'accord : aucune clause sur l'IA ou l'apprentissage
  automatique n'y a été trouvée, ni de limite de stockage, mais **lisez-le vous-même** — il fait foi.

## Synchronisation headless

`garmin-daily-sync` fonctionne avec cette source (`mcp__strava` autorisé), en **lecture
seule** : `daily-sync.sh` interdit `connect-strava`, `disconnect-strava` et `star-segment`
(et leurs équivalents OpenCode). Si les jetons sont absents ou révoqués, la synchronisation
s'arrête avec une notification : relancez `connect-strava` dans une session interactive.
`[sync].mode = "watch"` n'existe pas pour Strava (heures fixes).

## Désinstaller / changer de source

`./install.sh --source garmin` (ou `intervals`) retire l'entrée `strava` écrite par
l'installateur (jamais une entrée ajoutée à la main) et réécrit `[data].source`. Pour effacer
la connexion : supprimez `~/.config/strava-mcp/config.json` et révoquez l'application sur
<https://www.strava.com/settings/apps>.
