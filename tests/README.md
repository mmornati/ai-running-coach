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

### Instantanés « golden » de l'API du tableau de bord (#28)

`tests/install/test_dashboard_golden.py` construit un workspace synthétique à
date et graine figées (`tests/lib/synthetic.py`, `--today` + `seed`), lance
`scripts/arc_serve.py` pour de vrai (même infrastructure que
`test_dashboard.py` : `Sandbox`, `Server`), interroge les routes JSON de
`arc_serve.ROUTES` — dérivées à l'exécution, jamais d'une liste recopiée à la
main, pour qu'une route ajoutée sans golden fasse échouer la comparaison
plutôt que de passer inaperçue (preuve avec un vrai serveur dans
`TestGoldenDetectsNewRoute`, qui ajoute une route factice en process et
restaure `ROUTES` via `addCleanup`) — plus la route paramétrée
`/api/activity/<id>` (routée à part par une expression régulière, donc **hors**
de `ROUTES` : ajoutée ici explicitement, faute de pouvoir l'énumérer sans
dupliquer cette regex) et quelques appels paramétrés représentatifs (fenêtre
courte, un rapport précis). Compare au JSON de
`tests/data/golden/dashboard_api_<sport>.json` (deux profils, `trail` et
`road`, chacun empruntant un chemin de calcul différent dans
`scripts/arc_metrics.py::predictions`).

La comparaison (`tests/lib/golden.py`) est récursive et tolérante aux
flottants (`rel_tol=1e-6`, `abs_tol=1e-9` — du bruit de représentation IEEE
754 entre deux exécutions identiques, jamais de quoi changer une décision,
deux `NaN` issus du même calcul déterministe comptant comme égaux) ; un écart
produit une ligne par champ, avec le chemin JSON
(`$.body.series[3].distance_m`), la valeur attendue et la valeur obtenue — la
sortie est plafonnée à 50 lignes (`… N autres écarts (tronqué)`). Un booléen
n'est jamais confondu avec `0`/`1`, et un entier qui se met à sortir en
flottant (ou l'inverse, ex. `5000` vs `5000.0`) est rapporté comme un
changement de forme JSON même si la valeur numérique est égale. La liste des
clés ignorées à toute profondeur (`IGNORED_KEYS`) est **volontairement vide** :
`arc_serve.py` n'émet aujourd'hui aucun champ non déterministe (`source_path`
est déjà relatif au workspace, `today` est figé par `--today`) et ignorer une
clé *par son nom* masquerait pour toujours un futur champ légitime qui
porterait ce nom par malchance — une vraie clé volatile future devrait plutôt
être exclue par un chemin JSON précis, endpoint par endpoint. Pour la même
raison, un chemin absolu du bac à sable de test qui fuiterait dans une réponse
n'est **pas** normalisé avant comparaison (une redaction l'aurait fait
disparaître des deux côtés et l'aurait rendu indétectable une fois figé dans
le golden) : `test_matches_golden` vérifie explicitement qu'aucune chaîne de
la réponse ne contient le chemin du bac à sable courant, avant même de
comparer au golden. `dump_golden()` écrit les données déjà normalisées, pour
que le golden versionné reflète exactement ce que `compare()` compare.

Régénération volontaire (après un changement de forme JSON assumé, jamais pour
faire taire un échec inexpliqué) :

```bash
ARC_UPDATE_GOLDEN=1 python3 tests/run_tests.py -k Golden
```

En mode régénération, un statut HTTP différent de 200 (sauf le 404 attendu de
la route sans paramètre `/api/report`, qui n'a alors aucun rapport à
résoudre) fait échouer le test plutôt que de figer une route en échec dans le
golden.

Un diff attendu dans une revue est un ajout/retrait de champ cohérent avec le
changement de code, ou une valeur qui bouge dans le sens attendu (nouvelle
métrique, nouveau calcul) — jamais un déplacement de dates ou d'identifiants
d'activité : le workspace est déterministe (graine et date figées), donc tout
mouvement inattendu de ces valeurs signale un bug d'ordonnancement.

**Budget de taille.** Le workspace synthétique est volontairement court (40
jours, ~28 séances) — assez pour que `/api/form`, `/api/health` etc. aient une
série non triviale, assez peu pour que les deux fichiers golden pèsent environ
120 Ko chacun (~240 Ko à eux deux). `/api/health` sans paramètre (fenêtre par
défaut fixe de 90 jours, indépendante de la taille du workspace — voir
`scripts/arc_serve.py::api_health`) est la plus grosse route individuelle,
environ 28 % du volume total — loin d'en être la majorité.

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

### CI planifiée, sur demande, ou sur étiquette de PR (#29)

`.github/workflows/evals.yml` déclenche ce palier de trois façons, toutes
pensées pour plafonner le coût (jetons, minutes CI) et ne jamais exposer
`ANTHROPIC_API_KEY` à du code non fiable :

| Déclencheur | Quand | Paramètres |
|---|---|---|
| `schedule` | chaque lundi 03:17 UTC | modèle et répétitions par défaut |
| `workflow_dispatch` (onglet Actions) | à la demande | `repeat`, `model`, `cases` (filtre `-k`, vide = tous) |
| étiquette `run-evals` sur une PR | à la pose de l'étiquette (jamais à chaque push suivant) | par défaut |

Poser l'étiquette est l'acte d'approbation d'un mainteneur — jamais automatique,
et jamais sur `synchronize` : retirer puis reposer l'étiquette relance
volontairement les évals après un correctif, sans que chaque commit d'une PR
déjà étiquetée ne reparte pour un tour. Une PR de fork ne reçoit de toute façon
aucun secret sur cet événement ; une garde explicite (`head.repo.full_name`)
l'exclut quand même du déclenchement, en défense en profondeur.

Secret absent (`ANTHROPIC_API_KEY` non réglé — fork, ou dépôt fraîchement
installé) : chaque cas est simplement *ignoré*, jamais en échec, comme en
local (voir `runner.looks_unauthenticated`).

Le job publie deux artefacts (journal brut, et un `RESULTS.md` régénéré par
`tests/evals/render_results.py` depuis les taux de réussite du run — voir
docstring du module) et, uniquement pour les PR étiquetées, poste ce même
`RESULTS.md` en commentaire, depuis un second job qui ne porte
`pull-requests: write` que lui, et qui n'exécute lui-même ni prompt ni outil
MCP : il republie tel quel un fichier déjà produit par le premier job. Une
régression de taux de réussite par rapport au `RESULTS.md` **versionné** est
annotée `⚠️ régression` directement dans ce commentaire (voir
`render_results.parse_previous`). Ce `RESULTS.md` généré par la CI n'est
jamais committé automatiquement : régénérer le relevé de référence reste un
geste manuel (commande ci-dessus, ou téléchargement de l'artefact
`evals-results` produit par le job), à la main d'un mainteneur qui en valide
le contenu.

### Nouvelles assertions sur les contenus d'arc et les arguments d'outils (#27)

Quatre assertions permettent de vérifier le **contenu** des fichiers générés et des
appels d'outils — pas seulement leur existence ou leur type. Chacune prend
**exactement un** comparateur.

Syntaxe de chemin JSON commune à `arc_field` et `tool_args_match` : clés pointées
(`foo.bar`), indices (`items[0]`, `items[-1]`), caractères génériques (`items[*].x`).
Un chemin syntaxiquement invalide (`items[abc]`, `items[0`, `a.b.`) fait échouer le
cas au chargement, pas seulement à l'exécution.

**Sémantique TOUT, jamais AU MOINS UN.** `arc_field` et un `[*]` dans
`tool_args_match` exigent que **toutes** les valeurs résolues satisfassent **tous**
les comparateurs — une seule séance non conforme dans une semaine de cinq fait
échouer l'assertion, même si les quatre autres sont bonnes. Un chemin qui ne résout
à rien (clé absente, indice hors limites) est un échec à part entière, distinct
d'une valeur qui ne satisfait pas le comparateur.

Sauf mention contraire, les fichiers considérés sont ceux **écrits pendant le run**
(présents dans le workspace mais absents de la fixture de départ) — un fichier déjà
là avant l'exécution ne prouve rien sur ce que l'agent a fait.

#### `arc_field` — extraire et vérifier un champ du bloc ```arc

Extrait un champ du bloc ```` ```arc ```` de **chaque** fichier écrit pendant le run
et correspondant au glob, et vérifie que toutes les valeurs résolues satisfont le
comparateur (voir schéma complet dans `scripts/arc_contract.py` /
`skills/workspace-data-contract/SKILL.md`).

Comparateurs (un seul par assertion) : `equals`, `min`, `max`, `in`.

```toml
[[expect.arc_field]]
glob = "activities/*.md"       # Tous les fichiers d'activité ÉCRITS par le run
path = "distance_m"             # Chemin JSON au champ (nombre, mètres)
min = 5000                       # Distance ≥ 5 km, pour CHAQUE fichier
```

```toml
[[expect.arc_field]]
glob = "planning/Semaine_*.md"           # Semaines écrites par le run
path = "sessions[*].intensity"            # Intensité de CHAQUE séance de CHAQUE fichier
in = ["endurance", "tempo", "threshold"]  # Valeurs valides de l'énum `intensity`
                                           # (scripts/arc_contract.py : INTENSITY)
```

#### `tool_args_match` — vérifier les arguments d'un appel d'outil

Vérifie qu'**au moins un** appel de l'outil nommé a des arguments satisfaisant la
condition — mais, dans un appel donné, un `[*]` sur ses arguments exige que
**toutes** les valeurs résolues satisfassent (un appel qui planifie cinq séances
dont une hors gabarit ne « passe » pas parce que les quatre autres sont bonnes).
« L'outil n'a jamais été appelé » et « appelé, mais le chemin ne résout à rien dans
ses arguments » sont deux messages d'échec distincts.

Comparateurs (un seul par assertion) : `equals`, `regex`, `min`, `max`. Optionnel :
`server` (`garmin` | `intervals`) pour ne considérer que les appels à ce serveur.
`tool` doit être un nom d'outil réellement exposé par le stub visé — voir
`tests/evals/stub_garmin_mcp.py`/`stub_intervals_mcp.py` (`TOOLS`) pour la liste.

```toml
[[expect.tool_args_match]]
tool = "get_scheduled_workouts"   # Outil garmin (skills/garmin-workout-scheduling)
path = "start_date"                # Arguments.start_date
regex = "^\\d{4}-\\d{2}-\\d{2}$"    # Format AAAA-MM-JJ
```

```toml
[[expect.tool_args_match]]
tool = "schedule_workouts"
server = "garmin"
path = "schedules[*].calendar_date"   # Chaque séance planifiée dans l'appel
regex = "^2026-09-2[0-9]$"             # Toutes tombent dans la semaine visée
```

#### `sqlite_query` — requête SELECT (lecture seule) sur l'index du workspace

Indexe le workspace en SQLite (une seule fois par cas, quel que soit le nombre de
`sqlite_query` du cas) puis exécute une requête sur une connexion ouverte
**explicitement en lecture seule** (`mode=ro` + `PRAGMA query_only`) — utile pour
vérifier des agrégats (nombre de séances par semaine, charge totale du mois…) sans
jamais pouvoir modifier l'index. Une seule instruction de lecture (`SELECT` ou
`WITH … SELECT`, commentaires `-- …` de tête tolérés) ; toute tentative d'écriture
est refusée par la connexion elle-même, pas seulement par un contrôle textuel — ce
dernier n'est qu'un diagnostic plus lisible en cas d'abus évident, et sa recherche
naïve du `;` a une limite connue : une requête par ailleurs valide comme
`SELECT ';'` (un `;` dans un littéral) ou précédée d'un commentaire `/* … */` (au
lieu de `-- …`) sera refusée à tort par ce contrôle. Écrivez plutôt vos requêtes
sans point-virgule littéral et avec des commentaires `-- …` si besoin.

Comparateurs (un seul par assertion) : `equals`, `min`, `max`. La comparaison porte
sur la **première colonne de la première ligne** ; « aucune ligne » et « `NULL` »
sont deux échecs distincts et explicites (ni l'un ni l'autre n'est traité comme 0).

```toml
[[expect.sqlite_query]]
sql = "SELECT COUNT(*) FROM activity WHERE sport = 'running' AND date >= '2026-09-01'"
equals = 5
```

```toml
[[expect.sqlite_query]]
sql = """
WITH by_week AS (SELECT strftime('%W', date) AS wk, SUM(distance_m) AS d FROM activity GROUP BY wk)
SELECT MAX(d) FROM by_week
"""
min = 20000
```

#### `file_contains_any` — vérifier qu'un fichier contient au moins une notion

Parcourt les fichiers **écrits pendant le run** correspondant au glob et vérifie
qu'au moins un contient au moins une des notions listées (case-insensitive,
recherche de sous-chaîne — pas de regex ici, volontairement, pour rester lisible
par un non-développeur qui écrirait un cas).

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

