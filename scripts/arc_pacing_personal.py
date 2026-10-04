#!/usr/bin/env python3
"""Coefficients de pacing PERSONNELS : lecture, validation, écriture (#188, épopée #170).

## Rôle

`arc_race_debrief.py --calibrate` (#188) mesure, au débrief d'une course, l'erreur de chaque
facteur du pacing (nuit, technicité, chaleur, altitude) et PROPOSE des coefficients personnels.
Ce module est la couche de stockage : une section `[pacing.personal]` de
`config/workspace.user.toml` (jamais le fichier versionné), lue par `arc_race_pacing.py`.

```toml
[pacing.personal]
night_penalty_pct = 6.5       # pénalité de nuit à pleine nuit (défaut 5.0)
technicity_scale = 1.2        # échelle du surcoût de technicité (défaut 1.0)
heat_hot_factor = 1.14        # facteur de temps > seuil chaud (défaut 1.10)
altitude_scale = 1.1          # échelle du surcoût d'altitude (défaut 1.0, #185)
evidence = ["2026-09-27|trail-x|night|14|7.8"]   # preuves cumulées, une par course et facteur
```

## Règles

* **Jamais appliqué seul** : le fichier n'est écrit qu'après confirmation explicite de l'athlète
  (`arc_race_debrief.py --calibrate --apply`, règle de prompt du coach/stratège).
* **Les drapeaux CLI de `arc_race_pacing.py` priment** sur la config, qui prime sur le défaut.
* **Jamais fatal** : une valeur illisible ou hors bornes est IGNORÉE avec un avertissement
  (comme `[health].heat_threshold_c`), le défaut du projet s'applique.
* Sans section `[pacing.personal]`, le pacing est inchangé octet pour octet.

Stdlib uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import coach_config as CC  # noqa: E402

SECTION = "pacing.personal"

# Bornes des coefficients personnels — approximation du projet (jamais une mesure) : elles
# empêchent qu'une poignée de segments bruités ne produise un coefficient absurde.
# `night_penalty_pct` reprend `arc_race_pacing.NIGHT_PENALTY_PCT_MAX` (vérifié par un test).
BOUNDS: Dict[str, Tuple[float, float]] = {
    "night_penalty_pct": (0.0, 30.0),
    "technicity_scale": (0.25, 3.0),
    "heat_hot_factor": (1.0, 1.40),
    "altitude_scale": (0.25, 3.0),
}
KEYS = tuple(BOUNDS)

EVIDENCE_KEY = "evidence"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: Optional[str]) -> str:
    """Identifiant ASCII d'une course (clé d'idempotence des preuves)."""
    import unicodedata
    text = unicodedata.normalize("NFKD", name or "course").encode("ascii", "ignore").decode("ascii").lower()
    return _SLUG_RE.sub("-", text).strip("-") or "course"


def _to_float(raw) -> Optional[float]:
    """Nombre, ou chaîne numérique (le repli TOML < 3.11 rend les flottants en chaînes) ; jamais un
    booléen (`True` serait accepté comme 1.0)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError:
            return None
    else:
        return None
    return value if math.isfinite(value) else None


def extract_section(config: dict) -> dict:
    """`[pacing.personal]` d'une config fusionnée : sous-table imbriquée (tomllib) OU section « à
    point » du repli TOML < 3.11."""
    nested = (config.get("pacing") or {}).get("personal") if isinstance(config.get("pacing"), dict) else None
    if isinstance(nested, dict):
        return nested
    flat = config.get(SECTION)
    return flat if isinstance(flat, dict) else {}


def parse_values(section: dict) -> Tuple[Dict[str, float], List[str]]:
    """Coefficients valides de la section + avertissements pour chaque valeur ignorée."""
    values: Dict[str, float] = {}
    warnings: List[str] = []
    for key in KEYS:
        if key not in section or section[key] in (None, ""):
            continue
        value = _to_float(section[key])
        lo, hi = BOUNDS[key]
        if value is None or not (lo <= value <= hi):
            warnings.append(f"[{SECTION}].{key} = {section[key]!r} ignoré (nombre dans [{lo:g}, {hi:g}] "
                            "attendu) : défaut du projet appliqué.")
            continue
        values[key] = value
    return values, warnings


# --- Preuves cumulées ------------------------------------------------------------------------
# Un enregistrement par (course, facteur) : `AAAA-MM-JJ|slug|facteur|n|valeur`. `valeur` est
# l'estimation ABSOLUE observée par ce débrief (jamais un delta : les plans construits avec des
# réglages personnels différents restent comparables). Relancer le même débrief REMPLACE son
# enregistrement (même date, slug et facteur) au lieu de le compter deux fois.

Evidence = Tuple[str, str, str, int, float]


def format_evidence(rec: Evidence) -> str:
    date, slug, factor, n, value = rec
    return f"{date}|{slug}|{factor}|{n}|{round(value, 4)}"


def parse_evidence(raw) -> Tuple[List[Evidence], List[str]]:
    out: List[Evidence] = []
    warnings: List[str] = []
    if raw in (None, ""):
        return out, warnings
    items = raw if isinstance(raw, list) else [raw]
    for item in items:
        parts = str(item).split("|")
        n = _to_float(parts[3]) if len(parts) == 5 else None
        value = _to_float(parts[4]) if len(parts) == 5 else None
        if len(parts) != 5 or n is None or value is None or n < 1 or not parts[2]:
            warnings.append(f"[{SECTION}].evidence : entrée ignorée ({item!r}).")
            continue
        out.append((parts[0], parts[1], parts[2], int(n), value))
    return out, warnings


def merge_evidence(existing: Sequence[Evidence], new: Sequence[Evidence]) -> List[Evidence]:
    """Union dédoublonnée sur (date, course, facteur) : l'enregistrement le plus récent (`new`)
    remplace l'ancien. Ordre stable."""
    merged: Dict[Tuple[str, str, str], Evidence] = {}
    for rec in list(existing) + list(new):
        merged[(rec[0], rec[1], rec[2])] = rec
    return list(merged.values())


def read_config(config: dict) -> dict:
    """`{"values": {...}, "evidence": [...], "warnings": [...]}` depuis une config déjà fusionnée."""
    section = extract_section(config)
    values, warnings = parse_values(section)
    evidence, ev_warnings = parse_evidence(section.get(EVIDENCE_KEY))
    return {"values": values, "evidence": evidence, "warnings": warnings + ev_warnings}


def read_workspace(workspace: Path) -> dict:
    """Idem, depuis `config/workspace.toml` puis `workspace.user.toml` du workspace."""
    import arc_index as IDX
    return read_config(IDX.load_config(Path(workspace)))


def write_workspace(workspace: Path, values: Dict[str, float], evidence: Sequence[Evidence]) -> Path:
    """Écrit `[pacing.personal]` dans `config/workspace.user.toml` (jamais le fichier versionné),
    en conservant tout le reste du fichier (`coach_config.set_toml_key`, sauvegarde `.bak`).
    À n'appeler qu'APRÈS la confirmation explicite de l'athlète."""
    path = Path(workspace) / "config" / "workspace.user.toml"
    # Tout est validé AVANT la première écriture : jamais de fichier à moitié modifié.
    for key, value in values.items():
        if key not in BOUNDS:
            raise ValueError(f"coefficient inconnu : {key}")
        lo, hi = BOUNDS[key]
        if not (isinstance(value, (int, float)) and math.isfinite(value) and lo <= value <= hi):
            raise ValueError(f"{key} = {value} hors de [{lo:g}, {hi:g}]")
    # `set_toml_key` refait `.bak` à CHAQUE clé : sans ceci, la sauvegarde finale ne contiendrait
    # que l'avant-dernière étape, pas le fichier d'avant le débrief.
    original = path.read_bytes() if path.exists() else None
    for key, value in values.items():
        CC.set_toml_key(path, SECTION, key, round(float(value), 4))
    if evidence:
        CC.set_toml_key(path, SECTION, EVIDENCE_KEY, [format_evidence(r) for r in evidence])
    if original is not None and path.read_bytes() != original:
        path.with_suffix(path.suffix + ".bak").write_bytes(original)
    return path
