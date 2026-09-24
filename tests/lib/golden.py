"""Comparaison « golden » : instantanés JSON avec tolérance sur les flottants.

Utilisé par `tests/install/test_dashboard_golden.py` (#28) pour détecter toute
dérive de valeur ou de forme dans l'API `/api/*` de `scripts/arc_serve.py` sans
écrire une assertion par champ.

Format des fichiers golden (`tests/data/golden/*.json`) :

    {
      "_meta": {"today": "AAAA-MM-JJ", "seed": 12345, "days": 40, "sport": "trail"},
      "endpoints": {"/api/summary": {...}, "/api/form?days=14": {...}, ...}
    }

`_meta` documente les paramètres qui ont produit l'instantané (utile en revue
de diff) mais n'est **pas** comparé par `compare()` : seul `endpoints` l'est.

Régénération volontaire : `ARC_UPDATE_GOLDEN=1 python3 tests/run_tests.py -k Golden`.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Tolérance flottants
# ---------------------------------------------------------------------------

# Les métriques (`scripts/arc_metrics.py`) sont des sommes/moyennes de flottants
# SI (mètres, secondes) : deux exécutions identiques ne divergent qu'aux derniers
# bits de la représentation IEEE 754, jamais de quoi changer une décision. La
# tolérance relative absorbe ce bruit sur les grandes valeurs (distances
# cumulées) ; l'absolue couvre les valeurs proches de zéro (charge nulle, ACWR
# non défini) où la relative n'aurait aucun sens.
REL_TOL = 1e-6
ABS_TOL = 1e-9

# Nombre maximal de lignes de diff rendues par `compare()` — une régression
# structurelle (ex. clé renommée dans une liste de 200 activités) peut produire
# des centaines de lignes ; au-delà, la revue n'apporte plus rien et un rapport
# tronqué reste exploitable.
MAX_DIFF_LINES = 50

# ---------------------------------------------------------------------------
# Champs volatils — ignorés partout dans l'arbre, quelle que soit leur profondeur
# ---------------------------------------------------------------------------

# Volontairement VIDE : `scripts/arc_serve.py` ne renvoie aujourd'hui aucun
# champ non déterministe (ni horodatage de génération, ni port, ni chemin
# absolu — `source_path` est déjà relatif au workspace, voir
# `scripts/arc_index.py::index_workspace`, et `today` est figé par `--today`
# dans le test). Ignorer une clé *par son nom, à toute profondeur* est un
# outil dangereux : un futur champ légitime qui porterait par malchance un nom
# de cette liste (ex. un `port` métier sans rapport avec le serveur HTTP)
# serait masqué silencieusement pour toujours. Si un vrai champ volatil
# apparaît un jour, préférez une exclusion précise — un chemin JSON explicite
# par endpoint (`/api/xxx` → `body.generated_at`) — plutôt que d'ajouter son
# nom ici.
IGNORED_KEYS: set = set()


def normalize(value: Any) -> Any:
    """Retire récursivement les clés de `IGNORED_KEYS` (aujourd'hui aucune).

    N'altère PAS les chaînes : un chemin absolu de bac à sable qui fuiterait
    dans une réponse doit rester visible tel quel — voir
    `tests/install/test_dashboard_golden.py::_assert_no_leaked_sandbox_paths`,
    qui échoue précisément là-dessus plutôt que de le faire disparaître ici
    (un tel chemin, une fois écrit dans le golden par erreur, serait sinon
    « normalisé » des deux côtés et ne serait plus jamais détecté)."""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in IGNORED_KEYS}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Diff récursif
# ---------------------------------------------------------------------------


def _floats_close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)


def _kind(v: Any):
    """Distingue bool / int / float d'un JSON déjà chargé (`bool` est une
    sous-classe d'`int` en Python : il faut le tester en premier). Rend `None`
    pour tout le reste (str, dict, list, None)."""
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    return None


def _leaf_diff(expected: Any, got: Any, path: str) -> list:
    eknd, gknd = _kind(expected), _kind(got)
    if eknd is not None or gknd is not None:
        # Au moins un côté est un booléen ou un nombre : un booléen ne doit
        # jamais être confondu avec 1/0, et int↔float est un changement de
        # forme JSON même à valeur numériquement égale (5000 vs 5000.0) — un
        # champ qui se met à sortir un flottant là où il sortait un entier
        # signale un changement de calcul, pas du bruit.
        if eknd != gknd:
            what = "booléen" if "bool" in (eknd, gknd) else "type JSON"
            return [f"{path} : {what} changé ({eknd or type(expected).__name__} → "
                    f"{gknd or type(got).__name__}) : attendu {expected!r}, obtenu {got!r}"]
        if eknd == "bool":
            return [] if expected == got else [f"{path} : attendu {expected!r}, obtenu {got!r}"]
        # eknd == gknd, tous deux "int" ou "float"
        if isinstance(expected, float) and isinstance(got, float) and math.isnan(expected) and math.isnan(got):
            return []  # deux NaN d'un même calcul déterministe : pas une régression
        if not _floats_close(expected, got):
            return [f"{path} : attendu {expected!r}, obtenu {got!r} (tolérance rel={REL_TOL}, abs={ABS_TOL})"]
        return []
    if expected != got:
        return [f"{path} : attendu {expected!r}, obtenu {got!r}"]
    return []


def _diff_list(expected: list, got: list, path: str) -> list:
    out = []
    common = min(len(expected), len(got))
    for i in range(common):
        out.extend(diff(expected[i], got[i], f"{path}[{i}]"))
    for i in range(common, len(expected)):
        out.append(f"{path}[{i}] : absent de la réponse (attendu {expected[i]!r})")
    for i in range(common, len(got)):
        out.append(f"{path}[{i}] : présent dans la réponse, absent du golden ({got[i]!r})")
    return out


def diff(expected: Any, got: Any, path: str = "$") -> list:
    """Compare `expected` à `got` (déjà passés par `normalize`) et rend la liste
    des écarts, un par ligne lisible : « <chemin> : attendu <x>, obtenu <y> »."""
    if isinstance(expected, dict) and isinstance(got, dict):
        out = []
        for key in sorted(set(expected) | set(got)):
            sub = f"{path}.{key}"
            if key not in expected:
                out.append(f"{sub} : absent du golden, présent dans la réponse ({got[key]!r})")
            elif key not in got:
                out.append(f"{sub} : attendu {expected[key]!r}, absent de la réponse")
            else:
                out.extend(diff(expected[key], got[key], sub))
        return out
    if isinstance(expected, list) and isinstance(got, list):
        return _diff_list(expected, got, path)
    return _leaf_diff(expected, got, path)


def compare(expected: Any, got: Any) -> list:
    """Point d'entrée : normalise puis diffe, tronqué à `MAX_DIFF_LINES`. Rend
    une liste de chaînes vide si identique (aux tolérances près)."""
    lines = diff(normalize(expected), normalize(got))
    if len(lines) > MAX_DIFF_LINES:
        return lines[:MAX_DIFF_LINES] + [f"… {len(lines) - MAX_DIFF_LINES} autres écarts (tronqué)"]
    return lines


# ---------------------------------------------------------------------------
# Lecture / écriture des fichiers golden
# ---------------------------------------------------------------------------

UPDATE_ENV = "ARC_UPDATE_GOLDEN"


def update_requested() -> bool:
    return os.environ.get(UPDATE_ENV) == "1"


def load_golden(path: Path):
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def dump_golden(path: Path, meta: dict, endpoints: dict) -> None:
    """Formatage stable : clés triées, indentation fixe, unicode non échappé,
    une seule nouvelle ligne finale — un diff git ne bouge que ce qui change.

    `endpoints` est passé par `normalize()` avant écriture : le golden versionné
    doit refléter ce que `compare()` compare réellement, pas l'instantané brut
    (sinon une clé future ajoutée à `IGNORED_KEYS` resterait figée dans les
    fichiers existants au lieu d'en disparaître à la prochaine régénération)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"_meta": meta, "endpoints": normalize(endpoints)}
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
