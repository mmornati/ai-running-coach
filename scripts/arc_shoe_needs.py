#!/usr/bin/env python3
"""Moteur de règles fondé sur les preuves pour le choix des chaussures (#301, épopée #297).

Transforme les preuves de `config/shoes/rules.json` en PLAGES CIBLES (drop, pile du talon, souplesse de
la mousse, crampons, largeur d'avant-pied, plaque, index minimaliste), chacune avec les règles
appliquées, la raison en français, le niveau de preuve et les références. Fonctions pures : les
entrées (rôle, paires de référence, usage de la paire remplacée, antécédents de douleur, masse) sont
rassemblées par `arc_index.shoe_needs` ; ce module ne lit ni fichier de données ni réseau, n'écrit rien.

Ordre de décision : confort -> continuité -> garde-fous blessures -> adéquation au terrain. Le
confort perçu est le critère individuel le mieux étayé ; les caractéristiques d'une fiche
restreignent ou avertissent, elles ne décident pas. La sortie ne nomme JAMAIS une marque ni un modèle
(les paires de l'athlète ne sont citées que par leur `gear_id`). Déterministe : mêmes entrées, même
sortie. Ce n'est pas un avis médical.

Bibliothèque standard uniquement.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ENGINE_DIR = Path(__file__).resolve().parent.parent
RULES_FILE = ENGINE_DIR / "config" / "shoes" / "rules.json"

CONFIDENCE_ORDER = ("none", "expert_opinion", "low", "moderate", "high")   # du plus faible au plus fort
CONFIDENCE_LABELS_FR = {"high": "élevé", "moderate": "modéré", "low": "faible", "expert_opinion": "avis d'experts",
                        "none": "aucune preuve (approximation du projet)"}
ROLES = ("trail_long", "trail", "road_easy", "road_tempo", "race", "mixed_long", "mixed")   # vocabulaire de `arc_shoe_usage`
ROAD_ROLES = ("road_easy", "road_tempo")
TRAIL_ROLES = ("trail_long", "trail")
SOFTNESS = ("soft", "moderate", "firm")
TOE_BOX = ("narrow", "standard", "wide")
PLATES = ("none", "carbon", "nylon", "rock_plate")
RANGE_FIELDS = ("drop_mm", "stack_heel_mm", "lug_depth_mm", "minimalist_index_pct")
FIELD_LABELS_FR = {
    "drop_mm": "drop (mm)", "stack_heel_mm": "pile du talon (mm)", "midsole_softness": "souplesse de la mousse",
    "lug_depth_mm": "crampons (mm)", "toe_box": "largeur d'avant-pied", "plate": "plaque",
    "minimalist_index_pct": "index minimaliste (%)",
}
SOFTNESS_FR = {"soft": "souple", "moderate": "modérée", "firm": "ferme"}
TOE_BOX_FR = {"narrow": "étroit", "standard": "standard", "wide": "large"}
PLATE_FR = {"none": "aucune", "carbon": "carbone", "nylon": "nylon", "rock_plate": "anti-roche"}

# Chaque règle de `rules.json` a un gestionnaire ci-dessous, et inversement (vérifié par un test de lint).
HANDLED_RULES = (
    "broad_defaults", "comfort_first", "insufficient_reference", "continuity_drop", "continuity_minimalist_index",
    "continuity_stack", "continuity_toe_box", "achilles_calf_no_drop_decrease", "ankle_sprain_low_stack_wide_base",
    "mass_minimalism_caution", "softness_not_firm", "no_mass_cushion_rule", "no_foot_type_prescription",
    "continuity_lugs", "terrain_lugs_hard", "terrain_lugs_soft", "terrain_rock_plate", "race_performance_option", "race_stack_limit",
    "rotation_reminder", "change_wanted_adjust", "gait_dynamics_monitor_only",
)

# Sous-types de `change_wanted` (#299) sans plage associée : dits à l'athlète, jamais ignorés en silence.
PROFILE_INJURY_BULLETS = ("Antécédents de blessure", "Zones fragiles à surveiller")

CHANGE_NO_RANGE = {
    "lighter": "« plus léger » : le poids n'a pas de plage cible dans ce moteur",
    "narrower": "« plus étroit » : la largeur d'avant-pied autorise le standard et l'étroit",
    "other": "« autre » : à préciser avec l'athlète, aucune plage associée",
}


class ShoeNeedsError(ValueError):
    """Règles invalides ou illisibles."""


# ---------------------------------------------------------------------------
# Chargement et validation
# ---------------------------------------------------------------------------


def load_rules(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else RULES_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ShoeNeedsError(f"règles de chaussures illisibles ({p}) : {exc}")
    errors = validate_rules(doc)
    if errors:
        raise ShoeNeedsError("règles de chaussures invalides : " + " ; ".join(errors))
    return doc


def validate_rules(doc: Any) -> List[str]:
    """Liste d'erreurs (vide = conforme) : identifiants uniques et gérés, niveau de preuve connu, références
    résolues, et — sauf niveau `none`/`expert_opinion` — au moins une référence ; `none`/`expert_opinion`
    exigent une justification (`rationale`)."""
    if not isinstance(doc, dict):
        return ["racine : objet attendu."]
    errors: List[str] = []
    sources = doc.get("sources")
    if not isinstance(sources, dict) or not sources:
        errors.append("`sources` absent ou vide.")
        sources = {}
    for sid, s in sources.items():
        if not isinstance(s, dict) or not s.get("citation") or not str(s.get("url", "")).startswith("https://"):
            errors.append(f"source {sid} : citation et url https attendues.")
        elif not s.get("verified"):
            errors.append(f"source {sid} : `verified` (comment elle a été vérifiée) attendu.")
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        return errors + ["`rules` absent ou vide."]
    seen = set()
    for r in rules:
        rid = r.get("id") if isinstance(r, dict) else None
        if not rid or rid in seen:
            errors.append(f"identifiant de règle manquant ou en double : {rid!r}.")
            continue
        seen.add(rid)
        for key in ("condition", "effect"):
            if not isinstance(r.get(key), str) or not r[key].strip():
                errors.append(f"règle {rid} : `{key}` attendu.")
        conf = r.get("confidence")
        if conf not in CONFIDENCE_ORDER:
            errors.append(f"règle {rid} : `confidence` parmi {', '.join(CONFIDENCE_ORDER)} (reçu {conf!r}).")
        refs = r.get("references")
        if not isinstance(refs, list):
            errors.append(f"règle {rid} : `references` (liste) attendu.")
            refs = []
        for ref in refs:
            if ref not in sources:
                errors.append(f"règle {rid} : référence inconnue {ref!r}.")
        if conf in ("none", "expert_opinion"):
            if not str(r.get("rationale", "")).strip():
                errors.append(f"règle {rid} : `rationale` obligatoire pour le niveau {conf}.")
        elif conf in CONFIDENCE_ORDER and not refs:
            errors.append(f"règle {rid} : au moins une référence exigée pour le niveau {conf}.")
        if rid not in HANDLED_RULES:
            errors.append(f"règle {rid} : aucun gestionnaire dans arc_shoe_needs.")
    for rid in HANDLED_RULES:
        if rid not in seen:
            errors.append(f"gestionnaire sans règle dans rules.json : {rid}.")
    return errors


# ---------------------------------------------------------------------------
# Sortie : cibles
# ---------------------------------------------------------------------------


class _Rules:
    """Accès aux règles chargées + trace des règles appliquées."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.by_id = {r["id"]: r for r in doc["rules"]}
        self.sources = doc["sources"]
        self.applied: Dict[str, dict] = {}

    def param(self, rid: str, key: str) -> Any:
        return self.by_id[rid]["params"][key]

    def public(self, rid: str) -> dict:
        r = self.by_id[rid]
        return {"id": rid, "confidence": r["confidence"], "effect": r["effect"],
                "references": [{"id": s, "citation": self.sources[s]["citation"], "url": self.sources[s]["url"]}
                               for s in r.get("references", [])]}

    def mark(self, rid: str) -> None:
        self.applied.setdefault(rid, self.public(rid))


def _fmt(v: float) -> str:
    return f"{v:g}"


class _Target:
    def __init__(self, field: str, rules: _Rules):
        self.field, self.rules = field, rules
        self.lo: Optional[float] = None
        self.hi: Optional[float] = None
        self.allowed: Optional[List[str]] = None
        self.items: List[Tuple[str, str]] = []      # (règle, raison)
        self.conflicts: List[str] = []
        self.advisory: Optional[dict] = None

    def note(self, rid: str, reason: str) -> None:
        self.rules.mark(rid)
        if (rid, reason) not in self.items:
            self.items.append((rid, reason))

    def set_range(self, rid: str, lo: Optional[float], hi: Optional[float], reason: str, safety: bool = False) -> None:
        """Intersecte avec la plage courante. Une règle de sécurité l'emporte sur une intersection vide."""
        new_lo = self.lo if lo is None else (lo if self.lo is None else max(self.lo, lo))
        new_hi = self.hi if hi is None else (hi if self.hi is None else min(self.hi, hi))
        if new_lo is not None and new_hi is not None and new_lo > new_hi:
            if not safety:
                self.conflicts.append(f"{rid} : incompatible avec les règles précédentes, ignorée ({reason})")
                return
            self.conflicts.append(f"{rid} : prime sur une plage précédente incompatible ({reason})")
            new_lo, new_hi = (lo if lo is not None else new_lo), (hi if hi is not None else new_lo)
            if new_hi < new_lo:
                new_hi = new_lo
        self.lo, self.hi = new_lo, new_hi
        self.note(rid, reason)

    def set_allowed(self, rid: str, values: List[str], reason: str, safety: bool = False) -> None:
        cur = self.allowed
        new = list(values) if cur is None else [v for v in cur if v in values]
        if not new:
            self.conflicts.append(f"{rid} : valeurs incompatibles avec les règles précédentes"
                                  + (", prime" if safety else ", ignorée") + f" ({reason})")
            if not safety:
                return
            new = list(values)
        self.allowed = new
        self.note(rid, reason)

    def confidence(self) -> str:
        levels = [self.rules.by_id[rid]["confidence"] for rid, _ in self.items
                  if rid not in ("broad_defaults", "insufficient_reference")]
        if not levels:
            return "none"
        return min(levels, key=CONFIDENCE_ORDER.index)

    def public(self) -> dict:
        out: Dict[str, Any] = {"field": self.field, "label": FIELD_LABELS_FR[self.field]}
        if self.field in RANGE_FIELDS:
            if self.lo is not None:
                out["min"] = round(self.lo, 1)
            if self.hi is not None:
                out["max"] = round(self.hi, 1)
        else:
            out["allowed"] = list(self.allowed or [])
        rule_ids = sorted({rid for rid, _ in self.items}, key=[r["id"] for r in self.rules.doc["rules"]].index)
        out["rules"] = rule_ids
        out["reasons"] = [reason for _, reason in self.items]
        out["confidence"] = self.confidence()
        refs: Dict[str, dict] = {}
        for rid in rule_ids:
            for ref in self.rules.public(rid)["references"]:
                refs[ref["id"]] = ref
        out["references"] = list(refs.values())
        if self.conflicts:
            out["conflicts"] = list(self.conflicts)
        if self.advisory:
            out["advisory"] = dict(self.advisory)
        return out


def _spec_value(spec: Optional[dict], field: str) -> Optional[dict]:
    """{value, source_type, basis?, spread?} d'un champ de fiche (`arc_shoes.spec_summary`), ou None."""
    f = ((spec or {}).get("fields") or {}).get(field)
    if not isinstance(f, dict) or f.get("value") is None:
        return None
    return f


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _de(name: str) -> str:
    """Élision française : « d'ultra-glide » devant une voyelle ou un h muet, « de road-a » sinon."""
    return ("d'" if name[:1].lower() in "aeiouyàâéèêëîïôùûh" else "de ") + name


def parse_profile_injuries(body_md: Optional[str], zone_of) -> List[dict]:
    """Antécédents déclarés dans les puces du profil « Antécédents de blessure » et « Zones fragiles à surveiller »
    (valeur sur la ligne, ou sous-puces indentées). Un élément (séparé par `;`, `,` ou « et ») = une entrée
    {source: 'profile', bullet, text, zone, side, sprain}. `zone_of(texte)` -> {zone, side} (`arc_prevention`).
    « aucun », « néant », « rien », « - » et les commentaires HTML sont ignorés. Un élément sans zone reconnue
    est gardé avec `zone: None` (dit, jamais deviné)."""
    out: List[dict] = []
    if not body_md:
        return out
    lines = body_md.splitlines()
    for bullet in PROFILE_INJURY_BULLETS:
        pat = re.compile(r"^\s*[-*]\s*\*\*\s*" + re.escape(bullet) + r"\s*\*\*\s*:?\s*(.*)$", re.IGNORECASE)
        for i, line in enumerate(lines):
            m = pat.match(line)
            if not m:
                continue
            chunks = [m.group(1)]
            for nxt in lines[i + 1:]:
                if re.match(r"^\s*[-*]\s*\*\*", nxt) or nxt.lstrip().startswith("#"):
                    break
                if nxt.strip():
                    chunks.append(re.sub(r"^\s*[-*]\s*", "", nxt))
            text = re.sub(r"<!--.*?-->", " ", " ".join(chunks), flags=re.DOTALL).strip()
            for item in re.split(r"[;,\n]| et ", text):
                item = item.strip(" .\t")
                if not item or item.lower().strip("- ") in ("aucun", "aucune", "néant", "neant", "rien", "ras", ""):
                    continue
                z = zone_of(item)
                out.append({"source": "profile", "bullet": bullet, "text": item, "zone": z.get("zone"),
                            "side": z.get("side"), "sprain": "entorse" in item.lower()})
            break
    return out


def _basis(f: dict) -> str:
    """Base d'une valeur : `basis` quand l'athlète a validé une valeur de laboratoire ou de marque, sinon son type."""
    return f.get("basis") or f.get("source_type") or "?"


def _reference_values(refs: List[dict], field: str, warnings: List[str]) -> List[float]:
    vals: List[float] = []
    for r in refs:
        f = _spec_value(r.get("spec"), field)
        v = _num(f.get("value")) if f else None
        if v is None:
            continue
        vals.append(v)
        if field == "drop_mm" and _basis(f) == "manufacturer":
            warnings.append(f"drop {_de(r['gear_id'])} : valeur annoncée par la marque, non mesurée — les écarts "
                            "marque/laboratoire relevés (1,5 à 2,7 mm sur deux paires, épopée #297) peuvent décaler la plage")
    return vals


def evaluate(rules_doc: dict, inp: dict) -> dict:
    """Plages cibles pour `inp` (voir `arc_index.shoe_needs`) :

    - `role`, `replace` (gear_id ou None), `replaced` ({gear_id, usage, verdict, spec} ou None) ;
    - `references` : [{gear_id, comfort, would_rebuy, verdict, spec}] — would_rebuy = yes ou yes_with_change
      (changement appliqué) et confort >= 7 ;
    - `injury` : {sources: [{source, label, period?, entries}], entries: [{source, zone, side, score?, text?,
      sprain?, date?}]} — antécédents lus dans les douleurs déclarées (`medical/`) ET dans les puces du profil
      (« Antécédents de blessure », « Zones fragiles à surveiller »), zones normalisées par `arc_prevention` ;
    - `mass_kg` (+ `mass_source`), `active_pairs` : nombre de paires actives du profil.
    """
    R = _Rules(rules_doc)
    role = inp["role"]
    replaced = inp.get("replaced")
    refs = list(inp.get("references") or [])
    warnings: List[str] = []
    notes: List[str] = []
    options: List[dict] = []
    reminders: List[dict] = []
    T = {f: _Target(f, R) for f in ("drop_mm", "stack_heel_mm", "midsole_softness", "lug_depth_mm", "toe_box",
                                    "plate", "minimalist_index_pct")}

    # --- départ : plages larges --------------------------------------------------------------------
    R.mark("broad_defaults")
    for f in RANGE_FIELDS:
        lo, hi = R.param("broad_defaults", f)
        T[f].lo, T[f].hi = float(lo), float(hi)
        T[f].items.append(("broad_defaults", "plage large du projet avant restriction (aucune source)"))
    T["midsole_softness"].allowed = list(SOFTNESS)
    T["toe_box"].allowed = list(TOE_BOX)
    T["plate"].allowed = list(PLATES)
    for f in ("midsole_softness", "toe_box", "plate"):
        T[f].items.append(("broad_defaults", "toutes les valeurs au départ (aucune source)"))

    # --- 1. confort d'abord ------------------------------------------------------------------------
    insufficient = not refs
    if insufficient:
        R.mark("insufficient_reference")
        warnings.append("données insuffisantes : aucune paire avec would_rebuy = yes (ou yes_with_change) et confort >= 7 ; "
                        "plages larges conservées, aucune continuité contraignante (renseigner le bilan de retraite ou les "
                        "retours de confort)")
    else:
        R.mark("comfort_first")

    # --- 2. continuité -----------------------------------------------------------------------------
    ref_ids = ", ".join(r["gear_id"] for r in refs)
    ref_drops = _reference_values(refs, "drop_mm", warnings) if refs else []
    if ref_drops:
        tol = R.param("continuity_drop", "tolerance_mm")
        T["drop_mm"].set_range("continuity_drop", min(ref_drops) - tol, max(ref_drops) + tol,
                               f"drop de référence {_fmt(min(ref_drops))}"
                               + (f" à {_fmt(max(ref_drops))}" if max(ref_drops) != min(ref_drops) else "")
                               + f" mm (paires {ref_ids}) à +/- {_fmt(tol)} mm")
    elif refs:
        notes.append("drop de référence inconnu (fiche absente ou sans drop) : continuité du drop non calculée")
    ref_stacks = _reference_values(refs, "stack_heel_mm", warnings) if refs else []
    if ref_stacks:
        tol = R.param("continuity_stack", "tolerance_mm")
        T["stack_heel_mm"].set_range("continuity_stack", min(ref_stacks) - tol, max(ref_stacks) + tol,
                                     f"pile de référence {_fmt(min(ref_stacks))}"
                                     + (f" à {_fmt(max(ref_stacks))}" if max(ref_stacks) != min(ref_stacks) else "")
                                     + f" mm à +/- {_fmt(tol)} mm (approximation du projet)")
    ref_mi = [r["spec"]["minimalist_index"]["index_pct"] for r in refs
              if (r.get("spec") or {}).get("minimalist_index", {}).get("available")]
    if ref_mi:
        tol = R.param("continuity_minimalist_index", "tolerance_pts")
        T["minimalist_index_pct"].set_range("continuity_minimalist_index", min(ref_mi) - tol, max(ref_mi) + tol,
                                            f"index minimaliste de référence {_fmt(min(ref_mi))}"
                                            + (f" à {_fmt(max(ref_mi))}" if max(ref_mi) != min(ref_mi) else "")
                                            + f" % à +/- {_fmt(tol)} points")
    elif refs:
        notes.append("index minimaliste de référence indisponible (entrée manquante dans la fiche) : continuité non calculée")
    ref_toe = sorted({v for r in refs for v in [(_spec_value(r.get("spec"), "toe_box") or {}).get("value")] if v in TOE_BOX},
                     key=TOE_BOX.index)
    if ref_toe:
        T["toe_box"].set_allowed("continuity_toe_box", ref_toe,
                                 "largeur d'avant-pied des paires de référence : " + ", ".join(TOE_BOX_FR[v] for v in ref_toe))
    ref_plates = sorted({v for r in refs for v in [(_spec_value(r.get("spec"), "plate") or {}).get("value")] if v in PLATES},
                        key=PLATES.index)
    ref_stability = [r for r in refs if (_num((_spec_value(r.get("spec"), "stability_devices") or {}).get("value")) or 0) >= 1]

    # --- paire remplacée sans verdict de confort : bande d'AVERTISSEMENT, jamais une contrainte --------------
    if not refs and replaced and replaced.get("spec"):
        label = "paire remplacée, sans verdict de confort"
        rp = replaced["spec"]
        bands = []
        for fld, rid, key, tol_key, unit in (("drop_mm", "continuity_drop", "drop_mm", "tolerance_mm", "mm"),
                                             ("stack_heel_mm", "continuity_stack", "stack_heel_mm", "tolerance_mm", "mm")):
            v = _num((_spec_value(rp, key) or {}).get("value"))
            if v is not None:
                tol = R.param(rid, tol_key)
                T[fld].advisory = {"min": round(v - tol, 1), "max": round(v + tol, 1), "basis": label, "rule": rid,
                                   "reason": f"{FIELD_LABELS_FR[fld]} de la paire remplacée {_fmt(v)} +/- {_fmt(tol)} {unit}"}
                R.mark(rid)
                bands.append(FIELD_LABELS_FR[fld])
        mi = (rp.get("minimalist_index") or {})
        if mi.get("available"):
            tol = R.param("continuity_minimalist_index", "tolerance_pts")
            T["minimalist_index_pct"].advisory = {
                "min": round(mi["index_pct"] - tol, 1), "max": round(mi["index_pct"] + tol, 1), "basis": label,
                "rule": "continuity_minimalist_index",
                "reason": f"index minimaliste de la paire remplacée {_fmt(mi['index_pct'])} +/- {_fmt(tol)} points"}
            R.mark("continuity_minimalist_index")
            bands.append(FIELD_LABELS_FR["minimalist_index_pct"])
        if bands:
            warnings.append(f"{label} : bande de continuité indicative (non contraignante) pour " + ", ".join(bands)
                            + " — sortir de cette bande est un grand changement, à décider en connaissance de cause")

    # --- crampons : continuité sur la référence ---------------------------------------------------------
    ref_lugs = _reference_values(refs, "lug_depth_mm", warnings) if refs else []
    if ref_lugs:
        tol = R.param("continuity_lugs", "tolerance_mm")
        T["lug_depth_mm"].set_range("continuity_lugs", max(0.0, min(ref_lugs) - tol), max(ref_lugs) + tol,
                                    f"crampons de référence {_fmt(min(ref_lugs))}"
                                    + (f" à {_fmt(max(ref_lugs))}" if max(ref_lugs) != min(ref_lugs) else "")
                                    + f" mm à +/- {_fmt(tol)} mm (approximation du projet)")

    # --- amorti : défaut souple/modéré ---------------------------------------------------------------
    T["midsole_softness"].set_allowed("softness_not_firm", list(R.param("softness_not_firm", "default")),
                                      "mousse souple ou modérée par défaut (une mousse dure a été associée à plus de blessures)")
    mass = _num(inp.get("mass_kg"))
    if mass is not None:
        R.mark("no_mass_cushion_rule")
        notes.append(f"masse connue ({_fmt(mass)} kg) : elle ne change jamais l'amorti visé (« plus lourd donc plus d'amorti » n'est pas une règle)")
    R.mark("no_foot_type_prescription")
    notes.append("aucune prescription selon le type de pied ou la pronation")
    R.mark("gait_dynamics_monitor_only")
    notes.append("dynamiques de foulée (contact au sol, oscillation, cadence) : à surveiller après un changement, jamais un critère de choix")

    # --- change_wanted (préférence déclarée de la paire remplacée) ---------------------------------
    changes: List[str] = []
    verdicts = [(replaced or {}).get("verdict")] + [r.get("verdict") for r in refs]
    for v in verdicts:
        v = v or {}
        cw = v.get("change_wanted") if v.get("would_rebuy") == "yes_with_change" else None
        for ch in ([cw] if isinstance(cw, str) else list(cw or [])):
            if ch not in changes:
                changes.append(ch)
    stability_wanted = False
    step = R.param("change_wanted_adjust", "drop_step_mm")
    for ch in changes:
        if ch == "wider_toe_box":
            T["toe_box"].set_allowed("change_wanted_adjust", ["wide"], "changement souhaité : avant-pied plus large (prime sur la largeur de référence)", safety=True)
        elif ch == "narrower":
            T["toe_box"].set_allowed("change_wanted_adjust", ["narrow", "standard"], "changement souhaité : plus étroit (prime sur la largeur de référence)", safety=True)
        elif ch == "more_drop" and ref_drops:
            T["drop_mm"].set_range("change_wanted_adjust", min(ref_drops), max(ref_drops) + step,
                                   "changement souhaité : plus de drop (au-dessus de la référence)")
        elif ch == "less_drop" and ref_drops:
            T["drop_mm"].set_range("change_wanted_adjust", min(ref_drops) - step, max(ref_drops),
                                   "changement souhaité : moins de drop (sous la référence)")
        elif ch in ("more_drop", "less_drop"):
            notes.append(f"changement souhaité « {ch} » : drop de référence inconnu, aucune plage décalée")
        elif ch == "more_cushion":
            T["midsole_softness"].set_allowed("change_wanted_adjust", ["soft"], "changement souhaité : plus d'amorti (mousse souple)")
            if ref_stacks:
                T["stack_heel_mm"].set_range("change_wanted_adjust", min(ref_stacks), None,
                                             "changement souhaité : plus d'amorti (pile au moins égale à la référence)")
        elif ch == "firmer":
            T["midsole_softness"].set_allowed("change_wanted_adjust", ["moderate", "firm"], "changement souhaité : plus ferme")
            warnings.append("changement souhaité « plus ferme » : une mousse dure a été associée à plus de blessures chez les coureurs "
                            "légers (niveau faible) ; la préférence est respectée, avec cette réserve")
        elif ch == "more_grip":
            lug_ref = _reference_values(refs, "lug_depth_mm", warnings)
            if lug_ref:
                T["lug_depth_mm"].set_range("change_wanted_adjust", max(lug_ref) + R.param("change_wanted_adjust", "lug_step_mm"), None,
                                            "changement souhaité : plus d'adhérence (crampons plus longs que la référence)")
            else:
                notes.append("changement souhaité « plus d'adhérence » : crampons de référence inconnus, aucune plage décalée")
        elif ch == "more_stable":
            stability_wanted = True
            R.mark("change_wanted_adjust")
        elif ch in CHANGE_NO_RANGE:
            R.mark("change_wanted_adjust")
            notes.append("changement souhaité " + CHANGE_NO_RANGE[ch])

    # --- 3. garde-fous blessures --------------------------------------------------------------------
    injury = inp.get("injury") or {}
    entries = [e for e in (injury.get("entries") or []) if isinstance(e, dict)]
    history_sources = list(injury.get("sources") or [])
    by_zone: Dict[str, int] = {}
    for e in entries:
        if e.get("zone"):
            by_zone[e["zone"]] = by_zone.get(e["zone"], 0) + 1
    if not entries:
        notes.append("aucun antécédent de blessure trouvé (sources lues : "
                     + (", ".join(s_["label"] for s_ in history_sources) or "aucune") + ") — garde-fous Achille/mollet et "
                     "cheville non déclenchés ; à compléter dans le profil si c'est inexact")
    unknown_items = [e["text"] for e in entries if e.get("source") == "profile" and not e.get("zone")]
    if unknown_items:
        notes.append("antécédents du profil sans zone reconnue (aucune règle appliquée, à préciser) : " + " ; ".join(unknown_items))
    achilles_zones = R.param("achilles_calf_no_drop_decrease", "zones")
    hit = {z: by_zone[z] for z in achilles_zones if by_zone.get(z)}
    if hit:
        srcs = sorted({e["source"] for e in entries if e.get("zone") in achilles_zones})
        cur = _num((_spec_value((replaced or {}).get("spec"), "drop_mm") or {}).get("value"))
        floor = cur if cur is not None else (min(ref_drops) if ref_drops else None)
        zones_txt = ", ".join(f"{z.replace('_', ' ')} ({n} mention{'s' if n > 1 else ''})" for z, n in sorted(hit.items()))
        src_txt = " + ".join({"health": "douleurs déclarées", "profile": "profil"}[x] for x in srcs)
        if floor is not None:
            T["drop_mm"].set_range("achilles_calf_no_drop_decrease", floor, None,
                                   f"antécédent ({src_txt}) : {zones_txt} — ne pas descendre sous {_fmt(floor)} mm "
                                   "(drop de la paire actuelle ou de la référence ; extrapolation du projet)", safety=True)
        else:
            R.mark("achilles_calf_no_drop_decrease")
            T["drop_mm"].note("achilles_calf_no_drop_decrease",
                              f"antécédent ({src_txt}) : {zones_txt} — ne pas baisser le drop ; drop actuel inconnu "
                              "(renseigner la fiche de la paire)")
            warnings.append("antécédent tendon d'Achille / mollet : ne pas baisser le drop, mais le drop de la paire actuelle "
                            "est inconnu — compléter sa fiche de caractéristiques")
    ap = "ankle_sprain_low_stack_wide_base"
    ankle = [e for e in entries if e.get("zone") == R.param(ap, "zone")]
    sprain = next((e for e in ankle if e.get("sprain")), None)
    by_side: Dict[str, int] = {}
    for e in ankle:
        if e["source"] == "health" and (e.get("score") or 0) >= R.param(ap, "min_score"):
            side = e.get("side") or "?"
            by_side[side] = by_side.get(side, 0) + 1
    side_hit = max(by_side.items(), key=lambda kv: kv[1]) if by_side else None
    ankle_reason = None
    if sprain:
        ankle_reason = f"entorse de cheville déclarée au profil (« {sprain['text']} »)"
    elif side_hit and side_hit[1] >= R.param(ap, "min_episodes") and side_hit[0] != "?":
        side_fr = {"left": "gauche", "right": "droit"}.get(side_hit[0], side_hit[0])
        ankle_reason = (f"douleurs répétées à la cheville ({side_hit[1]} épisodes d'au moins {_fmt(R.param(ap, 'min_score'))}/10, "
                        f"même côté : {side_fr})")
    elif side_hit and side_hit[1] >= R.param(ap, "min_episodes"):
        notes.append("douleurs à la cheville répétées mais côté non précisé : la règle « même côté » ne peut pas être vérifiée, "
                     "non appliquée (préciser le côté en déclarant la douleur)")
    if ankle_reason:
        cur_stack = _num((_spec_value((replaced or {}).get("spec"), "stack_heel_mm") or {}).get("value"))
        if cur_stack is None and ref_stacks:
            cur_stack = min(ref_stacks)
        reason = ankle_reason + " — pile du talon au plus égale à celle de la paire actuelle, base large (avis d'experts)"
        if cur_stack is not None:
            T["stack_heel_mm"].set_range(ap, None, cur_stack, reason, safety=True)
        else:
            T["stack_heel_mm"].note(ap, reason + " ; pile actuelle inconnue")
        T["toe_box"].set_allowed(ap, ["standard", "wide"], "base large : avant-pied non étroit (avis d'experts)", safety=True)
    if mass is not None and mass > R.param("mass_minimalism_caution", "threshold_kg"):
        if ref_mi:
            T["minimalist_index_pct"].set_range(
                "mass_minimalism_caution", None, max(ref_mi),
                f"masse {_fmt(mass)} kg > {_fmt(R.param('mass_minimalism_caution', 'threshold_kg'))} kg : "
                "pas de pas vers plus de minimalisme (index plafonné à celui de la référence)", safety=True)
        else:
            R.mark("mass_minimalism_caution")
            warnings.append(f"masse {_fmt(mass)} kg > {_fmt(R.param('mass_minimalism_caution', 'threshold_kg'))} kg : prudence "
                            "avec une chaussure plus minimaliste que l'actuelle (index de référence indisponible)")

    # --- 4. terrain ---------------------------------------------------------------------------------
    usage = (replaced or {}).get("usage") or {}
    terrain = usage.get("terrain") or {}
    trail_share = (terrain.get("trail") or {}).get("share_km")
    road_share = (terrain.get("road") or {}).get("share_km")
    eff = role
    if role not in ROLES:
        eff = None
        notes.append(f"rôle « {role} » inconnu de ce moteur : plages larges, aucune règle de terrain ni de course appliquée")
    elif role in ("race", "mixed", "mixed_long"):
        if replaced and (trail_share is not None or road_share is not None):
            notes.append("terrain déduit de l'USAGE de la paire remplacée, pas de la course visée : à confirmer par l'athlète")
        if trail_share is not None and trail_share >= 0.7:
            eff = "trail"
        elif road_share is not None and road_share >= 0.7:
            eff = "road_easy"
        else:
            eff = None
            notes.append("rôle « " + role + " » sans terrain dominant connu : aucune règle de crampons appliquée "
                         "(passer --replace d'une paire dont l'usage est connu)")
    if eff in ROAD_ROLES:
        T["plate"].set_allowed("terrain_rock_plate", [x for x in PLATES if x != "rock_plate"],
                               "route : pas de plaque anti-roche (avis d'experts)")
        T["lug_depth_mm"].set_range("terrain_lugs_hard", None, float(R.param("terrain_lugs_hard", "max_lug_mm")),
                                    "terrain dur (route) : crampons de 4 mm au plus (avis d'experts)")
    elif eff in TRAIL_ROLES:
        wet = usage.get("wet") or {}
        dpk = usage.get("d_plus_m_per_km")
        soft_hints = []
        if wet.get("share") is not None and wet.get("with_weather", 0) >= R.param("terrain_lugs_soft", "min_sessions_with_weather") \
                and wet["share"] >= R.param("terrain_lugs_soft", "wet_share"):
            soft_hints.append(f"{wet['share'] * 100:.0f} % de séances humides")
        if dpk is not None and dpk >= R.param("terrain_lugs_soft", "d_plus_m_per_km"):
            soft_hints.append(f"D+ {_fmt(dpk)} m/km")
        if soft_hints:
            T["lug_depth_mm"].set_range("terrain_lugs_soft", float(R.param("terrain_lugs_soft", "min_lug_mm")), None,
                                        "trail avec indices de terrain meuble (" + ", ".join(soft_hints) + ") : crampons de 5 mm "
                                        "au moins — substituts du terrain, approximation du projet (avis d'experts)")
        else:
            notes.append("trail sans indice de terrain meuble dans l'usage (pluie, D+/km) : pas de contrainte de crampons ; "
                         "l'usage ne distingue ni la boue ni la roche, à préciser par l'athlète")
        R.mark("terrain_rock_plate")
        options.append({"id": "rock_plate", "field": "plate", "values": ["rock_plate"], "kind": "terrain", "rule": "terrain_rock_plate",
                        "confidence": R.by_id["terrain_rock_plate"]["confidence"],
                        "text": "plaque anti-roche : option si votre terrain est rocheux (non détectable dans les données, à confirmer)"})

    # --- plaque / stabilité : options ---------------------------------------------------------------
    if ref_plates:
        T["plate"].set_allowed("comfort_first", ref_plates,
                               "plaque des paires de référence : " + ", ".join(PLATE_FR[v] for v in ref_plates))
    else:
        notes.append("plaque : aucune plaque de référence connue, toutes les valeurs restent permises (la plaque est une option, jamais une exigence)")
    if role in ("race", "road_tempo"):
        R.mark("race_performance_option")
        options.append({"id": "performance_plate_foam", "field": "plate", "values": ["carbon", "nylon"], "kind": "performance",
                        "rule": "race_performance_option", "confidence": R.by_id["race_performance_option"]["confidence"],
                        "text": "plaque et mousse haute performance : option de PERFORMANCE (économie de course), aucune donnée sur les "
                                "blessures ; à réserver à la course et aux séances rapides"})
    if role == "race":
        lim = R.param("race_stack_limit", "road_max_stack_mm")
        R.mark("race_stack_limit")
        if eff == "trail":
            notes.append("course de trail : pas de limite d'épaisseur de semelle selon la FAQ World Athletics (extraits ; à confirmer dans le règlement de l'épreuve)")
        elif eff in ROAD_ROLES:
            T["stack_heel_mm"].set_range("race_stack_limit", None, float(lim),
                                         f"course sur route homologuée : pile de {_fmt(lim)} mm au plus (World Athletics)")
        else:
            notes.append(f"limite de pile World Athletics de {_fmt(lim)} mm sur route ; trail et montagne sans limite d'épaisseur "
                         "(FAQ, extraits) — terrain de la course non précisé")
    if ref_stability or stability_wanted:
        options.append({"id": "stability", "field": "stability_devices", "kind": "option", "rule": "no_foot_type_prescription",
                        "confidence": R.by_id["no_foot_type_prescription"]["confidence"],
                        "text": "dispositifs de stabilité : option seulement parce qu'ils sont déjà confortables pour vous (jamais une prescription selon le type de pied)"})

    # --- rappel : rotation ---------------------------------------------------------------------------
    R.mark("rotation_reminder")
    minp = R.param("rotation_reminder", "min_pairs")
    active = inp.get("active_pairs")
    reminders.append({"rule": "rotation_reminder", "confidence": R.by_id["rotation_reminder"]["confidence"],
                      "text": f"viser au moins {minp} paires aux rôles distincts en rotation (étude observationnelle : association, pas causalité)"
                              + (f" ; {active} paire(s) active(s) au profil" if active is not None else "")})

    targets = {f: T[f].public() for f in ("drop_mm", "stack_heel_mm", "midsole_softness", "lug_depth_mm", "toe_box",
                                           "plate", "minimalist_index_pct")}
    return {
        "role": role,
        "effective_terrain": eff,
        "replace": (replaced or {}).get("gear_id"),
        "insufficient_data": insufficient,
        "references": [{"gear_id": r["gear_id"], "comfort": r.get("comfort"), "would_rebuy": r.get("would_rebuy")} for r in refs],
        "inputs": {"mass_kg": mass, "mass_source": inp.get("mass_source"), "change_wanted": changes,
                   "injury_history": {"sources": history_sources, "entries": len(entries),
                                      "zones": dict(sorted(by_zone.items()))}},
        "targets": targets,
        "options": options,
        "reminders": reminders,
        "warnings": warnings,
        "notes": notes,
        "rules_applied": [R.applied[rid] for rid in [r["id"] for r in rules_doc["rules"]] if rid in R.applied],
        "disclaimer": rules_doc["disclaimer"],
    }


# ---------------------------------------------------------------------------
# Rendu texte
# ---------------------------------------------------------------------------


def _target_line(t: dict) -> str:
    if "allowed" in t:
        fr = {"midsole_softness": SOFTNESS_FR, "toe_box": TOE_BOX_FR, "plate": PLATE_FR}[t["field"]]
        val = ", ".join(fr[v] for v in t["allowed"])
    else:
        lo, hi = t.get("min"), t.get("max")
        val = (f"{_fmt(lo)} à {_fmt(hi)}" if lo is not None and hi is not None
               else f">= {_fmt(lo)}" if lo is not None else f"<= {_fmt(hi)}" if hi is not None else "libre")
    return f"{t['label']} : {val}  [{CONFIDENCE_LABELS_FR[t['confidence']]}]"


def render_text(rep: dict) -> str:
    if rep.get("error"):
        return rep["error"]
    lines = [f"Besoins pour le rôle « {rep['role']} »" + (f" (remplace {rep['replace']})" if rep.get("replace") else "")]
    if rep["insufficient_data"]:
        lines.append("DONNÉES INSUFFISANTES : aucune paire de référence (would_rebuy = yes et confort >= 7) — plages larges.")
    else:
        lines.append("Référence : " + ", ".join(r["gear_id"] for r in rep["references"]))
    for t in rep["targets"].values():
        lines.append("- " + _target_line(t))
        for reason in t["reasons"]:
            lines.append("    · " + reason)
        for c in t.get("conflicts", []):
            lines.append("    ! " + c)
        if t.get("advisory"):
            ad = t["advisory"]
            lines.append(f"    ~ bande indicative {_fmt(ad['min'])} à {_fmt(ad['max'])} ({ad['basis']}) : {ad['reason']}")
    if rep["options"]:
        lines.append("Options :")
        lines += [f"- {o['text']} [{CONFIDENCE_LABELS_FR[o['confidence']]}]" for o in rep["options"]]
    hist = rep["inputs"]["injury_history"]
    lines.append("Antécédents lus : " + ("; ".join(
        f"{s_['label']}" + (f" ({s_['period']})" if s_.get("period") else "") + f" -> {s_['entries']} entrée(s)"
        for s_ in hist["sources"]) or "aucune source") + (" — aucun antécédent trouvé" if not hist["entries"] else ""))
    for r in rep["reminders"]:
        lines.append("Rappel : " + r["text"])
    for w in rep["warnings"]:
        lines.append("Attention : " + w)
    for n in rep["notes"]:
        lines.append("Note : " + n)
    refs: Dict[str, dict] = {}
    for rule in rep["rules_applied"]:
        for ref in rule["references"]:
            refs[ref["id"]] = ref
    if refs:
        lines.append("Références :")
        lines += [f"- {r['citation']} {r['url']}" for r in refs.values()]
    lines.append(rep["disclaimer"])
    return "\n".join(lines)
