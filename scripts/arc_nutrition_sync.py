#!/usr/bin/env python3
"""arc_nutrition_sync.py — Plan de poussée des apports vers Garmin Connect (#167).

Le modèle ne fait QUE deux choses : appeler les outils du serveur MCP `garmin`
(lectures, puis écritures après un « oui » explicite de l'athlète) et passer du JSON
à ce script. Tout le raisonnement — quoi créer, quoi journaliser, quoi NE PAS
refaire — est ici, en pur stdlib, déterministe et testable sans modèle ni Garmin.

Opt-in strict : `[nutrition].garmin_sync` vaut `off` par défaut (clé absente, vide ou
invalide = `off`). `ask` = le coach PROPOSE la poussée, jamais automatique, jamais en
headless. Avec `[data].source` ≠ `garmin` (`intervals`, `strava`), la fonction est indisponible
(aucun équivalent) et le script le dit (`reason: "source_intervals"` / `"source_strava"`).

Outils `garmin-mcp` utilisés (noms, paramètres et formes vérifiés dans le code du commit
épinglé `GARMIN_MCP_REF` d'`install.sh` : `src/garmin_mcp/nutrition.py`,
`data_management.py`, `health_wellness.py`, et le test live `tests/e2e/` du même dépôt) :

  lecture   get_custom_foods(search, start, limit) → {"customFoods": [{"foodMetaData":
            {"foodId", "foodName", ...}, "nutritionContents": [{"servingId", "calories",
            "carbs", ...}]}]} ; texte brut « No custom foods found. » si vide
            get_nutrition_daily_food_log(date) → {"mealDetails": [{"mealName",
            "loggedFoods": [{"logId", "foodMetaData": {"foodId", "foodName"}, ...}]}]} ;
            texte brut « No food log data found for <date>. » si vide
            get_hydration_data(date) → JSON brut Garmin (forme NON documentée par
            garmin-mcp : le total du jour n'est lu que s'il porte `valueInML`, sinon
            inconnu — jamais deviné)
  écriture  create_custom_food(food_name, calories, serving_unit, number_of_units,
            brand_name, carbs, protein, fat, ...) — absolus PAR PORTION
            log_custom_food(meal_date, meal_time "HH:MM:SS", food_id, serving_id,
            serving_qty, source) — le repas est déduit de l'heure
            log_food(meal_date, meal_time, name, calories, carbs, protein, fat) — Quick Add
            add_hydration_data(value_in_ml, cdate, timestamp "YYYY-MM-DDThh:mm:ss.sss") —
            AJOUTE au total du jour (n'est pas idempotent côté Garmin : c'est ce script
            et `garmin_pushed` qui le rendent idempotent)

Non exposés (volontairement) : `delete_food_log`, `update_custom_food`, `upsert_and_log` —
une écriture irréversible ou qui écrase une entrée de l'athlète se corrige dans Garmin Connect.

Sous-commandes (JSON en entrée via --input ou stdin, JSON en sortie)
--------------------------------------------------------------------
    mode    [--workspace W]        disponibilité résolue (mode, source, available, reason)
    plan                           construit le plan de poussée (voir plus bas)
    record                         transforme les écritures exécutées en entrées `garmin_pushed`
    import-log                     lecture inverse : journal Garmin du jour → clés du contrat

plan — entrée
    {"date": "2026-10-02",
     "items": [{"product": "gels", "qty": 2, "time": "09:30:00"}],          # catalogue
     "quick_adds": [{"name": "Dîner", "calories": 800, "carbs_g": 100,
                     "protein_g": 30, "fat_g": 25, "time": "20:00:00"}],     # rapport nutrition
     "fluids": [{"ml": 500, "time": "09:30:00"}],
     "default_time": "09:30:00",           # heure de repli (début de séance), jamais inventée
     "estimate_kcal_from_carbs": false,    # true UNIQUEMENT si l'athlète a accepté l'approximation
     "catalogue_paths": [...],             # défaut : resources/nutrition/catalogue-produits-*.md
     "day_source": "manual" | "garmin",    # `intake_source` du fichier nutrition du jour
     "already_pushed": [...],              # `garmin_pushed` déjà écrit (activité + nutrition du jour)
     "garmin_custom_foods": {"<product>": <réponse brute de get_custom_foods(search=product)>},
     "garmin_food_log": <réponse brute de get_nutrition_daily_food_log(date)>,
     "garmin_hydration": <réponse brute de get_hydration_data(date)>,
     "confirm_keys": ["ab12..."],          # doublons que l'athlète a explicitement confirmés
     "mode": "ask", "source": "garmin"}    # surcharges de TEST (`build_plan` seulement) : la CLI les
                                           # ignore et lit toujours la configuration vivante

plan — sortie : `status` ∈ disabled | blocked | reads_needed | needs_input | ready |
nothing_to_push ; `reads_needed` (lectures à faire AVANT de rappeler le plan), `steps`
(écritures prêtes, chacune avec sa `key`), `skipped` (déjà poussé), `confirm_duplicates`
(déjà dans le journal Garmin sans trace de poussée : à demander), `needs_input` (produit
inconnu/ambigu, calories absentes, heure absente… — jamais d'invention), `warnings`.

Le script ne touche JAMAIS Garmin et n'écrit aucun fichier.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_log as _log  # noqa: E402  (catalogue + correspondance produit partagés avec /log)

MODES = ("off", "ask")
DEFAULT_MODE = "off"

ASSUMPTIONS = {
    "kcal_from_carbs": (
        "Calories d'un produit du catalogue sans colonne d'énergie : 4 kcal par gramme de "
        "glucides — approximation du projet (valeur d'Atwater usuelle pour les glucides), "
        "appliquée UNIQUEMENT si l'athlète l'a acceptée (`estimate_kcal_from_carbs`) et "
        "signalée `calories_estimated` ; une valeur d'étiquette est toujours préférable."
    ),
    "library_mismatch_tolerance": (
        "Un aliment personnalisé Garmin du même nom que le produit du catalogue n'est réutilisé "
        "que si ses glucides par portion (quand Garmin les renvoie) diffèrent de moins de 10 % "
        "de ceux du catalogue — seuil du projet, pas une valeur de la littérature ; au-delà, "
        "l'athlète tranche (aucune modification d'un aliment existant n'est exposée)."
    ),
}
KCAL_PER_G_CARBS = 4.0
LIBRARY_MISMATCH_TOLERANCE = 0.10
MAX_HYDRATION_ML = 10000   # plafond de garminconnect.add_hydration_data, par appel

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NO_DATA_PREFIXES = ("no custom foods found", "no food log data found", "no hydration data found")


class NutritionSyncError(ValueError):
    """Entrée malformée (date illisible, JSON invalide...)."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def sync_mode(config: dict, warn: bool = True) -> str:
    """`[nutrition].garmin_sync`, jamais en levant : absent, vide ou invalide → `off`."""
    raw = (config.get("nutrition") or {}).get("garmin_sync")
    if raw in (None, ""):
        return DEFAULT_MODE
    if isinstance(raw, str) and raw.strip().lower() in MODES:
        return raw.strip().lower()
    if warn:
        print(f"avertissement : [nutrition].garmin_sync = {raw!r} hors de {MODES} — "
              f"traité comme « {DEFAULT_MODE} » (aucune poussée vers Garmin).", file=sys.stderr)
    return DEFAULT_MODE


def availability(mode: str, source: str) -> dict:
    """Fonction utilisable ? `reason` explicite pour que l'agent le DISE."""
    source = (source or "garmin").strip().lower()
    if source != "garmin":
        # intervals.icu (#68) et Strava (#164) : aucun journal nutritionnel ni hydratation équivalents.
        label = {"intervals": "intervals.icu", "strava": "Strava"}.get(source, source)
        return {"mode": mode, "source": source, "available": False, "reason": f"source_{source}",
                "message": f"Indisponible : [data].source = « {source} » — {label} n'a pas de "
                           "journal nutritionnel ni d'hydratation équivalents à ceux de Garmin Connect."}
    if mode != "ask":
        return {"mode": mode, "source": source, "available": False, "reason": "off",
                "message": "Désactivé : [nutrition].garmin_sync = « off » (défaut, opt-in)."}
    return {"mode": mode, "source": source, "available": True, "reason": None, "message": None}


# ---------------------------------------------------------------------------
# Utilitaires de lecture des réponses Garmin
# ---------------------------------------------------------------------------

def _norm(text) -> str:
    return _log.normalize_name(str(text or ""))


def _load_response(raw):
    """Réponse brute d'un outil → (état, données). États : `absent` (non fournie),
    `empty` (texte « No ... found »), `error` (texte « Error ... » ou illisible),
    `ok` (JSON décodé)."""
    if raw is None:
        return "absent", None
    if isinstance(raw, (dict, list)):
        return "ok", raw
    text = str(raw).strip()
    if not text:
        return "empty", None
    low = text.lower()
    if low.startswith(_NO_DATA_PREFIXES):
        return "empty", None
    if low.startswith("error"):
        return "error", text
    try:
        return "ok", json.loads(text)
    except json.JSONDecodeError:
        return "error", text


def _custom_foods(data) -> list:
    foods = data.get("customFoods", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    out = []
    for f in foods:
        if not isinstance(f, dict):
            continue
        meta = f.get("foodMetaData", f)
        contents = f.get("nutritionContents") or [{}]
        first = contents[0] if contents and isinstance(contents[0], dict) else {}
        out.append({
            "name": str(meta.get("foodName", "")),
            "food_id": str(meta.get("foodId") or f.get("foodId") or ""),
            "serving_id": str(first.get("servingId") or ""),
            "carbs": _num(first.get("carbs")),
            "calories": _num(first.get("calories")),
        })
    return out


def _logged_foods(data) -> list:
    out = []
    meals = data.get("mealDetails", []) if isinstance(data, dict) else []
    for meal in meals or []:
        for food in (meal or {}).get("loggedFoods") or []:
            if not isinstance(food, dict):
                continue
            meta = food.get("foodMetaData") or {}
            out.append({"log_id": str(food.get("logId") or ""), "food_id": str(meta.get("foodId") or ""),
                        "name": str(meta.get("foodName") or "")})
    return out


def _num(value) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _time(raw) -> Optional[str]:
    """HH:MM[:SS] → HH:MM:SS, sinon None (jamais d'heure devinée)."""
    if raw in (None, ""):
        return None
    m = _TIME_RE.match(str(raw).strip())
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if h > 23 or mi > 59 or s > 59:
        return None
    return f"{h:02d}:{mi:02d}:{s:02d}"


def _key(date: str, kind: str, name: str, qty, when: str) -> str:
    raw = f"{date}|{kind}|{_norm(name)}|{float(qty):g}|{when}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Catalogue enrichi (portion, énergie, macros)
# ---------------------------------------------------------------------------

_GRAMS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(g|ml)\b", re.IGNORECASE)


def parse_catalogue_rows(text: str) -> list:
    """Comme `arc_log.parse_catalogue`, plus la portion (`serving_unit`, `serving_size`) et les
    colonnes facultatives énergie/protéines/lipides. Une valeur absente = clé omise."""
    rows, header, idx = [], None, {}
    for line in text.splitlines():
        if not line.strip().startswith("|") or _log._TABLE_SEPARATOR_RE.match(line.strip()):
            continue
        cells = _log._split_row(line)
        if not cells:
            continue
        if header is None:
            header = [_norm(c) for c in cells]
            for i, c in enumerate(header):
                if "produit" in c and "name" not in idx:
                    idx["name"] = i
                elif "portion" in c and "portion" not in idx:
                    idx["portion"] = i
                elif ("glucide" in c or "carb" in c) and "carbs" not in idx:
                    idx["carbs"] = i
                elif ("kcal" in c or "calorie" in c or "energie" in c) and "kcal" not in idx:
                    idx["kcal"] = i
                elif "prot" in c and "protein" not in idx:
                    idx["protein"] = i
                elif ("lipide" in c or "fat" in c or "graisse" in c) and "fat" not in idx:
                    idx["fat"] = i
            continue
        if "name" not in idx or "carbs" not in idx or len(cells) <= max(idx.values()):
            continue
        name = cells[idx["name"]].strip()
        carbs = _log._first_number(cells[idx["carbs"]])
        if not name or carbs is None:
            continue
        row = {"name": name, "carbs_g": carbs}
        if "portion" in idx:
            m = _GRAMS_RE.search(cells[idx["portion"]])
            if m:
                row["serving_size"] = float(m.group(1).replace(",", "."))
                row["serving_unit"] = m.group(2).upper()
        for key, field in (("kcal", "kcal"), ("protein", "protein_g"), ("fat", "fat_g")):
            if key in idx:
                val = _log._first_number(cells[idx[key]])
                if val is not None:
                    row[field] = val
        rows.append(row)
    return rows


def _load_catalogue(paths) -> list:
    rows = []
    for rel in _log.resolve_catalogue_paths(paths):
        p = Path(rel)
        if not p.is_absolute():
            p = _log.REPO_ROOT / p
        if p.exists():
            rows.extend(parse_catalogue_rows(p.read_text(encoding="utf-8")))
    return rows


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def _pushed_keys(already_pushed) -> set:
    return {str(e.get("key")) for e in (already_pushed or []) if isinstance(e, dict) and e.get("key")}


def build_plan(payload: dict, config: Optional[dict] = None) -> dict:
    date = str(payload.get("date") or "")
    if not _DATE_RE.match(date):
        raise NutritionSyncError(f"date AAAA-MM-JJ requise : {payload.get('date')!r}")
    config = config or {}
    mode = str(payload.get("mode") or sync_mode(config)).strip().lower()
    source = str(payload.get("source") or (config.get("data") or {}).get("source") or "garmin")
    avail = availability(mode if mode in MODES else DEFAULT_MODE, source)
    out = {"date": date, "enabled": avail["available"], "reason": avail["reason"], "status": None,
           "reads_needed": [], "steps": [], "skipped": [], "confirm_duplicates": [],
           "needs_input": [], "warnings": []}
    if not avail["available"]:
        out["status"] = "disabled"
        out["message"] = avail["message"]
        return out
    if payload.get("day_source") == "garmin":
        # Règle de la source unique par jour : ce jour a été importé DEPUIS Garmin, y repousser
        # le même apport le compterait deux fois.
        out["status"] = "blocked"
        out["reason"] = "day_source_garmin"
        out["message"] = ("Ce jour est alimenté depuis le journal Garmin (`intake_source: \"garmin\"`) : "
                          "rien n'est poussé, une seule source de vérité par jour.")
        return out

    pushed = _pushed_keys(payload.get("already_pushed"))
    confirmed = {str(k) for k in (payload.get("confirm_keys") or [])}
    default_time = _time(payload.get("default_time"))
    estimate = bool(payload.get("estimate_kcal_from_carbs"))
    items = payload.get("items") or []
    quick_adds = payload.get("quick_adds") or []
    fluids = payload.get("fluids") or []

    log_state, log_data = _load_response(payload.get("garmin_food_log"))
    day_log = _logged_foods(log_data) if log_state == "ok" else []
    if log_state == "error":
        out["status"] = "blocked"
        out["reason"] = "garmin_read_error"
        out["message"] = f"Lecture du journal Garmin en échec : {log_data} — aucune écriture sans la vérification de doublon."
        return out

    catalogue = _load_catalogue(payload.get("catalogue_paths")) if items else []
    foods_by_product = payload.get("garmin_custom_foods") or {}

    # -- lectures nécessaires avant toute écriture ---------------------------
    reads = []
    resolved = []   # (item, produit catalogue, qty, heure)
    for item in items:
        name = str(item.get("product", "")).strip()
        try:
            qty = _log.parse_quantity(item.get("qty", 1))
        except _log.ArcLogError as exc:
            out["needs_input"].append({"what": "quantity", "item": name, "reason": str(exc)})
            continue
        if qty <= 0:
            out["needs_input"].append({"what": "quantity", "item": name, "reason": "quantité nulle"})
            continue
        verdict, product = _log.match_product(name, catalogue)
        if verdict == "unknown":
            out["needs_input"].append({
                "what": "product", "item": name,
                "reason": "produit absent du catalogue : jamais poussé vers Garmin sans valeurs "
                          "d'étiquette fournies par l'athlète (ajoutez-le au catalogue ou donnez ses "
                          "valeurs)"})
            continue
        if verdict == "ambiguous":
            out["needs_input"].append({"what": "product", "item": name, "reason": "produit ambigu",
                                       "candidates": product})
            continue
        when = _time(item.get("time")) or default_time
        if when is None:
            out["needs_input"].append({"what": "meal_time", "item": product["name"],
                                       "reason": "heure du repas absente (HH:MM:SS) — Garmin range l'entrée "
                                                 "dans un repas selon l'heure, jamais devinée"})
            continue
        resolved.append((product, qty, when))
        if product["name"] not in foods_by_product:
            reads.append({"tool": "get_custom_foods", "args": {"search": product["name"]}})
    if log_state == "absent" and (resolved or quick_adds):
        reads.append({"tool": "get_nutrition_daily_food_log", "args": {"date": date}})
    hyd_state, hyd_data = _load_response(payload.get("garmin_hydration"))
    if fluids and hyd_state == "absent":
        reads.append({"tool": "get_hydration_data", "args": {"date": date}})
    # dédoublonne les lectures en conservant l'ordre
    seen, uniq = set(), []
    for r in reads:
        sig = (r["tool"], json.dumps(r["args"], sort_keys=True))
        if sig not in seen:
            seen.add(sig)
            uniq.append(r)
    if uniq:
        out["status"] = "reads_needed"
        out["reads_needed"] = uniq
        return out

    # -- produits du catalogue → aliments personnalisés Garmin ---------------
    created = set()
    for product, qty, when in resolved:
        pname = product["name"]
        key = _key(date, "custom_food", pname, qty, when)
        if key in pushed:
            out["skipped"].append({"key": key, "name": pname, "reason": "already_pushed"})
            continue
        state, data = _load_response(foods_by_product.get(pname))
        if state == "error":
            out["warnings"].append(f"get_custom_foods({pname!r}) en échec : {data}")
            out["needs_input"].append({"what": "garmin_read", "item": pname, "reason": "lecture Garmin en échec"})
            continue
        matches = [f for f in _custom_foods(data) if _norm(f["name"]) == _norm(pname)] if state == "ok" else []
        carbs = product["carbs_g"]
        if len(matches) > 1:
            out["needs_input"].append({"what": "garmin_food", "item": pname,
                                       "reason": "plusieurs aliments personnalisés Garmin portent ce nom",
                                       "candidates": [{"food_id": m["food_id"]} for m in matches]})
            continue
        food_id = serving_id = None
        if matches:
            m = matches[0]
            if m["carbs"] is not None and carbs and abs(m["carbs"] - carbs) / carbs > LIBRARY_MISMATCH_TOLERANCE:
                out["needs_input"].append({
                    "what": "garmin_food_mismatch", "item": pname,
                    "reason": f"l'aliment Garmin existant a {m['carbs']:g} g de glucides par portion, le "
                              f"catalogue {carbs:g} g — jamais modifié ni réutilisé sans votre accord"})
                continue
            if not m["food_id"] or not m["serving_id"]:
                out["needs_input"].append({"what": "garmin_food", "item": pname,
                                           "reason": "foodId/servingId introuvables dans la réponse Garmin"})
                continue
            food_id, serving_id = m["food_id"], m["serving_id"]
        else:
            calories, estimated = product.get("kcal"), False
            if calories is None:
                if estimate:
                    calories, estimated = carbs * KCAL_PER_G_CARBS, True
                else:
                    out["needs_input"].append({
                        "what": "calories", "item": pname,
                        "reason": "calories par portion absentes du catalogue — Garmin les exige : "
                                  "donnez la valeur d'étiquette, ou acceptez l'approximation de "
                                  "4 kcal/g de glucides (`estimate_kcal_from_carbs`)"})
                    continue
            if "serving_size" not in product:
                out["needs_input"].append({
                    "what": "serving", "item": pname,
                    "reason": "portion en g ou ml illisible dans le catalogue (ex. « 1 sachet (40 g) »)"})
                continue
            if pname not in created:
                args = {"food_name": pname, "calories": round(calories, 1), "serving_unit": product["serving_unit"],
                        "number_of_units": product["serving_size"], "carbs": carbs}
                for src, dst in (("protein_g", "protein"), ("fat_g", "fat")):
                    if src in product:
                        args[dst] = product[src]
                step = {"key": _key(date, "create_food", pname, 1, "-"), "kind": "create_custom_food", "args": args,
                        "note": "créé une seule fois puis réutilisé ; en cas de réponse vide (204) relire "
                                "get_custom_foods(search) pour récupérer foodId/servingId"}
                if estimated:
                    step["calories_estimated"] = True
                out["steps"].append(step)
                created.add(pname)
        dup = [e for e in day_log if food_id and e["food_id"] == food_id]
        step = {"key": key, "kind": "log_custom_food", "name": pname, "qty": qty,
                "args": {"meal_date": date, "meal_time": when, "food_id": food_id, "serving_id": serving_id,
                         "serving_qty": qty, "source": "GARMIN"}}
        if food_id is None:
            step["food_ref"] = pname   # ids connus seulement après create_custom_food
        if dup and key not in confirmed:
            out["confirm_duplicates"].append({"key": key, "name": pname,
                                              "reason": "déjà au journal Garmin du jour",
                                              "log_ids": [e["log_id"] for e in dup if e["log_id"]]})
            continue
        out["steps"].append(step)

    # -- apports déclarés par rapport (Quick Add) ----------------------------
    for qa in quick_adds:
        name = str(qa.get("name", "")).strip()
        when = _time(qa.get("time")) or default_time
        macros = {k: _num(qa.get(k)) for k in ("calories", "carbs_g", "protein_g", "fat_g")}
        if not name:
            out["needs_input"].append({"what": "name", "item": "", "reason": "nom d'entrée vide"})
            continue
        if when is None:
            out["needs_input"].append({"what": "meal_time", "item": name, "reason": "heure du repas absente"})
            continue
        missing = [k for k, v in macros.items() if v is None]
        if missing:
            out["needs_input"].append({"what": "macros", "item": name,
                                       "reason": f"valeurs manquantes ({', '.join(missing)}) — Quick Add les exige"})
            continue
        key = _key(date, "quick_add", name, macros["calories"], when)
        if key in pushed:
            out["skipped"].append({"key": key, "name": name, "reason": "already_pushed"})
            continue
        dup = [e for e in day_log if _norm(e["name"]) == _norm(name)]
        if dup and key not in confirmed:
            out["confirm_duplicates"].append({"key": key, "name": name, "reason": "même nom déjà au journal Garmin du jour",
                                              "log_ids": [e["log_id"] for e in dup if e["log_id"]]})
            continue
        out["steps"].append({"key": key, "kind": "log_food", "name": name, "qty": 1,
                             "args": {"meal_date": date, "meal_time": when, "name": name,
                                      "calories": macros["calories"], "carbs": macros["carbs_g"],
                                      "protein": macros["protein_g"], "fat": macros["fat_g"]}})

    # -- hydratation ----------------------------------------------------------
    if fluids:
        out["garmin_hydration_ml_today"] = None
        if hyd_state == "ok" and isinstance(hyd_data, dict) and _num(hyd_data.get("valueInML")) is not None:
            out["garmin_hydration_ml_today"] = _num(hyd_data.get("valueInML"))
        elif hyd_state == "error":
            out["warnings"].append(f"get_hydration_data en échec : {hyd_data}")
        else:
            out["warnings"].append("total d'hydratation Garmin du jour illisible (forme non documentée) — "
                                   "l'idempotence repose sur `garmin_pushed`")
    for fl in fluids:
        ml = _num(fl.get("ml") if isinstance(fl, dict) else fl)
        if ml is not None:
            # `add_hydration_data(value_in_ml: int)` : un volume fractionnaire serait refusé par le
            # schéma de l'outil — arrondi au ml (la clé porte la valeur réellement poussée).
            ml = float(round(ml))
        when = _time(fl.get("time") if isinstance(fl, dict) else None) or default_time
        if ml is None or ml <= 0 or ml > MAX_HYDRATION_ML:
            out["needs_input"].append({"what": "hydration", "item": str(fl),
                                       "reason": f"volume en ml entre 1 et {MAX_HYDRATION_ML} requis"})
            continue
        if when is None:
            out["needs_input"].append({"what": "meal_time", "item": f"{ml:g} ml", "reason": "heure absente"})
            continue
        key = _key(date, "hydration", "eau", ml, when)
        if key in pushed:
            out["skipped"].append({"key": key, "name": f"{ml:g} ml", "reason": "already_pushed"})
            continue
        out["steps"].append({"key": key, "kind": "add_hydration_data", "name": "eau", "ml": ml,
                             "args": {"value_in_ml": int(ml), "cdate": date,
                                      "timestamp": f"{date}T{when}.000"}})

    if out["needs_input"] and not out["steps"]:
        out["status"] = "needs_input"
    elif out["steps"]:
        out["status"] = "ready"
    elif out["confirm_duplicates"]:
        out["status"] = "needs_input"
    else:
        out["status"] = "nothing_to_push"
    return out


# ---------------------------------------------------------------------------
# record — entrées `garmin_pushed` après exécution
# ---------------------------------------------------------------------------

def record_pushed(payload: dict) -> dict:
    """`executed` : steps réellement exécutés (+ `food_id`/`serving_id` appris à la création) ;
    `food_log_before`/`food_log_after` (réponses brutes) permettent de rattacher le `log_id`
    quand une SEULE nouvelle entrée correspond — sinon `log_id` est omis, jamais deviné."""
    now = str(payload.get("now") or "")
    _, before = _load_response(payload.get("food_log_before"))
    _, after = _load_response(payload.get("food_log_after"))
    old_ids = {e["log_id"] for e in _logged_foods(before)} if before else set()
    new_entries = [e for e in _logged_foods(after) if e["log_id"] not in old_ids] if after else []
    entries = []
    for ex in payload.get("executed") or []:
        entry = {"key": str(ex["key"]), "kind": str(ex["kind"])}
        for field in ("name", "qty", "ml", "food_id", "serving_id"):
            if ex.get(field) not in (None, ""):
                entry[field] = ex[field]
        if ex["kind"] in ("log_custom_food", "log_food"):
            cands = [e for e in new_entries
                     if (ex.get("food_id") and e["food_id"] == str(ex["food_id"]))
                     or (ex["kind"] == "log_food" and _norm(e["name"]) == _norm(ex.get("name")))]
            if len(cands) == 1:
                entry["log_id"] = cands[0]["log_id"]
        if now:
            entry["at"] = now
        entries.append(entry)
    merged = [e for e in (payload.get("existing_garmin_pushed") or []) if isinstance(e, dict)]
    have = {e.get("key") for e in merged}
    merged.extend(e for e in entries if e["key"] not in have)
    return {"garmin_pushed": merged, "added": [e["key"] for e in entries if e["key"] not in have]}


# ---------------------------------------------------------------------------
# import-log — lecture inverse
# ---------------------------------------------------------------------------

def import_log(payload: dict, config: Optional[dict] = None) -> dict:
    """Journal Garmin du jour → clés du contrat `nutrition`, source déclarée `garmin`.

    Refuse un jour déjà miroir de `nutrition/*.md` (des `garmin_pushed` existent) : importer ce
    que l'on vient de pousser doublerait l'apport. Les totaux ne sont lus que dans
    `dailyNutritionContent` (calories/carbs/protein/fat — forme vérifiée sur l'endpoint de plage
    de garmin-mcp ; sur le journal du jour, à vérifier) ; absents, ils sont omis, jamais recalculés."""
    date = str(payload.get("date") or "")
    if not _DATE_RE.match(date):
        raise NutritionSyncError(f"date AAAA-MM-JJ requise : {payload.get('date')!r}")
    if payload.get("already_pushed"):
        return {"date": date, "status": "refused", "reason": "mirror_day",
                "message": "Ce jour a déjà été poussé vers Garmin depuis nutrition/ : source de vérité = "
                           "nutrition/*.md, rien n'est importé (sinon double comptage)."}
    state, data = _load_response(payload.get("garmin_food_log"))
    if state == "empty":
        return {"date": date, "status": "empty", "item_count": 0}
    if state != "ok":
        return {"date": date, "status": "error", "message": "journal Garmin absent ou illisible"}
    foods = _logged_foods(data)
    content = data.get("dailyNutritionContent") if isinstance(data, dict) else None
    out = {"date": date, "status": "ok", "intake_source": "garmin", "item_count": len(foods),
           "foods": [f["name"] for f in foods if f["name"]], "warnings": []}
    intake = {}
    if isinstance(content, dict):
        for src, dst in (("calories", "intake_kcal"), ("carbs", "carbs_g"), ("protein", "protein_g"), ("fat", "fat_g")):
            val = _num(content.get(src))
            if val is not None:
                intake[dst] = val
    if intake:
        out["intake"] = intake
    else:
        out["warnings"].append("totaux du jour absents de la réponse (`dailyNutritionContent`) — non estimés")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _config_for(workspace_arg):
    try:
        import arc_index
        from coach_setup import workspace_root
        return arc_index.load_config(workspace_root(workspace_arg))
    except Exception:
        return {}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("mode", "plan", "record", "import-log"):
        p = sub.add_parser(name)
        p.add_argument("--workspace", default=None, help="Racine du workspace (défaut : résolution standard)")
        if name != "mode":
            p.add_argument("--input", type=Path, default=None, help="Fichier JSON d'entrée (défaut : stdin)")
    args = parser.parse_args(argv)

    if args.cmd == "mode":
        config = _config_for(args.workspace)
        res = availability(sync_mode(config), (config.get("data") or {}).get("source", "garmin"))
        print(json.dumps(res, ensure_ascii=False))
        return 0
    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        payload = json.loads(raw)
        if args.cmd == "plan":
            # Toujours la configuration vivante : une entrée JSON ne peut pas activer la poussée
            # (`mode`/`source` y sont des surcharges de test de `build_plan`, ignorées ici).
            if isinstance(payload, dict):
                payload.pop("mode", None)
                payload.pop("source", None)
            result = build_plan(payload, _config_for(args.workspace))
        elif args.cmd == "record":
            result = record_pushed(payload)
        else:
            result = import_log(payload)
    except (json.JSONDecodeError, NutritionSyncError, KeyError, AttributeError, TypeError) as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
