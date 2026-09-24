# Tests

Quatre paliers, séparés par ce qu'ils coûtent et par leur déterminisme.

```bash
python3 tests/run_tests.py --tier a     # intégration de l'installation et du tableau de bord
python3 tests/run_tests.py --tier b     # lint prompts & configuration
python3 tests/run_tests.py --tier d     # données : contrat, index dérivé, métriques
python3 tests/run_tests.py --tier c     # évals d'exécution (modèle léger)
python3 tests/run_tests.py --tier all
python3 tests/run_tests.py -k TestCrontab      # filtrer
```

Aucune dépendance à installer : `unittest` de la bibliothèque standard, comme
le reste du projet (voir `CONTRIBUTING.md`).

## Palier A — intégration de l'installation

Lance réellement `install.sh`, `setup-ntfy.sh` et `coach-remote.sh`, puis vérifie
ce qui a été écrit sur le disque.

`install.sh` écrit dans `$HOME/.config`, `$HOME/.claude.json`,
`$HOME/Library/LaunchAgents` et **la crontab de l'utilisateur**. Une suite de
tests qui toucherait l'un de ces éléments sur la machine d'un contributeur serait
pire que pas de tests. `tests/lib/sandbox.py` :

- place `HOME` dans un répertoire temporaire, et **refuse de démarrer** s'il
  désigne encore le vrai utilisateur ;
- préfixe `PATH` avec `tests/lib/stubs/` — `uv`, `curl`, `brew`, `crontab`,
  `launchctl`, `claude`… Chaque stub journalise son argv dans `$ARC_STUB_LOG`,
  ce qui permet d'affirmer *comment* un outil a été appelé ;
- copie le dépôt dans le temporaire.

Leviers disponibles dans un test :

| Levier | Effet |
|---|---|
| `ARC_STUB_FAIL=crontab` | l'outil nommé échoue (une seule sous-commande pour `crontab` : la lecture) |
| `ARC_FAKE_UNAME=Linux` | teste le chemin crontab depuis macOS, et inversement |
| `hide=("screen", "tmux")` | `PATH` réduit d'où ces binaires sont absents |
| `sb.run_pty(argv, answers=[…])` | vrai terminal, pour tout ce qui est derrière `[[ -t 0 ]]` |
| `sb.tree()` | empreinte d'arborescence, pour l'idempotence et `--dry-run` |

Chaque cas nomme le défaut qu'il verrouille. Pour en ajouter un, partez de
`tests/install/test_install_regressions.py`.

**Tests ignorés.** `TestCoachRemote` s'ignore là où `screen` ou `tmux` existe
dans `/opt/homebrew/bin` ou `/usr/local/bin` : `coach-remote.sh` rajoute ces
dossiers au `PATH`, donc « aucun gestionnaire de services » n'y est pas une
situation atteignable. Le motif fautif reste verrouillé par le palier B, lui
indépendant de la machine.

## Palier B — lint des prompts et de la configuration

Aucun modèle, aucun réseau, quelques millisecondes. Vérifie le frontmatter des
agents et des skills, la résolution de **tout chemin cité dans un prompt**, la
parité des surfaces (Gemini, docs, navigation mkdocs), la fraîcheur des fichiers
générés et l'hygiène des scripts shell. `test_docker.py` y verrouille les
invariants du conteneur du tableau de bord (aucun port publié, workspace en
lecture seule, middleware d'authentification obligatoire, utilisateur non root) ;
la CI construit en plus l'image et l'interroge (job « Docker »).

C'est ce palier qui attrape la classe de bug ayant produit
`planning/Runner_Profile.md` : un chemin cité par trois fichiers d'instructions
et qui n'existait nulle part.

## Palier C — évals d'exécution des prompts

Lance les agents sur un workspace de démonstration avec un modèle léger et
vérifie des **comportements**, pas des tournures : les appels d'outils observés,
les fichiers créés, la présence ou l'absence de notions précises.

Non déterministe et facturé. Ignoré sauf si `ARC_LLM_TESTS=1` et que le runner
est authentifié — sans quoi les cas sont *ignorés*, jamais en échec.

Le serveur MCP factice (`tests/evals/stub_garmin_mcp.py`, et son pendant
`stub_intervals_mcp.py` pour la story source intervals.icu, #68) rend des
données canned stables par défaut, mais un cas peut scripter ses réponses
outil par outil — fichier de remplacement ou panne injectée (token expiré,
timeout, liste vide) — via une section `[stub.<serveur>.<outil>]` de son
`.toml`. Détail complet, sémantique des erreurs et exemples dans
`tests/evals/fixtures/README.md`. Les deux stubs partagent leur protocole
JSON-RPC via `tests/evals/mcp_stub_common.py`, verrouillé par le palier D
(`tests/data/test_mcp_stubs.py`).

```bash
ARC_LLM_TESTS=1 python3 tests/run_tests.py --tier c --repeat 3
```

Chaque cas est répété N fois et passe sur un seuil, pas à l'unanimité. Le dernier
relevé est versionné dans `tests/evals/RESULTS.md` : une régression se lit alors
dans un diff.

### Nouvelles assertions sur les contenus d'arc et les arguments d'outils (#27)

Quatre assertions permettent de vérifier le **contenu** des fichiers générés et des
appels d'outils — pas seulement leur existence ou leur type :

#### `arc_field` — extraire et vérifier un champ du bloc ```arc

Extrait un champ du bloc ```` ```arc ```` d'un fichier et le compare à une valeur
attendue. Syntaxe de chemin JSON : clés pointées (`foo.bar`), indices (`items[0]`),
caractères génériques (`items[*].intensity`).

Comparateurs : `equals`, `min`, `max`, `in`.

```toml
[[expect.arc_field]]
glob = "activities/*.md"      # Tous les fichiers d'activité
path = "distance_m"            # Chemin JSON au champ
min = 5000                      # Distance ≥ 5 km
```

```toml
[[expect.arc_field]]
glob = "planning/Semaine_*.md"  # Semaines
path = "sessions[*].intensity"  # Tous les niveaux d'intensité
in = [5, 6, 7]                  # Seulement 5, 6 ou 7
```

#### `tool_args_match` — vérifier les arguments d'un appel d'outil

Vérifie que l'outil nommé a été appelé avec des arguments satisfaisant une condition.
Même syntaxe de chemin que `arc_field`.

Comparateurs : `equals`, `min`, `max`, `regex`. Optionnel : `server` pour filtrer par
serveur MCP.

```toml
[[expect.tool_args_match]]
tool = "get_activities"         # Outil MCP
path = "days"                   # Arguments.days
equals = 7
```

```toml
[[expect.tool_args_match]]
tool = "get_health"
server = "garmin"
path = "metric"
regex = "hrv.*"                 # Matches "hrv_overnight", "hrv_baseline", …
```

#### `sqlite_query` — requête SELECT sur l'index du workspace

Indexe le workspace en SQLite (lecture seule) et exécute une requête SELECT — utile
pour vérifier des agrégats (nombre de séances par semaine, charge totale du mois…).

Comparateurs : `equals`, `min`, `max`.

```toml
[[expect.sqlite_query]]
sql = "SELECT COUNT(*) FROM activity WHERE sport = 'running' AND date >= '2026-09-01'"
equals = 5
```

#### `file_contains_any` — vérifier qu'un fichier contient au moins une notion

Parcourt les fichiers correspondant au glob et vérifie qu'au moins un contient au
moins une des notions listées (case-insensitive, recherche de sous-chaîne).

```toml
[[expect.file_contains_any]]
glob = "rapports/*.md"
any = ["bilan hebdomadaire", "résumé", "synthèse"]
```

## Palier D — données

Tests unitaires purs, sans sous-processus : le contrat ```` ```arc ````
(`scripts/arc_contract.py` contre `skills/workspace-data-contract/SKILL.md`), la
lecture des fichiers antérieurs au contrat (`scripts/arc_legacy.py`, sur les
fixtures d'évals), l'index SQLite dérivé et les métriques (TRIMP, condition/fatigue/forme,
VDOT) sur des valeurs de référence.

Plusieurs cas viennent d'un vrai workspace de plusieurs mois et portent le nom du
défaut qu'ils verrouillent : doublon d'une même séance Garmin, fichier d'analyse
pris pour une séance, dernier split partiel pris pour un record, ultra marché qui
fausse la VO2max. `tests/lib/synthetic.py` fabrique un workspace au contrat pour
les tests de bout en bout du palier A et pour essayer le tableau de bord :

```bash
python3 -m tests.lib.synthetic /tmp/demo --days 120
ARC_WORKSPACE=/tmp/demo scripts/dashboard.sh
```

### Échantillons seconde par seconde (`sample_session`, story #25)

Toute l'épopée FIT (zones #43, GAP #44, découplage #45, VAM #46, descente #47,
durabilité #48, modèle pente→allure #58) a besoin de séries seconde par
seconde à **vérité connue**. `tests.lib.synthetic.sample_session(...)` en
génère une, avec des propriétés paramétrées (segments montée/descente,
dérive FC/découplage imposée, répartition de zones FC imposée, fade de fin de
séance, trous de signal) et renvoie, à côté des échantillons, un dict
`truth`. **Toute valeur mesurée de `truth` est recalculée après coup depuis
la liste `records` finale**, jamais depuis un tableau interne pré-troncature
— un trou de signal ou une pente ne peut donc jamais fausser une mesure sans
que ce soit visible dans les données réellement émises.

Le découplage (Pa:HR, #45) et le fade (#48) sont mesurés sur le GAP (vitesse
ajustée à la pente), pas la vitesse brute — sinon une montée ou une descente
fausserait la mesure. `tests/data/test_synthetic_samples.py` vérifie D+/D−,
dérive, zones, fade, courbe pente→allure, déterminisme octet pour octet, et
recalcule certaines mesures de façon indépendante pour prouver qu'il n'y a
pas d'incohérence entre `truth` et `records`.

Champs d'un échantillon : `t_s, distance_m, altitude_m, hr_bpm, speed_ms,
cadence_spm` — **format normalisé**, aligné sur le schéma `activity_sample`
de `scripts/arc_index.py`. Ce n'est **pas** le format brut de
`skills/fit-download/scripts/download_fit.py` (qui dumpe les champs
`fitparse` tels quels : `timestamp`, `distance`, `heart_rate`,
`enhanced_altitude`/`altitude`, `enhanced_speed`/`speed`, `cadence`) : c'est
le format que l'ingestion FIT (story #42) devra produire en sortie de sa
normalisation. Pas de `lat`/`lon` : inutiles aux KPI de l'épopée et ça évite
tout risque de lieu réel (vérifié par `tests/lint/test_synthetic_no_real_data.py`).

Zones FC par défaut : méthode Karvonen sur la FC repos/max du profil type
(`HR_REST`/`HR_MAX` — voir `planning/Runner_Profile.md`), pas des bornes
arbitraires ; la story #43 rendra la méthode configurable par profil.

```bash
python3 -m tests.lib.synthetic /tmp/demo --days 120 --with-samples
# -> /tmp/demo/activities/fit/<garmin_activity_id>.json  ({"activity_id", "records", "truth"})
```

`--with-samples` calibre la distance, le D+/D− et la FC moyenne des
échantillons pour qu'ils restent cohérents avec le Markdown de la même
séance (`tests/data/test_synthetic_samples.py::TestMarkdownAgreement`), tout
en gardant des vitesses plausibles (`TestPlausibleSpeeds` : pas d'allure
au-delà de ~7 m/s, ni de vitesse « à plat » hors d'une plage d'endurance
réaliste) — un budget de pente trop étroit forcerait sinon la calibration
vers des allures de sprint pour tenir la distance visée.

