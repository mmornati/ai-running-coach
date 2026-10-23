#!/usr/bin/env python3
"""arc_log.py — Arithmétique, correspondance catalogue et fusion pour `/log` (#67).

Le skill `log` fait analyser une saisie libre par le modèle ("2 gels + 500 ml
au km 15, genou gauche 3/10, RPE 7") : le modèle en extrait des ENTITÉS (quel
produit, quelle quantité, quelle zone douloureuse, quel score...), mais ne
fait JAMAIS lui-même la conversion catalogue, les sommes, ni la fusion avec un
fichier existant — un LLM invente parfois un chiffre qui a l'air plausible, et
rien ne le rend idempotent. Ce module fait tout ce calcul, en pur stdlib,
déterministe et testable indépendamment du modèle : JSON en entrée (entités
extraites), JSON en sortie (macros calculées, correspondances catalogue,
produits inconnus/ambigus, douleur normalisée, fusion avec le fichier
existant, détection de doublon).

Le catalogue produit (`resources/nutrition/catalogue-produits-*.md`, voir
`agents/nutritionist.md`) est un tableau Markdown à trois colonnes au moins :

    | Produit | Portion | Glucides |
    |---|---|---|
    | Gel Fixture Test | 1 sachet (40 g) | 32 g |

Correspondance produit : accents et casse ignorés, pluriel français simple
toléré des DEUX côtés — la requête ("gels") ET le nom du catalogue lui-même
("Barres" au pluriel dans un catalogue mal saisi) — et une correspondance
PARTIELLE par mot entier est acceptée ("gel" retrouve "Gel Fixture Test").
Mais si plusieurs produits distincts correspondent, c'est une AMBIGUÏTÉ
(jamais une devinette), et si aucun catalogue n'est fourni ou qu'aucun
produit ne correspond, c'est un produit INCONNU : dans les deux cas,
`carbs_g` est OMIS pour cette entrée plutôt qu'inventé — à l'agent appelant
de demander la valeur à l'athlète (voir `skills/log/SKILL.md`).

Ce module ne récupère PAS lui-même la valeur `[injury_risk].pain_consult_threshold`
en dur : il la résout depuis la configuration vivante du workspace
(`arc_index.load_config` + `arc_guardrails.injury_risk_settings`), pour ne
jamais diverger d'une valeur personnalisée par l'athlète.

Usage
-----
    python3 scripts/arc_log.py --input entree.json
    echo '{"nutrition_items": [...]}' | python3 scripts/arc_log.py
    python3 scripts/arc_log.py --workspace /chemin/vers/workspace --input entree.json

Entrée JSON (toutes les clés sont optionnelles)
------------------------------------------------
    {
      "catalogue_paths": ["resources/nutrition/catalogue-produits-famille.md"],
      "nutrition_items": [{"product": "gels", "qty": "2"}],
      "fluid_entries": ["500 ml", "50cl", "2 x 500 ml"],
      "pain": [{"location": "genou gauche", "score": "3"}],
      "rpe": "7",
      "pain_consult_threshold": 7.0,
      "raw_text": "2 gels + 500 ml au km 15, genou gauche 3/10, RPE 7",
      "timestamp": "2026-09-24T18:32:00+02:00",
      "existing_activity_arc": {"garmin_activity_id": 90000000001, "carbs_g": 32},
      "existing_pain": [{"location": "cheville", "score": 2}],
      "existing_log_entries": ["2 gels + 500 ml au km 15, genou gauche 3/10, RPE 7"]
    }

`catalogue_paths` omis → résolu par le motif
`resources/nutrition/catalogue-produits-*.md` depuis la racine du dépôt (celle
de ce script, `parents[1]`) ; liste vide explicite → aucun catalogue (tous les
`nutrition_items` ressortent `unknown`, raison `no_catalogue`).

Un `nutrition_items[i]` peut porter `carbs_g_per_unit` : la valeur en grammes
que l'ATHLÈTE a donnée lui-même pour un produit absent du catalogue (l'agent
la demande d'abord, ne l'invente jamais — voir `skills/log/SKILL.md`), après
quoi ce script fait la multiplication par `qty` et l'ajoute au total — jamais
une addition faite à la main côté agent, même pour ce cas déclaré.

`pain_consult_threshold` explicite prime sur la configuration ; sans lui, ce
script lit `config/workspace(.user).toml` du `--workspace` donné (ou du
répertoire courant) via `arc_guardrails.injury_risk_settings`, avec repli sur
`arc_guardrails.PAIN_CONSULT_THRESHOLD` si la configuration est illisible.

`raw_text` + `existing_log_entries` (les lignes de provenance déjà trouvées
sous le bloc ```arc du fichier visé, voir « Idempotence » plus bas) permettent
de détecter un doublon : un `raw_text` déjà présent, normalisé (espaces,
casse), met `"duplicate": true` dans la sortie et **n'ajoute aucune fusion**
(`activity_merge`/`pain_merge` absents) — à l'agent de demander avant de
compter deux fois la même déclaration.

`existing_activity_arc`/`existing_pain` déclenchent le calcul de fusion
(`activity_merge`, `pain_merge`) : addition des glucides/liquide, remplacement
du dernier RPE déclaré, jamais d'écrasement d'une clé non concernée par `/log`
(ce module ne touche jamais `garmin_activity_id`, `distance_m`, etc. — il rend
seulement les clés à fusionner, l'écriture du fichier complet reste faite par
l'agent, qui a la vue d'ensemble du Markdown existant, narratif compris).

Sortie JSON (clés présentes seulement si les entrées correspondantes le sont)
------------------------------------------------------------------------------
    {
      "nutrition": {
        "matched": [{"input": "gels", "matched_product": "Gel Fixture Test",
                      "qty": 2.0, "carbs_g": 64.0}],
        "unknown": [], "ambiguous": [], "carbs_g": 64.0
      },
      "fluids": {"matched": [...], "unknown": [...], "fluid_intake_ml": 500.0},
      "pain": {"entries": [{"location": "genou gauche", "score": 3.0, "consult": false}],
               "unknown": [], "consult_threshold": 7.0},
      "rpe": 7.0,
      "duplicate": false,
      "provenance_line": "[/log 2026-09-24T18:32:00+02:00] 2 gels + 500 ml au km 15, genou gauche 3/10, RPE 7",
      "activity_merge": {"carbs_g": 64.0, "fluid_intake_ml": 500.0, "rpe": 7.0},
      "pain_merge": [{"location": "cheville", "score": 2}, {"location": "genou gauche", "score": 3.0}],
      "warnings": []
    }

Cycle menstruel (#166, opt-in) : `"cycle": {"phase": "lutéale", "day": "21"}` ne
produit une sortie `cycle` + `health_merge` (`cycle_phase`, `cycle_day`,
`cycle_source: "manual"`, à fusionner dans le bloc du fichier santé du jour)
QUE si `[health].cycle_tracking` n'est pas `"off"` (défaut) — résolu depuis la
configuration du workspace, ou forcé par `"cycle_tracking"` dans l'entrée (tests).
À `"off"`, la saisie est ignorée (`cycle.ignored = "tracking_off"`) : rien n'est
jamais écrit, et l'agent ne la mentionne pas hors de ce refus.

Retour de chaussant (#299, épopée #297) : `"shoe_feedback": {"pair": "Kipride", "comfort": "6",
"issues": [{"term": "ampoule", "zone": "sous le pied", "side": "gauche"}, {"term": "avant-pied serré"}],
"notes": "..."}` (+ `declared_gear` : [{gear_id, name}] ; à défaut, la section « Chaussures » du profil du
workspace). Le modèle extrait des TERMES ; ce module les rattache à la liste fermée du contrat
(`arc_contract.SHOE_ISSUE_KIND`), les zones à celles de `gear_inspection`, résout la paire et fusionne avec
l'éventuel `shoe_feedback` déjà écrit. Sortie `shoe_feedback` : `ready`, `gear_id`, `entry`, `merged`,
`unknown` (terme/zone/côté/confort inconnu → DEMANDER), `needs_gear` (`no_gear` | `unknown_pair` |
`ambiguous_pair` | `conflict` → DEMANDER la paire). Tout-ou-rien pour cette partie seulement : tant que
`ready` est faux, `activity_merge` ne porte pas `shoe_feedback` ; la douleur, le RPE et le ravitaillement de
la même phrase sont traités normalement. La douleur reste dans `pain` : un retour de chaussant ne la remplace
jamais et n'en est jamais présenté comme la cause.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOGUE_GLOB = "resources/nutrition/catalogue-produits-*.md"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from coach_setup import workspace_root  # noqa: E402
    import arc_index as _arc_index  # noqa: E402
    import arc_guardrails as _arc_guardrails  # noqa: E402
    import arc_cycle as _arc_cycle  # noqa: E402
except Exception:       # pragma: no cover — repli défensif, voir resolve_pain_consult_threshold
    workspace_root = None
    _arc_index = None
    _arc_guardrails = None
    _arc_cycle = None
try:
    import arc_contract as _arc_contract  # noqa: E402
    import arc_legacy as _arc_legacy  # noqa: E402
except Exception:       # pragma: no cover
    _arc_contract = None
    _arc_legacy = None
# Liste fermée des problèmes de chaussant : jamais dupliquée à la main (le contrat fait foi).
_SHOE_KINDS = tuple(_arc_contract.SHOE_ISSUE_KIND) if _arc_contract is not None else ()

# Repli si la configuration du workspace est illisible ou si l'import ci-dessus
# a échoué (environnement minimal, tests unitaires isolés) — même valeur que
# `arc_guardrails.PAIN_CONSULT_THRESHOLD`, jamais une constante dupliquée à la
# main : `tests/data/test_arc_log.py` verrouille que ce module RÉSOUT bien la
# configuration vivante plutôt que de se contenter de ce repli.
FALLBACK_PAIN_CONSULT_THRESHOLD = 7.0

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_SPACE_RE = re.compile(r"[^a-z0-9 ½]+")

# --- Nombres (quantités d'items solides : "2", "0,5", "1 et demi", "deux") ---
_WORD_NUMBERS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
    "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
}
_WORD_NUMBER_ALT = "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True))

# --- Volumes (ml/cl/dl/l, unité OBLIGATOIRE — jamais de repli "nombre nu") ---
_VOLUME_UNITS = {
    "ml": 1.0, "millilitre": 1.0, "millilitres": 1.0,
    "cl": 10.0, "centilitre": 10.0, "centilitres": 10.0,
    "dl": 100.0, "decilitre": 100.0, "decilitres": 100.0,
    "l": 1000.0, "litre": 1000.0, "litres": 1000.0,
}
_VOLUME_UNIT_ALT = "|".join(sorted(_VOLUME_UNITS, key=len, reverse=True))


class ArcLogError(ValueError):
    """Entrée malformée (JSON invalide, quantité/volume illisible, valeur négative...)."""


# ---------------------------------------------------------------------------
# Normalisation de texte
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(text: str) -> str:
    """Minuscules, sans accents, ponctuation réduite à des espaces, espaces compactés."""
    lowered = _strip_accents(text).lower()
    cleaned = _NON_ALNUM_SPACE_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _singularize_word(word: str) -> str:
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def _singular_forms(phrase: str) -> list:
    """Pluriel français simple, MOT PAR MOT, appliqué aux DEUX côtés d'une
    correspondance (la requête de l'athlète ET le nom du catalogue) : "gels
    fixture test" → aussi "gel fixture test", et un catalogue mal saisi au
    pluriel ("Barres Choco") se retrouve tout autant.

    Heuristique volontairement minimale (pas de dictionnaire) : un mot qui se
    termine par "s" et compte plus de trois lettres essaie aussi sa forme sans
    "s" — les invariants ("bras", "gaz"...) ne sont pas des produits de
    ravitaillement plausibles dans ce contexte, le risque de faux positif est
    accepté."""
    words = phrase.split(" ")
    singular_words = [_singularize_word(w) for w in words]
    forms = {phrase, " ".join(singular_words)}
    return list(forms)


def _reject_negative(text: str, what: str) -> None:
    if text.strip().startswith("-"):
        raise ArcLogError(f"{what} négatif refusé : {text!r}")


_QTY_OUT_OF_TEN_RE = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)\s*/\s*10")
# Fraction ("1 et demi", "1½") : num toujours un ENTIER nu, jamais un nombre
# déjà décimal — "1.5½" (nit, revue de code) doit être refusé, pas donner 2.0.
_QTY_FRACTION_RE = re.compile(r"(?P<num>\d+)\s*(?:(?P<half>½)|et\s+demie?)")
_QTY_PLAIN_RE = re.compile(r"\d+(?:[.,]\d+)?")


def parse_quantity(raw) -> float:
    """Quantité d'un item solide ("2 gels" → qty), un score de douleur ou un
    RPE. Ancré (`fullmatch`) : un texte qui ne correspond pas EXACTEMENT à une
    forme reconnue est refusé — jamais une extraction partielle qui
    ignorerait le reste ("3 x 40 g" ne doit jamais silencieusement devenir 3,
    la portion "40 g" contredirait peut-être le catalogue).

    Formes reconnues : nombre nu (point ou virgule décimale, SANS fraction —
    "1.5½" est refusé, jamais 2.0), "N/10" (score sur 10 : douleur "3/10",
    RPE "7/10"), entier + "½" ou "et demi(e)" (fraction, jamais combinée à un
    nombre déjà décimal), mot ("un".."dix"), mot + fraction. Négatif toujours
    refusé. Lève `ArcLogError` sinon."""
    if isinstance(raw, (int, float)):
        if raw < 0:
            raise ArcLogError(f"quantité négative refusée : {raw!r}")
        return float(raw)
    if raw is None:
        raise ArcLogError("quantité absente")
    text = str(raw).strip().lower()
    _reject_negative(text, "quantité")

    # "N/10" — score sur 10, douleur/RPE ("3/10", "7/10").
    m = _QTY_OUT_OF_TEN_RE.fullmatch(text)
    if m:
        return float(m.group("num").replace(",", "."))

    # Entier + fraction ("1 et demi", "1½").
    m = _QTY_FRACTION_RE.fullmatch(text)
    if m:
        return float(m.group("num")) + 0.5

    # "½" seul.
    if text == "½":
        return 0.5

    # Nombre nu, décimal ou entier, SANS fraction accolée.
    if _QTY_PLAIN_RE.fullmatch(text):
        return float(text.replace(",", "."))

    # Mot ("un".."dix"), éventuellement + fraction.
    m = re.fullmatch(rf"(?P<word>{_WORD_NUMBER_ALT})(?:\s*(?P<half>½)|\s+et\s+demie?)?", text)
    if m:
        value = float(_WORD_NUMBERS[m.group("word")])
        if m.group("half") or "et" in text:
            value += 0.5
        return value

    raise ArcLogError(f"quantité illisible : {raw!r}")


def parse_volume_ml(raw) -> float:
    """Volume déclaré, TOUJOURS avec une unité explicite reconnue (ml/cl/dl/l) —
    jamais de repli "nombre nu = millilitres" : un nombre sans unité, ou une
    unité non reconnue ("bidon"), doit être refusé pour que l'appelant le
    range dans `fluids.unknown` plutôt que d'inventer un volume. Ancré
    (`fullmatch`) pour la même raison qu'au-dessus.

    Formes reconnues : "N unité", "N x M unité" (N sachets/bidons de M chacun),
    "N et demi unité"/"N½ unité"/"½ unité", "un|deux unité". Unités : ml, cl,
    dl, l (et leurs formes longues). Négatif toujours refusé."""
    if isinstance(raw, (int, float)):
        raise ArcLogError(
            f"volume sans unité refusé (nombre nu {raw!r}) — préciser ml/cl/dl/l"
        )
    text = str(raw).strip().lower()
    _reject_negative(text, "volume")

    unit_alt = _VOLUME_UNIT_ALT

    # "N x M unité" — AVANT le cas simple, sinon "2 x 500 ml" matcherait
    # partiellement et perdrait le facteur "x 500".
    m = re.fullmatch(
        rf"(?P<n>\d+(?:[.,]\d+)?)\s*x\s*(?P<m>\d+(?:[.,]\d+)?)\s*(?P<unit>{unit_alt})", text
    )
    if m:
        n = float(m.group("n").replace(",", "."))
        qty = float(m.group("m").replace(",", "."))
        factor = _VOLUME_UNITS[m.group("unit")]
        return n * qty * factor

    # "N et demi unité" / "N½ unité".
    m = re.fullmatch(
        rf"(?P<num>\d+)\s*(?:(?P<half>½)|et\s+demie?)\s*(?P<unit>{unit_alt})", text
    )
    if m:
        value = float(m.group("num")) + 0.5
        return value * _VOLUME_UNITS[m.group("unit")]

    # "½ unité" seul.
    m = re.fullmatch(rf"½\s*(?P<unit>{unit_alt})", text)
    if m:
        return 0.5 * _VOLUME_UNITS[m.group("unit")]

    # "un|deux unité".
    m = re.fullmatch(rf"(?P<word>un|une|deux)\s*(?P<unit>{unit_alt})", text)
    if m:
        return float(_WORD_NUMBERS[m.group("word")]) * _VOLUME_UNITS[m.group("unit")]

    # "N unité" — cas simple, tenté en dernier (les formes ci-dessus sont
    # toutes des sur-ensembles syntaxiques qui, mal ordonnés, seraient
    # engloutis par celui-ci).
    m = re.fullmatch(rf"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>{unit_alt})", text)
    if m:
        return float(m.group("num").replace(",", ".")) * _VOLUME_UNITS[m.group("unit")]

    raise ArcLogError(f"volume illisible ou unité non reconnue (ml/cl/dl/l attendue) : {raw!r}")


# ---------------------------------------------------------------------------
# Catalogue produit
# ---------------------------------------------------------------------------

_TABLE_ROW_RE = re.compile(r"^\|(.+)\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|\s*$")
_NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _split_row(line: str) -> list:
    match = _TABLE_ROW_RE.match(line.strip())
    if not match:
        return []
    return [cell.strip() for cell in match.group(1).split("|")]


def _first_number(text: str) -> Optional[float]:
    match = _NUMBER_RE.search(text.replace(",", "."))
    return float(match.group(0)) if match else None


def parse_catalogue(text: str) -> list:
    """Extrait les lignes `{name, carbs_g}` d'un tableau Markdown "Produit | ... | Glucides".

    Insensible à la position/casse des colonnes : seules "Produit" (nom) et une
    colonne dont l'en-tête contient "glucide"/"carb" sont requises. Une ligne
    de tableau qui ne peut pas être rattachée à un nombre de glucides est
    ignorée silencieusement (catalogue partiel — ex. ligne de séparation, ou
    produit dont seule la portion est renseignée)."""
    products: list = []
    header: Optional[list] = None
    name_idx = carbs_idx = None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        if _TABLE_SEPARATOR_RE.match(line.strip()):
            continue
        cells = _split_row(line)
        if not cells:
            continue
        if header is None:
            header = [normalize_name(c) for c in cells]
            for idx, cell in enumerate(header):
                if name_idx is None and "produit" in cell:
                    name_idx = idx
                if carbs_idx is None and ("glucide" in cell or "carb" in cell):
                    carbs_idx = idx
            continue
        if name_idx is None or carbs_idx is None or len(cells) <= max(name_idx, carbs_idx):
            continue
        name = cells[name_idx].strip()
        carbs_cell = cells[carbs_idx].strip()
        if not name or not carbs_cell:
            continue
        carbs = _first_number(carbs_cell)
        if carbs is None:
            continue
        products.append({"name": name, "carbs_g": carbs})
    return products


def load_catalogue(paths) -> list:
    products: list = []
    for path in paths:
        p = Path(path)
        if not p.is_absolute():
            p = REPO_ROOT / p
        if not p.exists():
            continue
        products.extend(parse_catalogue(p.read_text(encoding="utf-8")))
    return products


def resolve_catalogue_paths(explicit) -> list:
    if explicit is not None:
        return list(explicit)
    return sorted(str(p.relative_to(REPO_ROOT)) for p in REPO_ROOT.glob(DEFAULT_CATALOGUE_GLOB))


def match_product(query: str, catalogue: list):
    """Rend `("matched", produit)`, `("ambiguous", [noms])` ou `("unknown", None)`.

    Pluriel français toléré des DEUX côtés (`_singular_forms`) : la requête de
    l'athlète ET le nom tel qu'écrit dans le catalogue."""
    if not catalogue:
        return "unknown", None
    nq_forms = set(_singular_forms(normalize_name(query)))

    def _matches(product_name: str) -> bool:
        return bool(nq_forms & set(_singular_forms(normalize_name(product_name))))

    exact = [p for p in catalogue if _matches(p["name"])]
    names = sorted({p["name"] for p in exact})
    if len(names) == 1:
        return "matched", exact[0]
    if len(names) > 1:
        return "ambiguous", names

    partial = []
    for product in catalogue:
        words = set(normalize_name(product["name"]).split())
        singular_words = {_singularize_word(w) for w in words}
        if nq_forms & (words | singular_words):
            partial.append(product)
    names = sorted({p["name"] for p in partial})
    if len(names) == 1:
        return "matched", partial[0]
    if len(names) > 1:
        return "ambiguous", names
    return "unknown", None


# ---------------------------------------------------------------------------
# Calcul principal
# ---------------------------------------------------------------------------

def compute_nutrition(items: list, catalogue: list) -> dict:
    matched, unknown, ambiguous = [], [], []
    total_carbs = 0.0
    for item in items:
        product_name = str(item.get("product", "")).strip()
        try:
            qty = parse_quantity(item.get("qty", 1))
        except ArcLogError as exc:
            unknown.append({"input": product_name, "reason": str(exc)})
            continue
        if not product_name:
            unknown.append({"input": product_name, "reason": "nom de produit vide"})
            continue

        # Valeur déclarée par l'ATHLÈTE lui-même pour un produit inconnu du
        # catalogue (ou sans catalogue) — l'agent qui a posé la question
        # ("combien de glucides dans ce produit ?") rappelle le script avec
        # cette valeur plutôt que de faire l'addition à la main (#67, revue de
        # code) : le calcul reste ici, jamais côté modèle, même pour une
        # simple multiplication.
        per_unit = item.get("carbs_g_per_unit")
        if per_unit is not None:
            try:
                per_unit_val = float(per_unit)
                if per_unit_val < 0:
                    raise ValueError
            except (TypeError, ValueError):
                unknown.append({
                    "input": product_name, "qty": qty,
                    "reason": f"carbs_g_per_unit invalide : {per_unit!r}",
                })
                continue
            carbs = round(per_unit_val * qty, 2)
            total_carbs += carbs
            matched.append({
                "input": product_name,
                "matched_product": product_name,
                "qty": qty,
                "carbs_g": carbs,
                "source": "athlete_declared",
            })
            continue

        if not catalogue:
            unknown.append({"input": product_name, "qty": qty, "reason": "no_catalogue"})
            continue
        status, result = match_product(product_name, catalogue)
        if status == "matched":
            carbs = result["carbs_g"] * qty
            total_carbs += carbs
            matched.append({
                "input": product_name,
                "matched_product": result["name"],
                "qty": qty,
                "carbs_g": round(carbs, 2),
            })
        elif status == "ambiguous":
            ambiguous.append({"input": product_name, "qty": qty, "candidates": result})
        else:
            unknown.append({"input": product_name, "qty": qty, "reason": "unknown_product"})
    return {
        "matched": matched,
        "unknown": unknown,
        "ambiguous": ambiguous,
        "carbs_g": round(total_carbs, 2) if matched else None,
    }


def compute_fluids(entries: list) -> dict:
    matched, unknown = [], []
    total = 0.0
    for entry in entries:
        try:
            ml = parse_volume_ml(entry)
        except ArcLogError as exc:
            unknown.append({"input": entry, "reason": str(exc)})
            continue
        matched.append({"input": entry, "fluid_ml": round(ml, 2)})
        total += ml
    return {
        "matched": matched,
        "unknown": unknown,
        "fluid_intake_ml": round(total, 2) if matched else None,
    }


def resolve_pain_consult_threshold(workspace: Optional[Path]) -> float:
    """Résout `[injury_risk].pain_consult_threshold` depuis la configuration
    VIVANTE du workspace (jamais une constante dupliquée à la main, #57) —
    repli sur `arc_guardrails.PAIN_CONSULT_THRESHOLD` si le module n'a pas pu
    être importé ou si la configuration est illisible pour une raison ou une
    autre (workspace minimal, tests)."""
    if _arc_index is None or _arc_guardrails is None:
        return FALLBACK_PAIN_CONSULT_THRESHOLD
    try:
        ws = workspace if workspace is not None else Path.cwd()
        config = _arc_index.load_config(ws)
        return _arc_guardrails.injury_risk_settings(config)["pain_consult_threshold"]
    except Exception:
        return FALLBACK_PAIN_CONSULT_THRESHOLD


def resolve_cycle_tracking(workspace: Optional[Path]) -> str:
    """Mode `[health].cycle_tracking` de la configuration vivante ; en cas de doute
    (import impossible, configuration illisible) → "off" : le cycle est opt-in strict."""
    if _arc_index is None or _arc_cycle is None:
        return "off"
    try:
        ws = workspace if workspace is not None else Path.cwd()
        return _arc_cycle.cycle_tracking_mode(_arc_index.load_config(ws))
    except Exception:
        return "off"


def compute_cycle(entry: dict, mode: str) -> dict:
    """Normalise une déclaration de cycle (`phase`, `day`) — jamais devinée :
    une valeur illisible va dans `unknown`, l'agent demande. À `off`, ignorée."""
    if mode == "off" or _arc_cycle is None:
        return {"ignored": "tracking_off"}
    phase = day = None
    unknown = []
    if entry.get("phase") not in (None, ""):
        phase = _arc_cycle.normalize_phase(entry.get("phase"))
        if phase is None:
            unknown.append({"field": "phase", "input": entry.get("phase")})
    if entry.get("day") not in (None, ""):
        day = _arc_cycle.normalize_day(entry.get("day"))
        if day is None:
            unknown.append({"field": "day", "input": entry.get("day")})
    return {"phase": phase, "day": day, "source": "manual", "unknown": unknown}


def compute_pain(entries: list, threshold: float) -> dict:
    valid, unknown = [], []
    for entry in entries:
        location = str(entry.get("location", "")).strip()
        raw_score = entry.get("score")
        try:
            score = parse_quantity(raw_score)
        except ArcLogError as exc:
            unknown.append({"location": location, "input": raw_score, "reason": str(exc)})
            continue
        if not (0 <= score <= 10):
            unknown.append({
                "location": location, "input": raw_score,
                "reason": f"score hors plage 0-10 : {score!r}",
            })
            continue
        valid.append({
            "location": location,
            "score": score,
            "consult": score >= threshold,
        })
    return {"entries": valid, "unknown": unknown, "consult_threshold": threshold}


def merge_activity(existing: Optional[dict], carbs_g, fluid_intake_ml, rpe) -> dict:
    """Clés à FUSIONNER dans le bloc `activity` existant — jamais le bloc entier :
    l'appelant garde `garmin_activity_id`, `distance_m` et tout le reste
    intacts. `carbs_g`/`fluid_intake_ml` s'ADDITIONNENT à une valeur déjà
    présente (un athlète peut logger deux fois pendant le même effort) ; `rpe`
    REMPLACE (un seul RPE par séance a un sens, le dernier déclaré prime)."""
    existing = existing or {}
    merged: dict = {}
    if carbs_g is not None:
        merged["carbs_g"] = round((existing.get("carbs_g") or 0) + carbs_g, 2)
    if fluid_intake_ml is not None:
        merged["fluid_intake_ml"] = round((existing.get("fluid_intake_ml") or 0) + fluid_intake_ml, 2)
    if rpe is not None:
        merged["rpe"] = rpe
    return merged


def merge_pain(existing_pain: Optional[list], new_entries: list) -> list:
    """Union simple : les entrées de douleur d'un jour s'ACCUMULENT, aucune
    n'est jamais remplacée (#57 — plusieurs zones peuvent être signalées au fil
    de la journée).

    `consult` reste dans `pain.entries` (il sert à recommander une
    consultation) mais n'est PAS recopié dans les entrées ajoutées : le contrat
    `health.pain` ne connaît que `location`/`score`, et `pain_merge` est recopié
    tel quel dans le bloc du fichier santé (#249)."""
    added = [{k: v for k, v in e.items() if k != "consult"} for e in new_entries]
    return list(existing_pain or []) + added


# ---------------------------------------------------------------------------
# Retour de chaussant (#299)
# ---------------------------------------------------------------------------
# Le modèle extrait des TERMES (« ampoule », « avant-pied serré ») ; ce module les rattache à la liste
# FERMÉE `arc_contract.SHOE_ISSUE_KIND`. Un terme absent de la table est INCONNU : on demande, on ne
# devine jamais un `kind`. Table volontairement stricte. La comparaison se fait sur des MOTS racinisés
# (sans accent, sans article ni possessif ni intensificateur, pluriel et féminin ramenés au radical) :
# « ampoules », « trop dures », « orteils très serrés » retrouvent leur forme de table.
# NÉGATION : « pas d'ampoule », « sans ampoule », « aucune ampoule », « plus d'ampoule », « pas instable »,
# « pas de souci » ne sont JAMAIS un problème : rien n'est écrit (le terme est rendu dans `negated`).
_SHOE_ISSUE_TERMS = {
    "blister": ("ampoule", "cloque"),
    "toe_box_tight": ("avant pied serre", "avant pied trop serre", "orteils serres", "orteils trop serres",
                      "orteil serre", "orteils a l etroit", "pointe serree", "boite a orteils serree",
                      "trop etroit devant", "chaussure etroite devant"),
    "heel_slip": ("talon qui bouge", "talon qui glisse", "talon flotte", "talon decolle",
                  "glissement du talon", "talon ballotte"),
    "hot_spot": ("point chaud", "points chauds", "echauffement", "frottement", "brulure"),
    "numbness": ("engourdissement", "engourdi", "pied qui s endort", "pied endormi", "fourmillements"),
    "lacing_pressure": ("pression des lacets", "lacets trop serres", "lacage trop serre", "lacage serre",
                        "dessus du pied serre", "coup de pied serre"),
    "instability": ("instable", "instabilite", "manque de stabilite", "pas stable"),
    "too_soft": ("trop mou", "trop molle", "trop moelleux", "trop souple", "spongieux", "mousse trop molle"),
    "too_firm": ("trop dur", "trop ferme", "mousse dure", "trop raide"),
    "poor_grip": ("manque d adherence", "mauvaise adherence", "adherence faible", "mauvaise accroche",
                  "manque d accroche", "patine", "glisse sur le mouille"),
    "upper_tear": ("tige dechiree", "empeigne dechiree", "dessus dechire", "tige trouee", "trou dans la tige",
                   "tige qui se dechire", "tige abimee", "empeigne abimee", "dessus abime"),
}
_SHOE_ZONE_TERMS = (   # du plus spécifique au moins spécifique ; premier motif trouvé gagne
    ("heel_posterolateral", ("talon postero lateral",)),
    ("heel_lateral", ("talon externe", "talon lateral", "bord externe du talon")),
    ("heel_medial", ("talon interne", "talon medial")),
    ("heel_central", ("talon",)),
    ("midfoot_lateral", ("medio pied externe", "milieu du pied externe", "voute externe", "medio pied lateral")),
    ("midfoot_medial", ("medio pied interne", "milieu du pied interne", "voute interne", "medio pied medial")),
    ("midfoot_central", ("medio pied", "milieu du pied", "voute", "arche")),
    ("forefoot_lateral", ("avant pied externe", "avant pied lateral", "petit orteil", "cinquieme metatarse")),
    ("forefoot_medial", ("avant pied interne", "avant pied medial", "oignon")),
    ("forefoot_central", ("avant pied",)),   # « sous le pied » seul = trop vague : on demande
    ("toe", ("gros orteil", "orteils", "orteil", "bout du pied", "pointe")),
)
_SHOE_SIDE_TERMS = (("left", ("gauche",)), ("right", ("droit", "droite")))
# Mots ignorés à la comparaison : articles, possessifs, prépositions courtes, intensificateurs.
# « trop » n'en fait PAS partie (« trop dur » != « dur »).
_SHOE_STOPWORDS = frozenset((
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "au", "aux", "mes", "mon", "ma", "ton", "ta",
    "tes", "son", "sa", "ses", "tres", "vraiment", "bien", "assez", "peu", "legerement", "tout", "ce", "cette",
))
_SHOE_NEGATIONS = frozenset(("pas", "sans", "aucun", "aucune", "jamais", "ni", "rien", "non"))
_PLUS_DE_RE = re.compile(r"\bplus (?:de|d)\b")
_CLAUSE_SPLIT_RE = re.compile(r"[,;.:/]|\bmais\b|\bet\b", re.IGNORECASE)


def _shoe_stem(word: str) -> str:
    """Radical grossier : pluriel et féminin ramenés ensemble (« serrées » == « serré »)."""
    word = _singularize_word(word)
    for _ in range(2):
        if len(word) > 3 and word.endswith("e"):
            word = word[:-1]
    return word


_SHOE_NO_ISSUE_WORDS = frozenset(_shoe_stem(w) for w in ("souci", "probleme", "ras", "signaler", "gene"))


def _shoe_tokens(text, keep_stopwords: bool = False) -> list:
    norm = _PLUS_DE_RE.sub("aucun", normalize_name(str(text or "")))
    return [_shoe_stem(w) if w not in _SHOE_NEGATIONS else w
            for w in norm.split() if keep_stopwords or w not in _SHOE_STOPWORDS]


def _find_tokens(tokens: list, phrase: str) -> Optional[int]:
    """Indice de début de `phrase` (même racinisation) comme sous-séquence contiguë de `tokens`."""
    target = _shoe_tokens(phrase)
    n = len(target)
    for i in range(len(tokens) - n + 1):
        if tokens[i:i + n] == target:
            return i
    return None


def _classify_shoe_term(term) -> dict:
    """{"kind", "zone", "side", "negated"} d'un terme libre. `kind` None = inconnu (on demande) ;
    `negated` True = l'athlète dit qu'il n'y a PAS ce problème (ne rien écrire)."""
    raw = str(term or "").strip()
    if raw in _SHOE_KINDS:                    # le modèle a déjà donné une valeur de la liste fermée
        return {"kind": raw, "zone": None, "side": None, "negated": False}
    negated_seen = False
    for clause in _CLAUSE_SPLIT_RE.split(raw):
        tokens = _shoe_tokens(clause)
        if not tokens:
            continue
        for kind, phrases in _SHOE_ISSUE_TERMS.items():
            for phrase in phrases:
                at = _find_tokens(tokens, phrase)
                if at is None:
                    continue
                if any(t in _SHOE_NEGATIONS for t in tokens[max(0, at - 3):at]):
                    negated_seen = True
                    continue
                rest = tokens[:at] + tokens[at + len(_shoe_tokens(phrase)):]
                return {"kind": kind, "zone": _zone_from_tokens(rest), "side": _side_from_tokens(rest),
                        "negated": False}
        if any(t in _SHOE_NEGATIONS for t in tokens) and (
                any(t in _SHOE_NO_ISSUE_WORDS for t in tokens) or len(tokens) <= 2):
            negated_seen = True       # « pas de souci », « rien », « aucun »
    return {"kind": None, "zone": None, "side": None, "negated": negated_seen}


def _zone_from_tokens(tokens: list) -> Optional[str]:
    for zone, phrases in _SHOE_ZONE_TERMS:
        if any(_find_tokens(tokens, p) is not None for p in phrases):
            return zone
    return None


def _side_from_tokens(tokens: list) -> Optional[str]:
    for side, phrases in _SHOE_SIDE_TERMS:
        if any(_find_tokens(tokens, p) is not None for p in phrases):
            return side
    return None


def _map_shoe_zone(text) -> tuple:
    """(zone, reconnue). Texte vide → (None, True) ; non reconnu → (None, False) : on demande."""
    raw = str(text or "").strip()
    if not raw:
        return None, True
    if _arc_contract is not None and raw in _arc_contract.GEAR_WEAR_ZONE:
        return raw, True
    zone = _zone_from_tokens(_shoe_tokens(raw))
    return zone, zone is not None


def _map_shoe_side(text) -> tuple:
    raw = str(text or "").strip()
    if not raw:
        return None, True
    if raw in ("left", "right"):
        return raw, True
    if normalize_name(raw) in ("g", "d"):
        return ("left" if normalize_name(raw) == "g" else "right"), True
    side = _side_from_tokens(_shoe_tokens(raw))
    return side, side is not None


def _declared_gear_from(payload: dict, workspace: Optional[Path]) -> list:
    """Paires connues : `declared_gear` de l'entrée ([{gear_id, name, ignored?}]) ou, à défaut, la section
    « Chaussures » du profil du workspace. Liste vide si rien n'est lisible (alors on demande la paire)."""
    given = payload.get("declared_gear")
    if isinstance(given, list):
        return [g for g in given if isinstance(g, dict) and g.get("gear_id")]
    if workspace is None or _arc_legacy is None:
        return []
    try:
        profile = Path(workspace) / "planning" / "Runner_Profile.md"
        if profile.is_file():
            return [g for g in _arc_legacy.parse_gear(profile.read_text(encoding="utf-8")) if g.get("gear_id")]
    except Exception:
        pass
    return []


def resolve_pair(text, declared: list) -> dict:
    """Rattache ce que dit l'athlète (« Kipride », « mes Pegasus ») à UNE paire du profil. Rend
    `{"gear_id": ...}` ou `{"reason": "unknown_pair" | "ambiguous_pair", "candidates": [...]}`. Jamais de
    devinette : TOUTES les paires qui correspondent sont calculées d'abord, et plusieurs = ambigu, même si
    l'une d'elles porte exactement le nom dit (« Pegasus » avec `pegasus` et `pegasus-41`)."""
    words = _shoe_tokens(text)
    pool = [g for g in declared if not g.get("ignored")]
    if not words:
        return {"reason": "no_gear", "candidates": [g["gear_id"] for g in pool]}
    hits = []
    for g in pool:
        hay = set(_shoe_tokens(f"{g.get('name') or ''} {g['gear_id']}"))
        if all(w in hay for w in words) and g["gear_id"] not in hits:
            hits.append(g["gear_id"])
    if len(hits) == 1:
        return {"gear_id": hits[0]}
    if not hits:
        return {"reason": "unknown_pair", "candidates": [g["gear_id"] for g in pool]}
    return {"reason": "ambiguous_pair", "candidates": hits}


def merge_shoe_feedback(existing: Optional[dict], entry: dict) -> dict:
    """Fusion avec un `shoe_feedback` déjà écrit sur la même séance : le confort REMPLACE (le dernier
    déclaré prime, comme `rpe`), les problèmes s'UNISSENT sans doublon exact, les notes s'accolent (une note
    déjà contenue dans l'ancienne n'est pas répétée ; jamais d'ancienne note perdue)."""
    merged = dict(existing) if isinstance(existing, dict) else {}
    if entry.get("comfort") is not None:
        merged["comfort"] = entry["comfort"]
    issues = list(merged.get("issues") or [])
    for issue in entry.get("issues") or []:
        if issue not in issues:
            issues.append(issue)
    if issues:
        merged["issues"] = issues
    new_note = entry.get("notes")
    if new_note:
        old = merged.get("notes")
        if not old or old in new_note:
            merged["notes"] = new_note
        elif new_note not in old:
            merged["notes"] = f"{old} ; {new_note}"
    return merged


def compute_shoe_feedback(entry: dict, existing_activity_arc: Optional[dict], declared: list) -> dict:
    """Normalise un retour de chaussant extrait par le modèle (#299).

    `entry` : {"pair": "Kipride", "comfort": "6", "issues": [{"term": "ampoule", "zone": "talon",
    "side": "gauche"}], "notes": "...", "pair_confirmed": false}. Tout-ou-rien : tant qu'un terme est inconnu ou
    que la paire n'est pas établie, `ready` vaut False et RIEN n'est à écrire pour la partie chaussant (le reste
    du `/log` — douleur, RPE, ravitaillement — n'est jamais bloqué). La paire de la séance (`gear_id` déjà écrit)
    prime ; une paire différente citée dans la phrase est un CONFLIT à trancher par l'athlète, jamais une
    réattribution silencieuse — `pair_confirmed: true` (l'athlète a confirmé la paire qu'il a nommée) la fait
    primer (déclaration de l'athlète > matériel Garmin). Un terme NIÉ (« pas d'ampoule ») n'est jamais écrit."""
    unknown: list = []
    negated: list = []
    out_issues: list = []
    for raw in entry.get("issues") or []:
        item = raw if isinstance(raw, dict) else {"term": raw}
        term = item.get("term", item.get("kind"))
        cls = _classify_shoe_term(term)
        if cls["negated"] and cls["kind"] is None:
            negated.append(term)
            continue
        kind = cls["kind"]
        if kind is None:
            unknown.append({"field": "issue", "input": term,
                            "reason": "terme hors de la liste fermée (ampoule, avant-pied serré, talon qui "
                                      "bouge, point chaud, engourdissement, laçage trop serré, instable, "
                                      "trop mou, trop dur, manque d'adhérence, tige déchirée)"})
            continue
        zone, zone_ok = _map_shoe_zone(item.get("zone"))
        side, side_ok = _map_shoe_side(item.get("side"))
        zone = zone or cls["zone"]        # zone / côté dits DANS le terme (« ampoule au talon gauche »)
        side = side or cls["side"]
        if not zone_ok:
            unknown.append({"field": "zone", "input": item.get("zone"), "reason": "zone non reconnue"})
        if not side_ok:
            unknown.append({"field": "side", "input": item.get("side"), "reason": "côté non reconnu"})
        if not (zone_ok and side_ok):
            continue
        issue = {"kind": kind}
        if zone:
            issue["zone"] = zone
        if side:
            issue["side"] = side
        if issue not in out_issues:
            out_issues.append(issue)
    comfort = None
    if entry.get("comfort") not in (None, ""):
        try:
            comfort = parse_quantity(entry["comfort"])
        except ArcLogError as exc:
            unknown.append({"field": "comfort", "input": entry["comfort"], "reason": str(exc)})
        else:
            if not 0 <= comfort <= 10:
                unknown.append({"field": "comfort", "input": entry["comfort"],
                                "reason": f"confort hors plage 0-10 : {comfort!r}"})
                comfort = None
    notes = str(entry.get("notes") or "").strip() or None
    built: dict = {}
    if comfort is not None:
        built["comfort"] = comfort
    if out_issues:
        built["issues"] = out_issues
    if notes:
        built["notes"] = notes

    existing = existing_activity_arc or {}
    run_gear = existing.get("gear_id")
    said = resolve_pair(entry.get("pair"), declared) if entry.get("pair") else None
    confirmed = entry.get("pair_confirmed") is True
    needs_gear = None
    gear_id = None
    gear_origin = None
    if run_gear:
        gear_id, gear_origin = run_gear, "run"
        if said and "gear_id" in said and said["gear_id"] != run_gear:
            if confirmed:
                gear_id, gear_origin = said["gear_id"], "message"
            else:
                needs_gear = {"reason": "conflict", "run_gear_id": run_gear, "said_gear_id": said["gear_id"]}
    elif said and "gear_id" in said:
        gear_id, gear_origin = said["gear_id"], "message"
    elif said:
        needs_gear = {"reason": said["reason"], "candidates": said["candidates"]}
    else:
        needs_gear = {"reason": "no_gear", "candidates": [g["gear_id"] for g in declared if not g.get("ignored")]}
    result: dict = {"gear_id": gear_id, "gear_origin": gear_origin, "entry": built, "unknown": unknown,
                    "needs_gear": needs_gear}
    if negated:
        result["negated"] = negated       # dits « pas de … » : volontairement NON écrits
    if not built and not unknown:
        result["empty"] = True
    result["ready"] = bool(built) and not unknown and needs_gear is None
    if result["ready"]:
        result["merged"] = merge_shoe_feedback(existing.get("shoe_feedback"), built)
    return result


_PROVENANCE_PREFIX_RE = re.compile(r"^\[/log [^\]]*\]\s*")


def _normalize_provenance(text: str) -> str:
    """Normalise une ligne de provenance OU une phrase brute pour comparaison.

    Une ligne déjà écrite sous le bloc porte le préfixe `[/log <horodatage>] `
    (voir `provenance_line`) que le `raw_text` brut, lui, ne porte jamais —
    sans ce retrait, `check_duplicate` ne detecte JAMAIS un doublon (bug,
    revue de code) : `existing_log_entries` vient précisément de relire ces
    lignes déjà écrites dans le fichier, préfixe compris."""
    stripped = _PROVENANCE_PREFIX_RE.sub("", text.strip())
    return _WHITESPACE_RE.sub(" ", stripped.lower())


def check_duplicate(raw_text: Optional[str], existing_log_entries) -> bool:
    if not raw_text or not existing_log_entries:
        return False
    target = _normalize_provenance(raw_text)
    return any(_normalize_provenance(str(e)) == target for e in existing_log_entries)


def provenance_line(raw_text: str, timestamp: Optional[str] = None) -> str:
    ts = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"[/log {ts}] {raw_text}"


def process(payload: dict, workspace: Optional[Path] = None) -> dict:
    catalogue_paths = resolve_catalogue_paths(payload.get("catalogue_paths"))
    catalogue = load_catalogue(catalogue_paths)

    warnings: list = []
    out: dict = {"warnings": warnings}

    raw_text = payload.get("raw_text")
    existing_log_entries = payload.get("existing_log_entries") or []
    duplicate = check_duplicate(raw_text, existing_log_entries)
    if raw_text:
        out["duplicate"] = duplicate
        out["provenance_line"] = provenance_line(raw_text, payload.get("timestamp"))

    nutrition_items = payload.get("nutrition_items") or []
    nutrition = None
    if nutrition_items:
        nutrition = compute_nutrition(nutrition_items, catalogue)
        out["nutrition"] = nutrition

    fluid_entries = payload.get("fluid_entries") or []
    fluids = None
    if fluid_entries:
        fluids = compute_fluids(fluid_entries)
        out["fluids"] = fluids

    pain_entries = payload.get("pain") or []
    pain = None
    if pain_entries:
        threshold = payload.get("pain_consult_threshold")
        if threshold is None:
            threshold = resolve_pain_consult_threshold(workspace)
        else:
            threshold = float(threshold)
        if len(pain_entries) > 10:
            warnings.append("pain : plus de 10 entrées, doublon probable (voir workspace-data-contract)")
        pain = compute_pain(pain_entries, threshold)
        out["pain"] = pain

    cycle_entry = payload.get("cycle")
    cycle = None
    if cycle_entry:
        # Forçage `cycle_tracking` de l'entrée (tests) : passé par la MÊME résolution que la
        # configuration (`arc_cycle.cycle_tracking_mode`) — une valeur invalide vaut "off", jamais
        # un suivi activé par une chaîne quelconque (revue de code #166).
        if payload.get("cycle_tracking") not in (None, ""):
            mode = (_arc_cycle.cycle_tracking_mode({"health": {"cycle_tracking": payload["cycle_tracking"]}})
                    if _arc_cycle is not None else "off")
        else:
            mode = resolve_cycle_tracking(workspace)
        cycle = compute_cycle(cycle_entry, mode)
        out["cycle"] = cycle
        if cycle.get("ignored"):
            warnings.append('cycle : [health].cycle_tracking = "off" — saisie ignorée, rien à écrire')

    rpe = None
    if "rpe" in payload and payload["rpe"] is not None:
        try:
            candidate = parse_quantity(payload["rpe"])
        except ArcLogError as exc:
            out["rpe_unknown"] = {"input": payload["rpe"], "reason": str(exc)}
            candidate = None
        else:
            if not (0 <= candidate <= 10):
                # Hors plage : jamais silencieusement accepté (#67, revue de
                # code) — la clé `rpe` n'est PAS posée, `rpe_unknown` force
                # l'agent à confirmer/reformuler plutôt qu'à écrire une valeur
                # hors contrat (0-10, voir workspace-data-contract).
                out["rpe_unknown"] = {"input": payload["rpe"], "reason": f"rpe hors plage 0-10 : {candidate!r}"}
                warnings.append(f"rpe : {candidate} hors plage 0-10, non retenu")
            else:
                rpe = candidate
                out["rpe"] = rpe

    shoe = None
    if payload.get("shoe_feedback"):
        shoe = compute_shoe_feedback(payload["shoe_feedback"], payload.get("existing_activity_arc"),
                                     _declared_gear_from(payload, workspace))
        out["shoe_feedback"] = shoe
        if shoe.get("empty"):
            warnings.append("shoe_feedback : ni confort, ni problème, ni note — rien à écrire")
        if shoe["unknown"] or shoe["needs_gear"]:
            warnings.append("shoe_feedback : partie chaussant NON écrite tant que les termes inconnus / la paire "
                            "ne sont pas clarifiés (le reste du /log n'est pas bloqué)")

    if "position" in payload and payload["position"]:
        out["position"] = str(payload["position"]).strip()

    # Fusion (#67, revue de code — idempotence) : seulement si l'appelant a
    # fourni l'état existant, et jamais pour un doublon détecté (sans quoi une
    # même déclaration relue deux fois compterait double).
    if not duplicate:
        carbs_g = nutrition["carbs_g"] if nutrition else None
        fluid_intake_ml = fluids["fluid_intake_ml"] if fluids else None
        shoe_ready = bool(shoe and shoe["ready"])
        if ("existing_activity_arc" in payload or shoe_ready) and (
                carbs_g is not None or fluid_intake_ml is not None or rpe is not None or shoe_ready):
            out["activity_merge"] = merge_activity(
                payload.get("existing_activity_arc"), carbs_g, fluid_intake_ml, rpe
            )
            if shoe_ready:
                out["activity_merge"]["shoe_feedback"] = shoe["merged"]
                if shoe["gear_origin"] == "message":
                    # La séance n'avait pas de paire : l'athlète vient de la nommer (priorité « chat »,
                    # comme `gear-attribution`) ; le contrat exige un `gear_id` pour tout `shoe_feedback`.
                    out["activity_merge"]["gear_id"] = shoe["gear_id"]
                    out["activity_merge"]["gear_source"] = "chat"
        if "existing_pain" in payload and pain and pain["entries"]:
            out["pain_merge"] = merge_pain(payload.get("existing_pain"), pain["entries"])
        if cycle and not cycle.get("ignored") and (cycle["phase"] or cycle["day"]):
            merge = {"cycle_source": "manual"}
            if cycle["phase"]:
                merge["cycle_phase"] = cycle["phase"]
            if cycle["day"]:
                merge["cycle_day"] = cycle["day"]
            out["health_merge"] = merge

    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=None, help="Fichier JSON d'entrée (défaut : stdin)")
    parser.add_argument("--output", type=Path, default=None, help="Fichier JSON de sortie (défaut : stdout)")
    parser.add_argument("--workspace", default=None, help="Racine du workspace (défaut : résolution standard)")
    args = parser.parse_args(argv)

    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERREUR : JSON d'entrée invalide — {exc}", file=sys.stderr)
        return 1

    workspace = None
    if args.workspace:
        workspace = Path(args.workspace).expanduser().resolve()
    elif workspace_root is not None:
        try:
            workspace = workspace_root(None)
        except Exception:
            workspace = None

    try:
        result = process(payload, workspace=workspace)
    except ArcLogError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        return 1

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
