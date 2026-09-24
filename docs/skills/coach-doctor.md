# Diagnostic d'installation (`coach-doctor`)

`/coach-doctor` (ou `python3 scripts/coach_doctor.py` directement) vérifie
l'installation en une commande, sans rien écrire ni appeler Garmin Connect.

## Lancer

```bash
python3 scripts/coach_doctor.py
```

```
coach doctor — /chemin/vers/votre/workspace
❌ garmin_token           Tokens Garmin expirés depuis 3 jour(s) (~/.garminconnect).
    → correctif : uv run garmin-mcp-auth
✅ garmin_mcp             MCP garmin joignable (handshake « initialize » réussi).
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

## Ce qui est vérifié

| Vérification | Détail | Sévérité |
|---|---|---|
| `garmin_token` | Âge/échéance des tokens `~/.garminconnect` | ⚠️ à moins de 14 jours de l'échéance, ❌ si expirés ou absents |
| `garmin_mcp` | MCP `garmin` joignable (handshake `initialize`, sans appel Garmin réel) | ❌ si la commande est introuvable, ⚠️ si elle ne répond pas |
| `config_files` | `config/workspace.toml` et `config/workspace.user.toml` sont du TOML valide | ❌ si absent ou invalide |
| `athlete_profile` | FC max / FC de repos renseignées dans `planning/Runner_Profile.md` | ℹ️ sinon — le coach utilise le RPE à la place |
| `index_freshness` | `.arc/coach.db` à jour par rapport aux fichiers du workspace | ⚠️ si périmé, ℹ️ si jamais construit |
| `out_of_contract` | Nombre de fichiers sans bloc ```` ```arc ```` conforme | ⚠️ si non nul |
| `daily_sync_scheduled` | Tâche cron (Linux) ou LaunchAgent (macOS) du daily-sync | ℹ️ seulement — un daily-sync non installé est un choix valide |
| `ntfy_configured` | Notifications push configurées, si activées | ℹ️ si désactivées, ⚠️ si mal configurées |

Un ❌ fait échouer la commande (code de sortie non nul). Un ⚠️ ou un ℹ️ jamais —
ce sont des dégradations connues, pas des pannes.

## Méthode de détection de l'échéance des tokens

1. `~/.garminconnect/oauth2_token.json` (format `garth`, présent sur certaines
   installations de `garminconnect`) : champ **explicite**
   `refresh_token_expires_at` — le signal le plus fiable.
2. À défaut, `~/.garminconnect/garmin_tokens.json` (format du client vendored
   par `garmin-mcp`, qui ne persiste que `di_token`/`di_refresh_token`/
   `di_client_id`, sans échéance longue durée explicite) : repli sur la date
   de dernière modification du fichier, plus une fenêtre de validité
   d'environ **6 mois** — voir [Dépannage](../troubleshooting.md).

Aucun contenu de token n'est jamais affiché : seuls des métadonnées (chemin,
date d'échéance, nombre de jours restants) apparaissent en sortie.

## Sortie machine

```bash
python3 scripts/coach_doctor.py --json
```

Un objet par vérification (`id`, `status`, `message`, `fix`), plus
`expires_at`/`days_left`/`source` pour `garmin_token` — schéma complet en tête
de `scripts/coach_doctor.py`. Cette sortie alimente le tableau de bord et
l'alerte ntfy avant expiration des tokens.

## Options utiles

```bash
python3 scripts/coach_doctor.py --workspace /chemin/vers/le/workspace
python3 scripts/coach_doctor.py --tokens-dir /chemin/de/test   # override ~/.garminconnect
python3 scripts/coach_doctor.py --now 2026-09-24T12:00:00+00:00  # horloge figée (tests)
```

## Quand le lancer

- Avant toute autre investigation : synchronisation en échec, erreur MCP,
  agent qui semble se comporter bizarrement.
- Après une réinstallation ou un changement de machine.
- Périodiquement, en curiosité — il ne modifie rien.
