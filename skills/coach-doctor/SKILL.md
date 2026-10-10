---
name: coach-doctor
description: Diagnostic d'installation en une commande — vérifie l'échéance des tokens Garmin, la joignabilité du MCP garmin, la validité des fichiers config/workspace*.toml, la complétude du profil athlète, la fraîcheur de l'index .arc/coach.db, les fichiers hors contrat, la planification du daily-sync (cron/launchd), la configuration ntfy et le lecteur FIT (fitparse dans l'environnement MCP de [data].source). Charger quand l'utilisateur lance /coach-doctor, quand quelque chose semble cassé (synchronisation en échec, réponse étrange d'un agent, erreur MCP), ou proactivement avant de creuser un problème d'installation plutôt que de deviner à l'aveugle.
---

# Diagnostic d'installation

`scripts/coach_doctor.py` sait tout vérifier d'un coup, sans rien écrire —
par défaut, sans appeler Garmin Connect non plus (voir §5). Ne devinez pas la
cause d'un problème d'installation à la main — lancez-le d'abord.

## 1. Lancer le diagnostic

```bash
python3 scripts/coach_doctor.py
```

Rend un tableau ✅/⚠️/❌ en français, une ligne par vérification, avec la
commande de correction sous chaque ligne non ✅ :

| Vérification | Ce qu'elle couvre |
|---|---|
| `garmin_token` | Âge/échéance des tokens (`~/.garminconnect` par défaut) — ⚠️ à moins de 14 jours, ❌ si expirés ou absents |
| `garmin_mcp` | Présence/exécutabilité du binaire MCP `garmin` — pas de handshake réel sans `--probe-mcp` (§5) |
| `config_files` | `config/workspace.toml` et `config/workspace.user.toml` sont du TOML valide |
| `athlete_profile` | FC max / FC de repos renseignées dans le profil — sinon repli sur le RPE |
| `index_freshness` | `.arc/coach.db` à jour par rapport aux fichiers du workspace |
| `out_of_contract` | Nombre de fichiers sans bloc ```` ```arc ```` conforme |
| `daily_sync_scheduled` | Tâche cron ou LaunchAgent du daily-sync installée ; en mode `[sync].mode = "watch"`, passage récent de `garmin_watch.py` (⚠ après 3 intervalles de silence) |
| `ntfy_configured` | Notifications push configurées (si activées) |
| `gear_sync` | (#133) Liste blanche `GARMIN_ENABLED_TOOLS` de `.mcp.json` avec `get_gear`/`get_activity_gear` ; paires actives du profil sans segment `garmin: <uuid>` (ℹ️). **Statique : aucun appel Garmin** — lister le matériel Garmin sans puce est le rôle du coach (`get_gear`) |
| `weight_sync` | (#222) Liste blanche `GARMIN_ENABLED_TOOLS` avec `get_daily_weigh_ins`/`get_weigh_ins` (lecture des pesées). ℹ️ si absents (relancer l'installation) ou source ≠ garmin — jamais un avertissement : le poids reste alors déclaratif. **Statique : aucun appel Garmin** |
| `gear_history` | (#145) ≥ 5 séances avec `garmin_activity_id`, dont plus de la moitié sans `gear_id` : historique sans matériel (ℹ️ seulement). Propose le rattrapage `python3 scripts/garmin_gear_backfill.py` (simulation d'abord ; `--apply` seulement sur accord de l'athlète). **Statique : aucun appel Garmin.** |
| `fit_reader` | `fitparse` importable dans l'environnement MCP de `[data].source` (`garmin-mcp` ou `intervals-icu-mcp`) — sans lui, les FIT téléchargés ne sont pas lus et les KPI fins restent vides. Correctif : `./install.sh --source <source>` ; informatif (ℹ️) avec `strava` : aucun FIT, flux normalisés en stdlib |
| `intervals_mcp_pin` | (#165) Source intervals.icu : le serveur `intervals-icu-mcp` installé par `uv tool` est-il au commit épinglé ? ⚠️ s'il vient encore de l'ancien dépôt `eddmann` (outils sans préfixe `icu_`) — correctif `./install.sh --source intervals`, puis NOUVELLE session. ℹ️ ailleurs (source Garmin : non applicable). Lecture locale du `direct_url.json`, aucun réseau |
| `strava_connection` | (#164, `[data].source = "strava"` seulement, sinon ℹ️) Node.js >= 18, wrapper `~/.config/ai-running-coach/strava-mcp/run.sh`, serveur `strava` dans `.mcp.json`, jetons du serveur (`~/.config/strava-mcp/config.json` : refresh token, clientId/clientSecret) et droits de lecture (⚠️ si lisible par d'autres : `chmod 600`). **Statique : valeurs jamais lues ni affichées, aucun appel réseau** ; l'échéance du jeton d'accès (6 h) n'est pas une alerte, il se rafraîchit seul |
| `telegram` | (#174, `[telegram].enabled` seulement, sinon ℹ️) Liste blanche non vide, fichier du jeton en mode 600 au bon format (**valeur jamais affichée**), jeton non exporté, `chat_bridge` cohérent avec `[chat]`, service vivant (battement de moins de 5 min). ⚠️ au plus, aucun appel réseau |

Un ❌ fait échouer la commande (code de sortie non nul) ; un ⚠️ ou un ℹ️ jamais
— ce sont des dégradations connues, pas des pannes.

## 2. Relayer le résultat

Restituez le tableau (ou un résumé s'il est long, selon `[coaching].verbosity`)
**dans la langue des réponses** (`config/workspace.toml` → `[language].responses`,
défaut `auto` = celle de la requête de l'athlète — ce diagnostic est une
réponse en chat, pas un fichier persisté dans `activities/`/`medical/`/etc.,
donc `[language].documents` ne s'applique pas ici), en mettant en avant :

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
`source` pour `garmin_token`. Conçu pour être réutilisé tel quel par la story
#32 (alerte ntfy avant expiration des tokens, via `--check garmin_token`) : ne
changez pas les noms de champs sans mettre à jour les deux.

## 4. Quand le charger de vous-même

- L'athlète rapporte une synchronisation en échec, une erreur MCP, ou un agent
  qui semble se comporter bizarrement (bilan santé absent, séance non
  poussée...).
- Avant de conclure « c'est un token expiré » ou « le MCP n'est pas configuré »
  à partir d'un symptôme indirect — vérifiez, ne devinez pas.
- Jamais en boucle : si le diagnostic est déjà tout vert, ne le relancez pas
  sans nouvelle raison.

## 5. Ce que ce script NE fait PAS (et l'exception `--probe-mcp`)

- Il n'écrit jamais rien sur le disque (pas de réindexation, pas de correction
  automatique) et n'affiche jamais le contenu d'un token — ni en table, ni en
  `--json`.
- **Par défaut**, il ne contacte pas Garmin Connect : `garmin_mcp` vérifie
  seulement que le binaire configuré existe et est exécutable. Lancer le vrai
  `garmin-mcp` déclencherait une authentification Garmin (réseau, retries,
  éventuelle réécriture des tokens) avant même de répondre en MCP — bien plus
  qu'une vérification d'installation ne doit faire. Un handshake MCP
  `initialize` réel, borné dans le temps, existe en opt-in via
  `--probe-mcp` — **ce drapeau contacte Garmin Connect** : ne le proposez à
  l'athlète que s'il demande explicitement une vérification plus poussée que
  « le binaire est-il installé ? ».
- Il ne remplace pas `/coach-setup` (configuration initiale) ni
  `scripts/setup-ntfy.sh` (configuration des notifications) — il vous dit
  seulement lequel lancer.
