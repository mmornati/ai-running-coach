# Fixtures des évals

Workspaces de démonstration, entièrement **synthétiques**. Aucune donnée réelle,
aucun compte Garmin : un scénario doit pouvoir tourner chez n'importe qui.

| Fixture | Contenu |
|---|---|
| `base-week/` | Une semaine plausible : quatre séances persistées, deux bilans santé, un objectif actif, un profil rempli. |
| `missed-session/` | Comme `base-week`, mais la séance qualité du mardi n'a jamais été faite. |
| `empty/` | Workspace nu — l'état d'un premier démarrage. |
| `configured/` | Profil et objectif déjà installés, pour tester l'idempotence. |

Les dates sont volontairement relatives dans le texte (« lundi », « mardi ») et
fixes dans les noms de fichiers : les évals ne vérifient jamais une date précise.

## Scripter les stubs MCP (`[stub]`, #26)

`tests/evals/stub_garmin_mcp.py` et `tests/evals/stub_intervals_mcp.py`
rendent des données canned « athlète reposé, rien à signaler » par défaut. Un
cas qui a besoin d'autre chose (token expiré, liste vide, HRV effondrée...)
le déclare dans une section `[stub.<serveur>.<outil>]` de son `.toml`, sans
toucher au stub lui-même :

```toml
[stub.garmin.get_hrv_data]
file = "hrv-collapsed.json"       # sert ce fichier tel quel comme réponse

[stub.garmin.get_rhr_day]
error = "401"                     # token expiré (voir plus bas)

[stub.garmin.get_activities]
error = "empty"                   # liste vide, de la même forme que la valeur canned
```

Un cas sans section `[stub]` n'a droit à aucun de ces effets : c'est le seul
comportement garanti par la non-régression (#26 n'a rien changé aux 13 cas
existants).

**Résolution de `file`** : toujours relatif à `tests/evals/fixtures/stub-responses/`
(jamais relatif au fichier du cas) — un seul endroit à connaître, quel que
soit le cas qui réutilise la fixture. `hrv-collapsed.json` y vit déjà comme
exemple pour l'épopée FIT/santé (HRV effondrée).

**Sémantique des erreurs injectées** :

| `error` | Comportement du stub |
|---|---|
| `"401"` | Rend un résultat d'outil **normal** (pas d'erreur JSON-RPC, pas de `isError`) dont le texte imite ce que `garmin_mcp` rend réellement quand `garminconnect` lève une authentification expirée : un message contenant « Authentication failed (401 Unauthorized) » et la commande de renouvellement (`uv run garmin-mcp-auth`). Ce choix privilégie la fidélité comportementale à la pureté du protocole MCP — voir `mcp_stub_common.auth_expired_text` pour la justification détaillée et la source vendored qui l'a confirmé. |
| `"timeout"` | L'appel ne reçoit **aucune réponse** — un vrai timeout côté client, pas un message d'erreur. `delay` (secondes, défaut 2) règle combien de temps le stub attend avant de laisser tomber la requête ; une borne dure (`ARC_STUB_TIMEOUT_CAP`, défaut 10s) l'empêche de dépasser une durée raisonnable même si un cas demande un `delay` excessif. |
| `"empty"` | Rend une liste ou un dict vide, de la même forme que la donnée canned par défaut (`[]` pour un endpoint « liste », `{}` sinon). |

`file` et `error` sont mutuellement exclusifs sur un même outil (vérifié par
`tests/evals/test_evals.py::TestCaseFilesAreValid.test_stub_section_is_well_formed`).

## Serveur `intervals` (#68)

`stub_intervals_mcp.py` partage tout — protocole JSON-RPC, format du journal
d'appels, mécanique `[stub.intervals.<outil>]` — avec le stub `garmin` via
`tests/evals/mcp_stub_common.py`. Le runner ne le câble dans `.mcp.json` que
si le cas déclare au moins une entrée `[stub.intervals.*]` : un scénario qui
ne teste pas la source intervals.icu n'expose pas ce serveur. Sa liste
d'outils (`get-wellness-for-date`, `get-recent-activities`,
`get-calendar-events`, ...) est une hypothèse documentée dans le module,
reprise de `eddmann/intervals-icu-mcp` — à ajuster si #68 retient un autre
serveur MCP intervals.icu.
