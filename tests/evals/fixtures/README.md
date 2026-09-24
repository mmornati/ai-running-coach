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
| `"401"` | Rend un résultat d'outil **normal** (pas d'erreur JSON-RPC, pas de `isError`) dont le texte imite ce que `garmin_mcp` rend RÉELLEMENT à l'expiration du token (vérifié dans le paquet vendored, `garminconnect/__init__.py` et `garmin_mcp/health_wellness.py`) : `Error retrieving data for <outil>: Authentication failed: 401 Client Error: Unauthorized for url: ...` — **sans aucun remède**. Le vrai serveur ne suggère pas `uv run garmin-mcp-auth` ; c'est à l'agent de reconnaître la panne et de l'orienter (#31/#32), pas au stub de la lui souffler. Voir `mcp_stub_common.auth_expired_text` pour la justification détaillée. |
| `"timeout"` | L'appel ne reçoit **aucune réponse**. `delay` (secondes, défaut 2) règle combien de temps le stub DORT avant de laisser tomber la requête ; une borne dure (`ARC_STUB_TIMEOUT_CAP`, défaut 10s) plafonne ce sommeil quel que soit le `delay` demandé. Cette borne ne raccourcit PAS l'attente du client en face — passé son délai, le stub ne répond toujours pas. Pour qu'un cas d'éval scriptant un timeout n'attende pas les 300s du sous-processus `claude -p`, `runner.run_case` règle `MCP_TOOL_TIMEOUT` côté client dès qu'un cas déclare `error = "timeout"`, et `subprocess.TimeoutExpired` est traité comme un échec de cas normal plutôt qu'une exception qui casserait la suite. |
| `"empty"` | Rend une liste ou un dict vide, de la même forme que la donnée canned par défaut (`[]` pour un endpoint « liste », `{}` sinon). |

`file` et `error` sont mutuellement exclusifs sur un même outil (vérifié par
`tests/evals/test_evals.py::TestCaseFilesAreValid.test_stub_section_is_well_formed`,
qui vérifie aussi que l'outil scripté existe bien dans le stub visé, et que
`file` reste sous `stub-responses/` — un `file` qui s'en évaderait
(`../../AGENTS.md`, chemin absolu) est refusé au chargement du cas comme à
l'exécution du stub).

Le fichier généré à partir de `[stub.<serveur>]` est déposé **hors du
workspace** de l'agent (à côté, pas dedans) : l'agent ne doit pas pouvoir lire
à l'avance le scénario de panne qu'on lui scripte. `ARC_STUB_CONFIG` est
toujours présente dans l'environnement de chaque stub, y compris vide, pour
qu'un export resté dans le shell de l'appelant ne puisse jamais fuiter dans un
cas qui ne script rien.

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
