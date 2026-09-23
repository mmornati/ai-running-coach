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
générés et l'hygiène des scripts shell.

C'est ce palier qui attrape la classe de bug ayant produit
`planning/Runner_Profile.md` : un chemin cité par trois fichiers d'instructions
et qui n'existait nulle part.

## Palier C — évals d'exécution des prompts

Lance les agents sur un workspace de démonstration avec un modèle léger et
vérifie des **comportements**, pas des tournures : les appels d'outils observés,
les fichiers créés, la présence ou l'absence de notions précises.

Non déterministe et facturé. Ignoré sauf si `ARC_LLM_TESTS=1` et que le runner
est authentifié — sans quoi les cas sont *ignorés*, jamais en échec.

```bash
ARC_LLM_TESTS=1 python3 tests/run_tests.py --tier c --repeat 3
```

Chaque cas est répété N fois et passe sur un seuil, pas à l'unanimité. Le dernier
relevé est versionné dans `tests/evals/RESULTS.md` : une régression se lit alors
dans un diff.

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

