#!/usr/bin/env python3
"""Fiches de caractéristiques des chaussures (#298, épopée #297) : provenance, valeur retenue,
écart entre sources et index minimaliste d'Esculier.

Lit les fiches `gear/specs/<gear_id>.md` (type `shoe_spec` du contrat de données, voir
`skills/workspace-data-contract/SKILL.md`) telles qu'indexées par `arc_index.py` ; n'écrit rien,
n'appelle aucun réseau. La saisie assistée (recherche web, validation ligne par ligne par
l'athlète) est décrite dans `skills/shoe-specs/SKILL.md` : ce module n'en est que la partie
déterministe.

Règles :
- une valeur absente reste absente — jamais reprise d'un modèle voisin ;
- `measured` (labo) prime sur `manufacturer` (marque) ; `athlete` (valeur validée ou corrigée par
  l'athlète) prime sur les deux ;
- l'index minimaliste est incalculable (et le dit) si une entrée manque.

Bibliothèque standard uniquement.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_contract as C  # noqa: E402

# ---------------------------------------------------------------------------
# Index minimaliste (Esculier et al. 2015)
# ---------------------------------------------------------------------------

MI_REFERENCE = {
    "citation": "Esculier et al. 2015, J Foot Ankle Res 8:42 (échelle de notation du minimalisme).",
    "url": "https://jfootankleres.biomedcentral.com/articles/10.1186/s13047-015-0094-5",
    "pmc": "PMC4543477",
    "grid": "Fichier additionnel 1 de l'article (« Minimalist Index », PDF d'une page par sous-échelle)",
}

# Seuils INFÉRIEURS inclus de chaque tranche : score = 5 - (nombre de seuils <= valeur).
# Poids : 5 = moins de 125 g, 4 = 125 à moins de 175 g, ... 0 = 325 g et plus. Hauteur de talon (stack) :
# 5 = moins de 8 mm ... 0 = 32 mm et plus. Drop : 5 = moins de 1 mm ... 0 = 13 mm et plus.
MI_WEIGHT_EDGES_G = (125.0, 175.0, 225.0, 275.0, 325.0)
MI_STACK_EDGES_MM = (8.0, 14.0, 20.0, 26.0, 32.0)
MI_DROP_EDGES_MM = (1.0, 4.0, 7.0, 10.0, 13.0)
MI_SUBSCORE_MAX = 5
MI_SUBSCORES = ("weight", "stack_height", "heel_toe_drop", "flexibility", "stability")
MI_MAX_SUM = MI_SUBSCORE_MAX * len(MI_SUBSCORES)   # 25

MI_ASSUMPTIONS = (
    "Grille et formule : Esculier et al. 2015 (J Foot Ankle Res 8:42), fichier additionnel 1 — cinq "
    "sous-échelles de 0 à 5 (5 = plus minimaliste), somme multipliée par 4 = pourcentage (somme / 25 x 100).",
    "L'article mesure le poids de la chaussure, la hauteur de talon au pied à coulisse au milieu du talon "
    "et le drop comme talon moins avant-pied sous les têtes métatarsiennes ; les valeurs d'une fiche "
    "(marque ou laboratoire) en sont une approximation du projet : taille de référence et point de mesure "
    "peuvent différer.",
    "Flexibilité (longitudinale + torsionnelle, chacune 0 à 2,5 par pas de 0,5) et dispositifs de "
    "stabilité/contrôle du mouvement (0 à 6 : semelle intermédiaire multi-densité, ponton médial "
    "thermoplastique, contrefort rigide, voûte médiale surélevée, tige médiale tendue, évasement médial) "
    "n'ont pas de champ « fabricant » : ce sont des évaluations manuelles de l'athlète, saisies avec leur "
    "provenance ; sans elles l'index n'est pas calculé.",
    "Un index n'est pas un verdict : il situe la chaussure sur l'échelle du minimalisme pour mesurer un "
    "changement entre deux paires (épopée #297) ; ce n'est pas un avis médical.",
)


def _edge_score(value: float, edges) -> int:
    return MI_SUBSCORE_MAX - sum(1 for edge in edges if value >= edge)


def weight_subscore(weight_g: float) -> int:
    """Poids : 5 = moins de 125 g ... 0 = 325 g et plus."""
    return _edge_score(weight_g, MI_WEIGHT_EDGES_G)


def stack_subscore(stack_heel_mm: float) -> int:
    """Hauteur de talon : 5 = moins de 8 mm ... 0 = 32 mm et plus."""
    return _edge_score(stack_heel_mm, MI_STACK_EDGES_MM)


def drop_subscore(drop_mm: float) -> int:
    """Drop : 5 = moins de 1 mm ... 0 = 13 mm et plus (un drop négatif vaut 5)."""
    return _edge_score(drop_mm, MI_DROP_EDGES_MM)


def stability_subscore(devices: int) -> int:
    """Dispositifs de stabilité : 5 = aucun, 4 = 1, 3 = 2, 2 = 3, 1 = 4, 0 = 5 ou 6."""
    return max(0, MI_SUBSCORE_MAX - int(devices))


def flexibility_subscore(longitudinal: float, torsional: float) -> float:
    """Flexibilité : somme des deux sous-notes (chacune 0 à 2,5 par pas de 0,5), donc 0 à 5."""
    return float(longitudinal) + float(torsional)


# Pointure de référence attendue du poids : US homme 9 (convention des comparatifs de laboratoire ;
# le fichier additionnel de l'article ne la précise pas — approximation du projet).
_US_M9_RE = re.compile(r"^(us)?(m|men|mens)?9$")


def is_us_m9(reference_size) -> bool:
    """« US 9 », « US M9 », « US men's 9 », « M9 »... — US homme 9 (la pointure sans genre précisé est lue homme)."""
    if not isinstance(reference_size, str):
        return False
    return bool(_US_M9_RE.match(re.sub(r"[\s.'’\-]", "", reference_size.lower())))


def _weight_reference_warnings(spec: dict) -> List[str]:
    entry = spec.get("weight_g")
    if not isinstance(entry, dict) or entry.get("value") is None:
        return []
    ref = entry.get("reference_size")
    if ref is None:
        return ["pointure de référence du poids absente (attendue : US M9, convention des comparatifs) — le poids "
                "dépend de la pointure : sous-note de poids à lire avec prudence"]
    if not is_us_m9(ref):
        return [f"poids annoncé en pointure « {ref} » et non US M9 (convention des comparatifs) — sous-note de "
                "poids à lire avec prudence"]
    return []


def minimalist_index(spec: dict) -> dict:
    """Index minimaliste d'une fiche `shoe_spec` (dict du bloc `arc`).

    Rend `{"available": bool, "index_pct", "sum", "subscores", "inputs", "missing", "reason", ...}`.
    `available` est faux — et `index_pct` absent — dès qu'une des cinq entrées manque ou sort de son
    domaine : jamais un indice partiel, jamais une valeur supposée. `reason` dit pourquoi.
    """
    inputs: Dict[str, dict] = {}
    missing: List[str] = []

    def retained(field: str) -> Optional[float]:
        entry = spec.get(field)
        value = entry.get("value") if isinstance(entry, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        inputs[field] = {"value": value, "source_type": entry.get("source_type")}
        return float(value)

    weight = retained("weight_g")
    stack = retained("stack_heel_mm")
    drop = retained("drop_mm")
    if drop is None:
        # Repli de l'article : drop = hauteur de talon moins hauteur sous les têtes métatarsiennes.
        fore = retained("stack_forefoot_mm")
        if stack is not None and fore is not None:
            drop = stack - fore
            inputs["drop_mm"] = {"value": round(drop, 3), "source_type": "derived",
                                 "derived_from": ["stack_heel_mm", "stack_forefoot_mm"]}
    longi = retained("flexibility_longitudinal")
    tors = retained("flexibility_torsional")
    devices = retained("stability_devices")

    for label, value in (("weight_g", weight), ("stack_heel_mm", stack),
                         ("drop_mm (ou stack_forefoot_mm)", drop),
                         ("flexibility_longitudinal", longi), ("flexibility_torsional", tors),
                         ("stability_devices", devices)):
        if value is None:
            missing.append(label)
    out: dict = {"available": False, "reference": MI_REFERENCE["citation"], "url": MI_REFERENCE["url"],
                 "inputs": inputs, "missing": missing, "assumptions": list(MI_ASSUMPTIONS)}
    warnings = _weight_reference_warnings(spec)
    if warnings:
        out["warnings"] = warnings
    if missing:
        out["reason"] = "entrées manquantes : " + ", ".join(missing) + " — index non calculé"
        return out
    for field, (lo, hi) in (("flexibility_longitudinal", C.SHOE_PLAUSIBLE["flexibility_longitudinal"]),
                            ("flexibility_torsional", C.SHOE_PLAUSIBLE["flexibility_torsional"]),
                            ("stability_devices", C.SHOE_PLAUSIBLE["stability_devices"])):
        if not lo <= inputs[field]["value"] <= hi:
            out["reason"] = f"{field} hors du domaine {lo:g}-{hi:g} — index non calculé"
            return out
    subscores = {
        "weight": weight_subscore(weight),
        "stack_height": stack_subscore(stack),
        "heel_toe_drop": drop_subscore(drop),
        "flexibility": flexibility_subscore(longi, tors),
        "stability": stability_subscore(int(devices)),
    }
    total = sum(subscores.values())
    out.update({"available": True, "subscores": subscores, "sum": total, "max_sum": MI_MAX_SUM,
                "index_pct": round(total * 4.0, 1)})
    return out


# ---------------------------------------------------------------------------
# Provenance : valeur retenue, alternatives, écart entre sources
# ---------------------------------------------------------------------------


def select_value(candidates: List[dict]) -> Optional[dict]:
    """Valeur à retenir parmi des candidats `{value, source_type, ...}` : `athlete` > `measured` >
    `manufacturer` ; à type égal, le premier de la liste ; les candidats `outlier: true` sont écartés.
    Rend `None` si aucun candidat n'est utilisable (la valeur reste alors absente)."""
    rank = {t: i for i, t in enumerate(C.SHOE_SOURCE_PRIORITY)}
    usable = [c for c in candidates if isinstance(c, dict) and not c.get("outlier")
              and c.get("source_type") in rank and c.get("value") is not None]
    if not usable:
        return None
    return min(usable, key=lambda c: rank[c["source_type"]])


def field_summary(entry: dict) -> dict:
    """Résumé d'un champ de la fiche : valeur retenue + provenance, alternatives et écart entre sources.

    `spread` (numérique seulement) : `min`/`max`/`range` sur les sources non aberrantes, et
    `measured_minus_manufacturer` quand un labo ET une marque ont chacun une valeur (l'écart marque/labo
    que la règle de continuité du drop doit voir)."""
    alts = [a for a in (entry.get("alternatives") or []) if isinstance(a, dict)]
    out = {k: entry[k] for k in ("value", "source_type", "basis", "url", "retrieved", "reference_size", "scale")
           if entry.get(k) is not None}
    out["alternatives"] = alts
    numeric = [c for c in [entry] + alts
               if isinstance(c.get("value"), (int, float)) and not isinstance(c.get("value"), bool)
               and not c.get("outlier")]
    if len(numeric) > 1:
        values = [c["value"] for c in numeric]
        spread = {"n": len(values), "min": min(values), "max": max(values),
                  "range": round(max(values) - min(values), 3)}
        measured = next((c["value"] for c in numeric if c.get("source_type") == "measured"), None)
        brand = next((c["value"] for c in numeric if c.get("source_type") == "manufacturer"), None)
        if measured is not None and brand is not None:
            spread["measured_minus_manufacturer"] = round(measured - brand, 3)
        out["spread"] = spread
    outliers = [a for a in alts if a.get("outlier")]
    if outliers:
        out["outliers"] = len(outliers)
    return out


def spec_summary(source_path: str, data: dict) -> dict:
    """Une fiche mise en forme pour la CLI : identité, champs avec provenance, index minimaliste."""
    out = {"gear_id": data.get("gear_id"), "source_path": source_path, "date": data.get("date"),
           "brand": data.get("brand"), "model": data.get("model")}
    for key in ("version", "release_year", "size", "purchase_date"):
        if data.get(key) is not None:
            out[key] = data[key]
    fields = {k: field_summary(data[k]) for k in C.SHOE_VALUE_FIELDS if isinstance(data.get(k), dict)}
    out["fields"] = fields
    absent = [k for k in ("category", "drop_mm", "stack_heel_mm", "stack_forefoot_mm", "weight_g",
                          "midsole_foam", "midsole_softness", "plate", "lug_depth_mm", "toe_box")
              if k not in fields]
    out["absent"] = absent
    out["minimalist_index"] = minimalist_index(data)
    return out


def report(rows: List[dict], declared: Optional[List[dict]] = None, gear_id: Optional[str] = None) -> dict:
    """Rapport de la commande `shoe-specs`. `rows` = [{source_path, data}] des fiches indexées ;
    `declared` = paires du profil [{gear_id, name, retired, ignored}] (pour lister celles SANS fiche)."""
    specs = [spec_summary(r["source_path"], r["data"]) for r in rows
             if gear_id is None or r["data"].get("gear_id") == gear_id]
    specs.sort(key=lambda s: (s.get("gear_id") or ""))
    out: dict = {"count": len(specs), "specs": specs}
    if declared is not None:
        known = {g["gear_id"] for g in declared}
        for spec in specs:
            spec["in_profile"] = spec["gear_id"] in known
        out["unknown_gear"] = [s["gear_id"] for s in specs if not s["in_profile"]]
        have = {s["gear_id"] for s in specs}
        out["gear_without_spec"] = [
            {"gear_id": g["gear_id"], "name": g.get("name")} for g in declared
            if g["gear_id"] not in have and not g.get("retired") and not g.get("ignored")
            and (gear_id is None or g["gear_id"] == gear_id)]
    if gear_id is not None and not specs:
        out["error"] = f"aucune fiche de caractéristiques pour « {gear_id} » (gear/specs/{gear_id}.md)"
    return out


def _fmt_field(name: str, f: dict) -> str:
    value = f.get("value")
    unit = {"drop_mm": " mm", "stack_heel_mm": " mm", "stack_forefoot_mm": " mm", "weight_g": " g",
            "lug_depth_mm": " mm"}.get(name, "")
    scale = f" ({f['scale']})" if f.get("scale") else ""
    basis = f" (fondée sur {f['basis']})" if f.get("basis") else ""
    line = f"  {name} : {value}{unit}{scale} [{f.get('source_type')}{basis}]"
    spread = f.get("spread")
    if spread:
        line += f" — sources {spread['min']:g} à {spread['max']:g}"
        if "measured_minus_manufacturer" in spread:
            line += f", labo - marque = {spread['measured_minus_manufacturer']:+g}"
    if f.get("outliers"):
        line += f", {f['outliers']} aberration(s) écartée(s)"
    return line


def render_text(rep: dict) -> str:
    """Rendu texte (`--text`)."""
    if rep.get("error"):
        return rep["error"]
    lines: List[str] = []
    for spec in rep["specs"]:
        ver = f" {spec['version']}" if spec.get("version") else ""
        lines.append(f"{spec['gear_id']} — {spec.get('brand')} {spec.get('model')}{ver}")
        for name, f in spec["fields"].items():
            lines.append(_fmt_field(name, f))
        if spec["absent"]:
            lines.append("  absent : " + ", ".join(spec["absent"]))
        if spec.get("in_profile") is False:
            lines.append("  ATTENTION : cette paire ne figure pas dans ### Chaussures du profil")
        mi = spec["minimalist_index"]
        for warning in mi.get("warnings", []):
            lines.append(f"  avertissement : {warning}")
        if mi["available"]:
            lines.append(f"  index minimaliste : {mi['index_pct']:g} % (somme {mi['sum']:g}/{mi['max_sum']})")
        else:
            lines.append(f"  index minimaliste : indisponible — {mi['reason']}")
    if not rep["specs"]:
        lines.append("Aucune fiche de caractéristiques (gear/specs/).")
    if rep.get("gear_without_spec"):
        lines.append("Paires sans fiche : " + ", ".join(g["gear_id"] for g in rep["gear_without_spec"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Retours de chaussant et bilan de retraite (#299)
# ---------------------------------------------------------------------------

FEEDBACK_RECENT = 10     # nombre de retours récents listés par paire


def verdict_summary(data: dict) -> Optional[dict]:
    """Bilan de retraite (`shoe_spec.verdict`) tel qu'écrit, ou None. Rien n'est déduit."""
    v = data.get("verdict")
    return dict(v) if isinstance(v, dict) else None


def feedback_report(feedback_rows: List[dict], spec_rows: List[dict], declared: Optional[List[dict]] = None,
                    gear_id: Optional[str] = None) -> dict:
    """Rapport de la commande `shoe-feedback` (#299), lecture seule. `feedback_rows` = lignes de la
    table `shoe_feedback` ({source_path, date, gear_id, comfort, issues (liste), notes}) ; `spec_rows`
    = [{source_path, data}] des fiches (pour le bilan de retraite). Agrégation PAR PAIRE : le confort
    déclaré (moyenne, min/max, dernier) et le nombre de SÉANCES touchées par chaque `kind` / zone. Un retour décrit une
    sensation de chaussant : jamais une cause de douleur (corrélation, pas causalité)."""
    by_gear: Dict[str, List[dict]] = {}
    for r in feedback_rows:
        if r.get("gear_id") and (gear_id is None or r["gear_id"] == gear_id):
            by_gear.setdefault(r["gear_id"], []).append(r)
    verdicts = {}
    for sr in spec_rows:
        gid = sr["data"].get("gear_id")
        v = verdict_summary(sr["data"])
        if gid and v and (gear_id is None or gid == gear_id):
            verdicts[gid] = v
    names = {g["gear_id"]: g.get("name") for g in (declared or [])}
    pairs = []
    for gid in sorted(set(by_gear) | set(verdicts)):
        rows = sorted(by_gear.get(gid, []), key=lambda r: (r.get("date") or "", r.get("source_path") or ""))
        comforts = [r["comfort"] for r in rows if isinstance(r.get("comfort"), (int, float))]
        kinds: Dict[str, int] = {}
        zones: Dict[str, int] = {}
        for r in rows:       # comptés en SÉANCES (un même problème deux fois dans une séance compte une fois)
            issues = [i for i in (r.get("issues") or []) if isinstance(i, dict) and i.get("kind")]
            for kind in {i["kind"] for i in issues}:
                kinds[kind] = kinds.get(kind, 0) + 1
            for zone in {i["zone"] for i in issues if i.get("zone")}:
                zones[zone] = zones.get(zone, 0) + 1
        pairs.append({
            "gear_id": gid, "name": names.get(gid), "runs_with_feedback": len(rows),
            "runs_with_issues": sum(1 for r in rows if r.get("issues")),
            "comfort": ({"mean": round(sum(comforts) / len(comforts), 2), "min": min(comforts),
                         "max": max(comforts), "last": comforts[-1], "n": len(comforts)}
                        if comforts else None),
            "issue_counts": dict(sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))),
            "zone_counts": dict(sorted(zones.items(), key=lambda kv: (-kv[1], kv[0]))),
            "recent": [{"date": r.get("date"), "source_path": r.get("source_path"),
                        "comfort": r.get("comfort"), "issues": r.get("issues") or [],
                        "notes": r.get("notes")} for r in rows[-FEEDBACK_RECENT:]],
            "verdict": verdicts.get(gid)})
    out: dict = {"count": len(pairs), "pairs": pairs,
                 "note": "déclaratif ; un retour de chaussant n'est jamais une cause de douleur "
                         "(corrélation, pas causalité)"}
    if gear_id is not None and not pairs:
        if gear_id in names:
            out["info"] = f"aucun retour de chaussant pour « {gear_id} »"
        else:
            out["error"] = f"paire inconnue du profil et sans retour de chaussant : « {gear_id} »"
    return out


def render_feedback_text(rep: dict) -> str:
    """Rendu texte de `shoe-feedback` (`--text`)."""
    if rep.get("error"):
        return rep["error"]
    lines: List[str] = []
    for p in rep["pairs"]:
        title = f"{p['gear_id']}" + (f" — {p['name']}" if p.get("name") else "")
        lines.append(f"{title} : {p['runs_with_feedback']} retour(s), {p['runs_with_issues']} avec problème(s)")
        c = p.get("comfort")
        if c:
            lines.append(f"  confort : moyenne {c['mean']:g}/10 (min {c['min']:g}, max {c['max']:g}, "
                         f"dernier {c['last']:g}, n={c['n']})")
        if p["issue_counts"]:
            lines.append("  problèmes (séances) : " + ", ".join(f"{k} ×{n}" for k, n in p["issue_counts"].items()))
        v = p.get("verdict")
        if v:
            change = f", changements voulus : {', '.join(v['change_wanted'])}" if v.get("change_wanted") else ""
            lines.append(f"  bilan de retraite ({v.get('date')}) : confort {v.get('comfort_overall'):g}/10, "
                         f"rachat : {v.get('would_rebuy')}{change}")
    if not rep["pairs"]:
        lines.append(rep.get("info") or "Aucun retour de chaussant enregistré.")
    return "\n".join(lines)
