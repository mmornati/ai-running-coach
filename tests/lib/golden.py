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

# ---------------------------------------------------------------------------
# Champs volatils — ignorés partout dans l'arbre, quelle que soit leur profondeur
# ---------------------------------------------------------------------------

# `scripts/arc_serve.py` ne renvoie aujourd'hui ni horodatage de génération, ni
# chemin absolu, ni port (`source_path` est déjà relatif au workspace — voir
# `scripts/arc_index.py::index_workspace` — et `today` est figé par `--today`
# dans le test). La liste reste utile de façon défensive : si une story future
# ajoute un champ de ce type à l'API, l'ignorer explicitement ici évite de
# devoir regénérer les golden à chaque exécution au lieu de détecter une vraie
# régression.
IGNORED_KEYS = {"generated_at", "indexed_at", "created_at", "port", "pid"}

# Motif d'un chemin absolu de bac à sable temporaire (macOS `/private/var/...`,
# `/var/folders/...`, Linux `/tmp/...`) — défensif, au cas où un futur endpoint
# laisserait fuiter un chemin absolu au lieu du chemin relatif au workspace.
_TMP_PATH_RE = None  # compilé paresseusement pour ne pas payer l'import re si inutile


def _tmp_path_re():
    global _TMP_PATH_RE
    if _TMP_PATH_RE is None:
        import re
        _TMP_PATH_RE = re.compile(r"^(/private)?/(tmp|var/folders)/\S+$")
    return _TMP_PATH_RE


def normalize(value: Any) -> Any:
    """Retire récursivement les clés volatiles et redacte un éventuel chemin
    absolu de bac à sable — appliqué aux deux côtés avant comparaison."""
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items() if k not in IGNORED_KEYS}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, str) and _tmp_path_re().match(value):
        return "<TMP>"
    return value


# ---------------------------------------------------------------------------
# Diff récursif
# ---------------------------------------------------------------------------


def _floats_close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def diff(expected: Any, got: Any, path: str = "$") -> list:
    """Compare `expected` à `got` (déjà passés par `normalize`) et rend la liste
    des écarts, un par ligne lisible : « <chemin> : attendu <x>, obtenu <y> »."""
    out = []
    if isinstance(expected, dict) and isinstance(got, dict):
        for key in sorted(set(expected) | set(got)):
            sub = f"{path}.{key}"
            if key not in expected:
                out.append(f"{sub} : absent du golden, présent dans la réponse ({got[key]!r})")
            elif key not in got:
                out.append(f"{sub} : attendu {expected[key]!r}, absent de la réponse")
            else:
                out.extend(diff(expected[key], got[key], sub))
    elif isinstance(expected, list) and isinstance(got, list):
        if len(expected) != len(got):
            out.append(f"{path} : longueur attendue {len(expected)}, obtenue {len(got)}")
        for i, (e, g) in enumerate(zip(expected, got)):
            out.extend(diff(e, g, f"{path}[{i}]"))
    elif _is_number(expected) and _is_number(got):
        if not _floats_close(float(expected), float(got)):
            out.append(f"{path} : attendu {expected!r}, obtenu {got!r} (tolérance rel={REL_TOL}, abs={ABS_TOL})")
    elif expected != got:
        out.append(f"{path} : attendu {expected!r}, obtenu {got!r}")
    return out


def compare(expected: Any, got: Any) -> list:
    """Point d'entrée : normalise puis diffe. Rend une liste de chaînes vide si
    identique (aux tolérances près)."""
    return diff(normalize(expected), normalize(got))


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


def dump_golden(path: Path, data: dict) -> None:
    """Formatage stable : clés triées, indentation fixe, unicode non échappé,
    une seule nouvelle ligne finale — un diff git ne bouge que ce qui change."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
