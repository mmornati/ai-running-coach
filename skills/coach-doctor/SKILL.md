---
name: coach-doctor
description: Diagnostic d'installation en une commande — vérifie l'échéance des tokens Garmin, la joignabilité du MCP garmin, la validité des fichiers config/workspace*.toml, la complétude du profil athlète, la fraîcheur de l'index .arc/coach.db, les fichiers hors contrat, la planification du daily-sync (cron/launchd) et la configuration ntfy. Charger quand l'utilisateur lance /coach-doctor, quand quelque chose semble cassé (synchronisation en échec, réponse étrange d'un agent, erreur MCP), ou proactivement avant de creuser un problème d'installation plutôt que de deviner à l'aveugle.
---

# Diagnostic d'installation

`scripts/coach_doctor.py` sait tout vérifier d'un coup, sans rien écrire ni
appeler Garmin Connect. Ne devinez pas la cause d'un problème d'installation à
la main — lancez-le d'abord.

## 1. Lancer le diagnostic

```bash
python3 scripts/coach_doctor.py
```

Rend un tableau ✅/⚠️/❌ en français, une ligne par vérification, avec la
commande de correction sous chaque ligne non ✅ :

| Vérification | Ce qu'elle couvre |
|---|---|
| `garmin_token` | Âge/échéance des tokens `~/.garminconnect` — ⚠️ à moins de 14 jours, ❌ si expirés ou absents |
| `garmin_mcp` | MCP `garmin` joignable (handshake léger, sans appel Garmin réel) |
| `config_files` | `config/workspace.toml` et `config/workspace.user.toml` sont du TOML valide |
| `athlete_profile` | FC max / FC de repos renseignées dans le profil — sinon repli sur le RPE |
| `index_freshness` | `.arc/coach.db` à jour par rapport aux fichiers du workspace |
| `out_of_contract` | Nombre de fichiers sans bloc ```` ```arc ```` conforme |
| `daily_sync_scheduled` | Tâche cron ou LaunchAgent du daily-sync installée |
| `ntfy_configured` | Notifications push configurées (si activées) |

Un ❌ fait échouer la commande (code de sortie non nul) ; un ⚠️ ou un ℹ️ jamais
— ce sont des dégradations connues, pas des pannes.

## 2. Relayer le résultat

Restituez le tableau (ou un résumé s'il est long, selon `[coaching].verbosity`)
**dans la langue des documents** (`config/workspace.toml` → `[language].documents`),
en mettant en avant :

- tout ❌, avec sa commande de correction telle quelle — ne la reformulez pas ;
- les ⚠️ qui touchent directement la demande de l'athlète (ex. token qui expire
  bientôt s'il vient de parler de synchronisation Garmin) ;
- ne noyez pas l'athlète sous les ℹ️ (daily-sync non installé, notifications
  désactivées) s'il n'a rien demandé de tel — mentionnez-les en une ligne.

Le token Garmin expiré ou proche de l'échéance est le cas le plus fréquent :
orientez toujours vers `uv run garmin-mcp-auth` (voir `docs/troubleshooting.md`),
jamais une commande inventée.

## 3. Sortie machine (`--json`)

```bash
python3 scripts/coach_doctor.py --json
```

Schéma documenté en tête de `scripts/coach_doctor.py` — un objet par
vérification (`id`, `status`, `message`, `fix`), plus `expires_at`/`days_left`/
`source` pour `garmin_token`. Utilisé par le tableau de bord et par la story
#32 (alerte ntfy avant expiration des tokens) : ne changez pas les noms de
champs sans mettre à jour les deux.

## 4. Quand le charger de vous-même

- L'athlète rapporte une synchronisation en échec, une erreur MCP, ou un agent
  qui semble se comporter bizarrement (bilan santé absent, séance non
  poussée...).
- Avant de conclure « c'est un token expiré » ou « le MCP n'est pas configuré »
  à partir d'un symptôme indirect — vérifiez, ne devinez pas.
- Jamais en boucle : si le diagnostic est déjà tout vert, ne le relancez pas
  sans nouvelle raison.

## 5. Ce que ce script NE fait PAS

- Il n'écrit rien sur le disque (pas de réindexation, pas de correction
  automatique) et n'affiche jamais le contenu d'un token.
- Il n'appelle pas l'API Garmin Connect (le check `garmin_mcp` se limite à un
  handshake MCP `initialize`, borné dans le temps).
- Il ne remplace pas `/coach-setup` (configuration initiale) ni
  `scripts/setup-ntfy.sh` (configuration des notifications) — il vous dit
  seulement lequel lancer.
