# Diagnostic d'installation (`coach-doctor`)

`/coach-doctor` (ou `python3 scripts/coach_doctor.py` directement) vérifie
l'installation en une commande, sans rien écrire — et, par défaut, sans
appeler Garmin Connect (voir `--probe-mcp` plus bas).

## Lancer

```bash
python3 scripts/coach_doctor.py
```

```
coach doctor — /chemin/vers/votre/workspace
❌ garmin_token           Tokens Garmin expirés depuis 3 jour(s) (/home/alex/.garminconnect).
    → correctif : uv run garmin-mcp-auth
✅ garmin_mcp             MCP garmin : commande « garmin-mcp » présente (/home/alex/.local/bin/garmin-mcp).
✅ config_files           Configuration TOML valide (config/workspace.toml, config/workspace.user.toml).
✅ athlete_profile        FC max et FC de repos renseignées dans le profil.
✅ index_freshness        Index .arc/coach.db à jour.
✅ out_of_contract        Aucun fichier hors contrat.
ℹ️ daily_sync_scheduled   Aucun LaunchAgent daily-sync — synchronisation Garmin manuelle uniquement.
    → correctif : ./install.sh --daily-sync
⚠️ ntfy_configured        ntfy activé mais aucun topic configuré.
    → correctif : scripts/setup-ntfy.sh

Au moins une vérification est en échec (❌) — voir les correctifs ci-dessus.
```

(Le chemin affiché est toujours le chemin ABSOLU résolu — `~/.garminconnect`
n'apparaît jamais littéralement en sortie.)

## Ce qui est vérifié

| Vérification | Détail | Sévérité |
|---|---|---|
| `garmin_token` | Âge/échéance des tokens Garmin (`~/.garminconnect` par défaut) | ⚠️ à moins de 14 jours de l'échéance, ❌ si expirés ou absents |
| `garmin_mcp` | Présence/exécutabilité du binaire MCP `garmin` (aucun process lancé) | ❌ si la commande est introuvable ou non exécutable |
| `config_files` | `config/workspace.toml` et `config/workspace.user.toml` sont du TOML valide | ❌ si absent ou invalide, ⚠️ si validation stricte indisponible (Python < 3.11) |
| `athlete_profile` | FC max / FC de repos renseignées dans `planning/Runner_Profile.md` | ℹ️ sinon — le coach utilise le RPE à la place |
| `index_freshness` | `.arc/coach.db` à jour par rapport aux fichiers du workspace (y compris les fichiers supprimés) | ⚠️ si périmé ou si un fichier supprimé est encore indexé, ℹ️ si jamais construit |
| `out_of_contract` | Nombre de fichiers sans bloc ```` ```arc ```` conforme | ⚠️ si non nul |
| `daily_sync_scheduled` | Tâche cron (Linux) ou LaunchAgent (macOS) du daily-sync | ℹ️ seulement — un daily-sync non installé est un choix valide |
| `ntfy_configured` | Notifications push configurées, si activées | ℹ️ si désactivées, ⚠️ si mal configurées |

Un ❌ fait échouer la commande (code de sortie non nul). Un ⚠️ ou un ℹ️ jamais —
ce sont des dégradations connues, pas des pannes.

## `garmin_mcp` : présence par défaut, handshake réel en option

Lancer réellement `garmin-mcp` déclenche une connexion à Garmin Connect avant
même de répondre au protocole MCP (voir la docstring de
`check_garmin_mcp_presence` dans `scripts/coach_doctor.py`) : réseau, retries,
et une possible réécriture des tokens. `coach doctor` s'en tient donc par
défaut à vérifier que le binaire configuré existe et est exécutable.

Un vrai handshake MCP `initialize`, borné dans le temps, reste disponible :

```bash
python3 scripts/coach_doctor.py --probe-mcp   # CONTACTE Garmin Connect
```

## Méthode de détection de l'échéance des tokens

Le client `garminconnect` vendored par `garmin-mcp` ne lit/écrit qu'un seul
fichier : `garmin_tokens.json` — c'est donc TOUJOURS lui qui fait foi quand il
est présent, même si un `oauth2_token.json` (format `garth`, jamais produit
par cette installation) traîne encore d'une ancienne configuration.

1. `garmin_tokens.json` (le fichier réel) ne contient aucune échéance longue
   durée exploitable : son `di_token` est un JWT dont le claim `exp`
   correspond à une session courte (régénérée automatiquement, ~1 jour), et
   `di_refresh_token` n'est pas un JWT. Repli : date de dernière modification
   du fichier + une fenêtre de validité d'environ **6 mois** — voir
   [Dépannage](../troubleshooting.md). **Limite connue** : ce fichier est
   réécrit à chaque rafraîchissement automatique du token, ce qui repousse
   la mtime (donc l'échéance estimée) sans que la session ait réellement été
   renouvelée pour 6 mois de plus — ne traitez pas `mtime_fallback` comme une
   garantie, seulement comme la meilleure estimation disponible.
2. `oauth2_token.json` (format `garth`) n'est utilisé QUE si `garmin_tokens.json`
   est absent : son champ **explicite** `refresh_token_expires_at` sert alors
   de signal.

Aucun contenu de token n'est jamais affiché : seuls des métadonnées (chemin,
date d'échéance, nombre de jours restants) apparaissent en sortie.

## Sortie machine

```bash
python3 scripts/coach_doctor.py --json
python3 scripts/coach_doctor.py --json --check garmin_token   # une seule vérification (#32)
```

Un objet par vérification (`id`, `status`, `message`, `fix`), plus
`expires_at`/`days_left`/`source` pour `garmin_token` — schéma complet en tête
de `scripts/coach_doctor.py`. Conçue pour être réutilisée telle quelle par
l'alerte ntfy avant expiration des tokens (#32).

## Options utiles

```bash
python3 scripts/coach_doctor.py --workspace /chemin/vers/le/workspace
python3 scripts/coach_doctor.py --tokens-dir /chemin/de/test     # override du répertoire de tokens
python3 scripts/coach_doctor.py --now 2026-09-24T12:00:00+00:00  # horloge figée (tests)
python3 scripts/coach_doctor.py --check garmin_token             # une seule vérification, sans MCP
python3 scripts/coach_doctor.py --probe-mcp                      # handshake MCP réel (contacte Garmin)
```

## Quand le lancer

- Avant toute autre investigation : synchronisation en échec, erreur MCP,
  agent qui semble se comporter bizarrement.
- Après une réinstallation ou un changement de machine.
- Périodiquement, en curiosité — par défaut, il ne modifie rien et ne contacte
  personne.
