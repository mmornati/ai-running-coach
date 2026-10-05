# Démarrage rapide

Ce guide vous permet d'installer et de configurer `ai-running-coach` en quelques minutes.

<!-- arc-video:ligne-de-depart -->
<div class="arc-video-card" markdown>

[![Ligne de départ](video/ligne-de-depart/poster.jpg)](video/ligne-de-depart/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 01 · 1 min 45</span>

**[Ligne de départ](video/ligne-de-depart/index.html)** — Du git clone au premier /today : installation, authentification Garmin, /coach-setup et /coach-doctor en moins de deux minutes.

[Regarder](video/ligne-de-depart/index.html) · [English](video/ligne-de-depart/index.html?lang=en) · [Toutes les vidéos](videos.md)

</div>

</div>
<!-- /arc-video -->


## Prérequis

- **macOS** ou **Linux**
- **bash 3.2+** (celui livré avec macOS convient)
- **curl** et **git**
- Un compte **Garmin Connect** (avec un appareil Garmin)

!!! tip "Homebrew"
    **Homebrew** est recommandé sur macOS. Il est requis uniquement pour le mode passerelle optionnel (`leanproxy-mcp`).

## Installation

```bash
git clone https://github.com/mmornati/ai-running-coach.git
cd ai-running-coach
./install.sh
```

Le script effectue les étapes suivantes :

1. **uv** — gestionnaire Python (installé si absent)
2. **garmin-mcp** — serveur MCP d'accès à Garmin Connect
3. **garmin-mcp-auth** — authentification Garmin (tokens valides ~6 mois)
4. **Configuration IDE** — serveur MCP `garmin` (mode direct, liste blanche d'outils) pour Claude Code, GitHub Copilot, OpenCode, Gemini CLI, Cursor, Windsurf
5. **Dossiers de travail** — `activities/`, `medical/`, `nutrition/`, `planning/`, `rapports/`, `gear/`, `resources/`

## Authentification Garmin

Lors de la première installation, le script lance l'authentification Garmin Connect :

1. Saisissez votre **email** et **mot de passe** Garmin Connect
2. Validez le **code MFA** si votre compte en est équipé
3. Les tokens sont stockés dans `~/.garminconnect/` (valides ~6 mois)

!!! warning "Sécurité"
    Vos identifiants ne sont jamais stockés dans le projet. Les tokens sont conservés dans votre répertoire personnel (`~/.garminconnect/`), hors du dépôt.

## Options du script

| Option | Description |
|---|---|
| `--preset NOM` | Préréglage qui compose les options ci-dessous : `laptop`, `coach-server` ou `docker` — voir [Préréglages](#prereglages) |
| `--ide claude` | Installe pour un IDE précis (`claude`, `copilot`, `opencode`, `gemini`, `cursor`, `windsurf`) |
| `--source intervals` | Source de données primaire : `garmin` (défaut), `intervals` (sans montre Garmin) ou `strava` (Node.js 18+) — voir [Configuration Intervals.icu](intervals-setup.md) et [Configuration Strava](strava-setup.md) |
| `--agents LISTE` | Staff à installer, ex. `coach,nutritionist` — voir [Configuration](configuration.md#le-staff-agents) |
| `--no-medical` | Tous les agents sauf le médecin |
| `--no-auth` | Saute l'authentification Garmin |
| `--auth` | Force l'authentification Garmin (annule un `--no-auth` composé par un préréglage) |
| `--use-leanproxy` | Mode passerelle leanproxy-mcp (power user, optionnel) |
| `--skip-leanproxy` | Mode direct (défaut) — annule un `--use-leanproxy` composé par un préréglage |
| `--workspace DIR` | Données et configs IDE dans `DIR` (votre dépôt privé), moteur lié — voir [Votre workspace privé](workspace.md) |
| `--daily-sync` | Synchronisation Garmin automatique (cron/launchd) + notification — voir [Le coach dans la poche](mobile.md) |
| `--no-daily-sync` | Désactive la synchronisation (annule un `--daily-sync` composé par un préréglage) |
| `--remote-control` | Service Claude Code Remote Control : le coach depuis le téléphone — voir [Le coach dans la poche](mobile.md) |
| `--no-remote-control` | Désactive Remote Control (annule un `--remote-control` composé par un préréglage) |
| `--dry-run` | Affiche les actions sans rien exécuter |
| `--help` | Affiche l'aide |

## Préréglages

Un préréglage ne fait que **composer les options ci-dessus** — jamais de
comportement qui ne serait pas atteignable avec les options existantes. Une
option passée explicitement l'emporte toujours sur le préréglage, quel que
soit son ordre sur la ligne de commande (`--preset laptop --daily-sync`
revient exactement à `--daily-sync --preset laptop`) — y compris pour
**éteindre** une valeur qu'un préréglage aurait allumée, avec `--auth`,
`--no-daily-sync` ou `--no-remote-control`.

`--source` n'est composée par AUCUN préréglage — les préréglages décrivent
**où** vous installez (laptop, machine coach, machine coach + Docker), pas
**quelle source de données** vous avez ; les deux se combinent librement
(ex. `--preset coach-server --source intervals`). Le récapitulatif affiché
avant toute action indique l'origine de chaque valeur retenue —
`explicite`, `préréglage <nom>` ou `défaut` (jamais `préréglage` pour
`--source`, toujours `explicite` ou `défaut`).

| Préréglage | Équivaut à | Pour qui |
|---|---|---|
| `laptop` | `--ide all` (le reste aux valeurs par défaut — `laptop` **est** la configuration par défaut du script, en plus explicite) | Le parcours de cette page : votre propre machine, en interactif, tous les IDE supportés. |
| `coach-server` | `--ide claude --daily-sync --remote-control` | La machine « coach » toujours allumée de [Le coach dans la poche](mobile.md) : synchronisation automatique + dialogue depuis le téléphone. |
| `docker` | `--ide claude --daily-sync` | La machine qui sert AUSSI le [tableau de bord en conteneur](dashboard/docker.md) : `docs/dashboard/docker.md` le déploie « sur la machine coach », dont la synchronisation Garmin a besoin d'une authentification comme n'importe quelle autre machine coach (l'authentification **reste active**, contrairement à une version antérieure de ce préréglage) ; pas de Remote Control, l'interface de cette machine est le tableau de bord web. Ce préréglage ne prépare que **l'hôte** — le conteneur lui-même se lance séparément avec `docker compose up -d --build`. |

Avant d'agir, le script affiche un récapitulatif de la configuration
effective, en indiquant pour chaque option si sa valeur vient du préréglage
ou d'une option explicite :

```bash
./install.sh --preset coach-server --no-remote-control --dry-run
```

```
==> Récapitulatif de la configuration effective :
  Préréglage : coach-server
  IDE : claude (préréglage coach-server)
  Auth Garmin : activée (préréglage coach-server)
  Sync auto (cron) : oui (préréglage coach-server)
  Remote Control : non (explicite)
  ...
```

`--dry-run` fonctionne avec chaque préréglage (aucune écriture sur le
disque) ; un nom de préréglage inconnu est une erreur claire (`Préréglage
inconnu : « … ». Valides : laptop coach-server docker`), pas un plantage ; de
même pour `--preset` répété avec deux valeurs différentes sur la même ligne de
commande.

## Premiers pas

1. **Lancez votre IDE** dans le dossier du projet

2. **Lancez `/coach-setup`**

    Un entretien court : votre staff d'agents, votre discipline, la façon dont le
    coach vous parle, votre bilan santé matinal. Il installe aussi votre profil
    d'athlète et votre fiche d'objectif.

    Relancer la commande est sans risque : elle ne pose que les questions sans
    réponse et ne remplace jamais un réglage existant.
    Voir [Premier démarrage](skills/coach-setup.md) et [Configuration](configuration.md).

3. **Demandez à l'agent `coach`** de définir votre objectif, par exemple :

    - *« Je veux préparer un trail de 50 km avec 2500 m de D+ dans 6 mois »*
    - *« Aide-moi à planifier ma semaine d'entraînement »*

4. L'agent `coach` coordonne les agents que vous avez retenus et pousse vos séances directement dans le **calendrier Garmin Connect**

## Vérification

Pour vérifier que tout est bien installé :

```bash
uv --version
garmin-mcp --version
ls ~/.garminconnect/
```

En mode passerelle (`--use-leanproxy`), vérifiez aussi `leanproxy-mcp --version`.

## Prochaines étapes

- [Configuration](configuration.md) — staff, style de coaching, discipline, bilan santé
- [Configuration Garmin](garmin-setup.md) — détails sur l'accès Garmin
- [Les agents](agents.md) — comprendre le rôle de chaque agent
- [Les skills](skills.md) — découvrir les skills disponibles
- [Dépannage](troubleshooting.md) — résoudre les problèmes courants
