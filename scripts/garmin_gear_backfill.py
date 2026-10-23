#!/usr/bin/env python3
"""Rattrapage du matériel Garmin sur l'historique des séances (#145, épopée #131).

#133 attribue la chaussure Garmin aux séances NOUVELLES (`get_activity_gear` à la
synchronisation). Les séances déjà dans le workspace n'ont pas de `gear_id` : la carte
« Matériel » est vide alors que Garmin Connect connaît la paire de chaque séance. Ce
script les rattrape en UN appel Garmin par paire de chaussures (`get_gear_activities`),
jamais un par séance.

    python3 scripts/garmin_gear_backfill.py --workspace <dossier>            # simulation (défaut)
    python3 scripts/garmin_gear_backfill.py --workspace <dossier> --apply    # écrit

Simulation par défaut : rien n'est écrit sans `--apply`. Le rapport donne, par paire, la puce
`### Chaussures` proposée, le nombre de séances rattachées, les km du workspace vs le total
Garmin ; puis les conflits, les séances ambiguës, les séances Garmin absentes du workspace et
les fichiers sans `garmin_activity_id`.

Options : `--since AAAA-MM-JJ` (séances du workspace à partir de cette date seulement),
`--gear UUID` (une seule paire Garmin), `--all-shoes` (propose aussi les paires sans séance
dans la période du workspace, en `(retirée)` quand Garmin les a retirées), `--json` (sortie
machine), `--workspace`, `--tokens-dir`.

CODES DE SORTIE : 0 = succès (simulation ou application complète) ; 1 = succès partiel
(paire injoignable côté Garmin, fichier rejeté par la validation et restauré) ; 2 = usage,
dépendance `garminconnect` absente, authentification Garmin impossible ou `get_gear` illisible ; 3 = `--apply`
impossible faute de profil athlète (`planning/Runner_Profile.md`).

EXCEPTION À « stdlib seule » (documentée, comme `skills/fit-download/scripts/download_fit.py`) :
la seule dépendance non standard est `garminconnect`, importée PARESSEUSEMENT dans
`connect_garmin()` — tout le reste du module (planification pure) s'importe et se teste avec la
bibliothèque standard. Comme `download_fit.py`, le script se relance avec l'interpréteur de
`garmin-mcp` (`~/.local/share/uv/tools/garmin-mcp/bin/python3`, ou `GARMIN_PYTHON`) quand
`garminconnect` manque, et lit les mêmes jetons (`~/.garminconnect`, ou `GARMINTOKENS` de
`.mcp.json` — même résolution que `coach_doctor.py`).

RÈGLES (voir docs/garmin-setup.md) :
  - Seul `gearTypeName == "Shoes"`. Jamais `(par défaut)` posé automatiquement.
  - Priorité #133 : une séance qui porte déjà un `gear_id` (athlète ou chat, ou Garmin d'une
    synchronisation antérieure) n'est JAMAIS écrasée ; la divergence est listée. Seul un
    `gear_source: "garmin_unmapped"` (sans `gear_id`) est remplacé.
  - Une séance présente dans deux paires côté Garmin est ambiguë : jamais attribuée, listée.
  - Puce existante avec le même `garmin: <uuid>` : son `gear_id` est réutilisé ; seul ajout possible,
    ` (retirée AAAA-MM-JJ)` quand Garmin a retiré la paire depuis (date de fin Garmin). `--apply`
    rafraîchit aussi l'instantané `.arc/garmin_gear.json` (`arc_garmin_gear`). Puce `(ignorée)` : la
    paire n'est jamais attribuée.
  - `départ N km` d'une puce NOUVELLE = km Garmin de la paire pour les séances Garmin ABSENTES du
    workspace (identifiées par `activityId`, jamais par un total soustrait) : celles du workspace
    sont déjà comptées par leurs fichiers, elles ne peuvent donc pas l'être deux fois. Non calculé
    (avec la raison au rapport) avec `--since` ou si la liste Garmin est tronquée ou en erreur. Seules
    comptent les séances Garmin datées STRICTEMENT AVANT le premier fichier du workspace : les absentes
    dans la période (trous) ou postérieures (la synchronisation les importera) sont listées à part.
  - TOUTES les paires sont lues, même avec `--gear` (ambiguïté). Paire en erreur ou tronquée : `--apply`
    refusé (code 1, rien d'écrit). Fichiers en double pour un même `garmin_activity_id`, `gear_source` sans
    `gear_id` : signalés, jamais écrits. Fichier déjà hors contrat : signalé à part, jamais réécrit.
  - Puce existante sans `garmin:` de même nom/id : pas de doublon, `--apply` n'y ajoute QUE ` — garmin: <uuid>`.
  - Écritures en octets (CRLF et permissions conservés) ; `ARC_GEAR_BACKFILL_RELAUNCHED` évite toute
    boucle de relance entre interpréteurs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_contract as C  # noqa: E402
import arc_legacy as L  # noqa: E402

GEAR_ACTIVITIES_PAGE = 1000            # plafond `MAX_ACTIVITY_LIMIT` de garminconnect
GEAR_ACTIVITIES_MAX_PAGES = 50         # garde-fou contre une pagination sans fin
EXIT_OK, EXIT_PARTIAL, EXIT_USAGE, EXIT_NO_PROFILE = 0, 1, 2, 3
DEFAULT_PROFILE_REL = "planning/Runner_Profile.md"
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_KEYWORDS = r"depuis|alerte|d[ée]part|usage\s*:|id\s*:|garmin\s*:"


# ---------------------------------------------------------------------------
# Inventaire Garmin (pur)
# ---------------------------------------------------------------------------

def _clean(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def normalize_shoes(raw_gear: List[dict]) -> List[dict]:
    """`get_gear` → chaussures seulement (`gearTypeName == "Shoes"`), champs normalisés.

    Nom : `displayName`, puis `customMakeModel`, puis « Chaussure Garmin <uuid[:8]> »
    (`displayName` peut être `None` chez Garmin)."""
    shoes = []
    for g in raw_gear or []:
        if not isinstance(g, dict) or str(g.get("gearTypeName") or "").strip().lower() != "shoes":
            continue
        uuid = _clean(g.get("uuid"))
        if not uuid:
            continue
        uuid = uuid.lower()
        begin = _DATE_PREFIX_RE.match(str(g.get("dateBegin") or ""))
        end = _DATE_PREFIX_RE.match(str(g.get("dateEnd") or ""))
        try:
            max_m = float(g.get("maximumMeters") or 0)
        except (TypeError, ValueError):
            max_m = 0.0
        shoes.append({
            "uuid": uuid,
            "name": _clean(g.get("displayName")) or _clean(g.get("customMakeModel")) or f"Chaussure Garmin {uuid[:8]}",
            "retired": str(g.get("gearStatusName") or "").strip().lower() == "retired",
            "date_begin": begin.group(1) if begin else None,
            "date_end": end.group(1) if end else None,
            "max_m": max_m if max_m > 0 else 0.0,
        })
    return shoes


def normalize_gear_activities(raw: Optional[List[dict]]) -> List[dict]:
    """`get_gear_activities` → `[{id, date, distance_m}]` (ids entiers, sans doublon)."""
    out, seen = [], set()
    for a in raw or []:
        try:
            aid = int(a.get("activityId"))
        except (AttributeError, TypeError, ValueError):
            continue
        if aid in seen:
            continue
        seen.add(aid)
        day = _DATE_PREFIX_RE.match(str(a.get("startTimeLocal") or a.get("startTimeGMT") or ""))
        try:
            dist = float(a.get("distance") or 0)
        except (TypeError, ValueError):
            dist = 0.0
        out.append({"id": aid, "date": day.group(1) if day else None, "distance_m": max(dist, 0.0)})
    return out


# ---------------------------------------------------------------------------
# Puces `### Chaussures` (pur)
# ---------------------------------------------------------------------------

def _try_parse(bullet: str) -> Optional[dict]:
    parsed = L.parse_gear("### Chaussures\n\n" + bullet + "\n")
    return parsed[0] if len(parsed) == 1 else None


def safe_bullet_name(name: str, uuid: str) -> str:
    """Nom compatible avec l'analyseur de puces : tirets cadratins, marqueurs `(retirée)`… et
    « : mot-clé » retirés ; repli progressif jusqu'à « Chaussure Garmin <uuid[:8]> »."""
    fallback = f"Chaussure Garmin {uuid[:8]}"
    text = re.sub(r"\s+", " ", str(name or "").replace("**", " ")).strip()
    text = re.sub(r"[—–]", "-", text)
    text = re.sub(r"\(\s*(?:par\s*d[ée]faut|retir[ée]e?|ignor[ée]e?)\s*\)", " ", text, flags=re.I)
    text = re.sub(rf"\s+-\s+(?=(?:{_KEYWORDS}))", " ", text, flags=re.I)
    text = re.sub(rf"\s*:\s*(?=(?:{_KEYWORDS}))", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    for candidate in (text, re.sub(r"\s+", " ", re.sub(r"[^\w /.,+'-]", " ", text)).strip()):
        parsed = _try_parse(f"- {candidate}") if candidate else None
        if parsed and parsed.get("name") == candidate:
            return candidate
    return fallback


def unique_gear_id(name: str, uuid: str, used: set) -> str:
    """Slug `arc_contract.gear_slug(name)` (repli sur l'uuid), suffixé `-2`, `-3`… s'il est déjà pris
    (profil, matériel `### Matériel`, puces proposées dans ce même passage)."""
    base = C.gear_slug(name) or C.gear_slug(f"chaussure garmin {uuid[:8]}") or "chaussure-garmin"
    candidate, n = base, 1
    while candidate in used:
        n += 1
        suffix = f"-{n}"
        candidate = base[: C.GEAR_ID_MAX_LEN - len(suffix)].rstrip("-") + suffix
    used.add(candidate)
    return candidate


def build_bullet(shoe: dict, gear_id: str, depart_km: Optional[int]) -> str:
    """`- <nom> — depuis <date> — alerte N km — départ N km — id: <slug> — garmin: <uuid> (retirée)`.
    Toujours relue par `arc_legacy.parse_gear` : un écart (id, uuid, nom) lève une erreur plutôt
    qu'une puce silencieusement fausse."""
    name = safe_bullet_name(shoe["name"], shoe["uuid"])
    parts = [name]
    if shoe.get("date_begin"):
        parts.append(f"depuis {shoe['date_begin']}")
    if shoe.get("max_m"):
        parts.append(f"alerte {round(shoe['max_m'] / 1000):d} km")
    if depart_km:
        parts.append(f"départ {int(depart_km)} km")
    parts.append(f"id: {gear_id}")
    parts.append(f"garmin: {shoe['uuid']}")
    bullet = "- " + " — ".join(parts) + (" (retirée)" if shoe.get("retired") else "")
    parsed = _try_parse(bullet)
    if not parsed or parsed.get("gear_id") != gear_id or parsed.get("garmin_uuid") != shoe["uuid"] \
            or parsed.get("name") != name:
        raise ValueError(f"puce non relue à l'identique par parse_gear : {bullet!r}")
    return bullet


# ---------------------------------------------------------------------------
# Planification (pure : aucune E/S)
# ---------------------------------------------------------------------------

def _km(meters: float) -> float:
    return round(meters / 1000.0, 1)


def _bucket(day: Optional[str], ws_min: Optional[str], ws_max: Optional[str]) -> str:
    """Position d'une séance Garmin ABSENTE du workspace par rapport à sa période : `before` (strictement
    avant le premier fichier), `in_period` (trou du workspace), `after` (postérieure au dernier fichier —
    la synchronisation l'importera), `undated`."""
    if not day:
        return "undated"
    if ws_min is None or day < ws_min:
        return "before"
    return "in_period" if day <= ws_max else "after"


def plan(shoes: List[dict], gear_acts: Dict[str, dict], ws_files: List[dict], profile_gear: List[dict],
         *, since: Optional[str] = None, only_gear: Optional[str] = None, all_shoes: bool = False,
         extra_used_ids=(), garmin_defaults=()) -> dict:
    """Plan de rattrapage — entrées :

    - `shoes` : `normalize_shoes` (TOUTES les paires : l'ambiguïté se détecte sur l'ensemble, `only_gear`
      ne restreint que ce qui est proposé/écrit) ; `gear_acts` : `{uuid: {"activities":
      normalize_gear_activities, "error": str|None, "truncated": bool}}` ;
    - `ws_files` : une entrée par `activities/*.md` : `{path, date, garmin_activity_id, distance_m,
      gear_id, gear_source, has_block}` ;
    - `profile_gear` : `arc_legacy.parse_gear` (puces existantes, `(ignorée)` comprises).

    `incomplete` liste les paires dont la liste Garmin est en erreur ou tronquée : l'ambiguïté n'est alors pas
    garantie et `--apply` est refusé par l'appelant.
    """
    only = (only_gear or "").strip().lower() or None
    selected = [s for s in shoes if only is None or s["uuid"] == only]
    by_ws_id: Dict[int, List[dict]] = {}
    for f in ws_files:
        if f.get("garmin_activity_id") is not None:
            by_ws_id.setdefault(f["garmin_activity_id"], []).append(f)
    no_id_files = [f for f in ws_files if f.get("garmin_activity_id") is None]
    dated = [f["date"] for f in ws_files if f.get("date")]
    ws_min, ws_max = (min(dated), max(dated)) if dated else (None, None)
    lo = max(ws_min, since) if (ws_min and since) else (since or ws_min)

    profile_by_uuid: Dict[str, List[dict]] = {}
    for g in profile_gear:
        if g.get("garmin_uuid"):
            profile_by_uuid.setdefault(g["garmin_uuid"], []).append(g)
    ws_gear_ids = {f["gear_id"] for f in ws_files if f.get("gear_id")}
    profile_ids = {g["gear_id"] for g in profile_gear}
    used_ids = profile_ids | set(extra_used_ids) | ws_gear_ids
    unlinked_bullets = [g for g in profile_gear if not g.get("garmin_uuid") and not g.get("garmin_uuid_invalid")
                        and not g.get("ignored")]
    claimed_bullets: set = set()

    # activité Garmin → paires qui la revendiquent (TOUTES les paires interrogées)
    claimed: Dict[int, List[str]] = {}
    incomplete = []
    for s in shoes:
        info = gear_acts.get(s["uuid"], {})
        if info.get("error"):
            incomplete.append({"uuid": s["uuid"], "name": s["name"], "reason": "erreur : " + str(info["error"])})
        elif info.get("truncated"):
            incomplete.append({"uuid": s["uuid"], "name": s["name"], "reason": "liste tronquée"})
        for a in info.get("activities", []):
            claimed.setdefault(a["id"], []).append(s["uuid"])
    ambiguous_ids = {aid for aid, us in claimed.items() if len(us) > 1}
    selected_uuids = {s["uuid"] for s in selected}

    result: Dict[str, Any] = {
        "since": since, "gear_filter": only, "all_shoes": all_shoes,
        "workspace_period": [ws_min, ws_max],
        "shoes": [], "assignments": [], "new_bullets": [], "links": [], "retirements": [], "conflicts": [], "ambiguous": [],
        "duplicate_ids": [], "inconsistent": [], "incomplete": incomplete,
        "missing_from_workspace": [], "workspace_without_id": [f["path"] for f in no_id_files],
        "workspace_files": len(ws_files), "workspace_with_id": sum(len(v) for v in by_ws_id.values()),
        "garmin_defaults": list(garmin_defaults), "skipped_out_of_period": [],
    }
    dup_seen: Dict[int, dict] = {}
    ordered = sorted(selected, key=lambda s: (s["date_begin"] or "9999", s["name"].lower(), s["uuid"]))
    for shoe in ordered:
        info = gear_acts.get(shoe["uuid"], {})
        acts = info.get("activities", [])
        entry: Dict[str, Any] = {
            "uuid": shoe["uuid"], "name": shoe["name"], "retired": shoe["retired"],
            "garmin_sessions": len(acts), "garmin_km": _km(sum(a["distance_m"] for a in acts)),
            "error": info.get("error"), "truncated": bool(info.get("truncated")),
            "matched": 0, "workspace_km": 0.0, "to_write": 0, "already": 0, "conflicts": 0,
            "ambiguous": 0, "before_since": 0, "duplicates": 0, "inconsistent": 0,
            "missing_from_workspace": 0, "missing_before": 0, "missing_in_period": 0, "missing_after": 0,
            "missing_undated": 0, "name_matches": [],
            "status": None, "gear_id": None, "bullet": None, "depart_km": None, "depart_note": None,
        }
        result["shoes"].append(entry)
        if info.get("error"):
            entry["status"] = "error"
            continue
        in_period = [a for a in acts if a["date"] and lo and ws_max and lo <= a["date"] <= ws_max]
        if not in_period:
            entry["status"] = "out_of_period"
            result["skipped_out_of_period"].append(shoe["uuid"])
            if not all_shoes:
                continue
        existing = profile_by_uuid.get(shoe["uuid"], [])
        base_slug = C.gear_slug(shoe["name"])
        if len(existing) > 1:
            entry["status"] = "duplicate_in_profile"
            entry["depart_note"] = "uuid présent sur plusieurs puces du profil : rien n'est attribué"
            continue
        if existing and existing[0].get("ignored"):
            entry["status"] = "ignored"
            entry["gear_id"] = existing[0]["gear_id"]
            continue
        linking = None
        if existing:
            entry["status"] = "existing"
            entry["gear_id"] = existing[0]["gear_id"]
            if shoe["retired"] and not existing[0].get("retired"):
                # Retraite décidée dans Garmin APRÈS la création de la puce : seul ajout proposé, « (retirée …) ».
                result["retirements"].append({"uuid": shoe["uuid"], "gear_id": existing[0]["gear_id"],
                                              "name": existing[0].get("name") or shoe["name"],
                                              "date_end": shoe.get("date_end")})
        else:
            cands = [g for g in unlinked_bullets if base_slug and (C.gear_slug(g.get("name") or "") == base_slug
                                                                    or g["gear_id"] == base_slug)]
            if cands:
                if len(cands) > 1 or cands[0]["gear_id"] in claimed_bullets:
                    entry["status"] = "name_ambiguous"
                    entry["depart_note"] = ("plusieurs puces du profil sans garmin: portent ce nom : rien n'est "
                                            "attribué, ajoutez le segment garmin: à la bonne puce")
                    continue
                linking = cands[0]
                claimed_bullets.add(linking["gear_id"])
                entry["status"] = "link_existing"
                entry["gear_id"] = linking["gear_id"]
                result["links"].append({"uuid": shoe["uuid"], "gear_id": linking["gear_id"],
                                        "name": linking.get("name") or linking["gear_id"]})
            else:
                if entry["status"] != "out_of_period":
                    entry["status"] = "new"
                entry["name_matches"] = sorted(
                    i for i in ws_gear_ids - profile_ids
                    if base_slug and (i == base_slug or base_slug.startswith(i + "-")))
                entry["gear_id"] = unique_gear_id(shoe["name"], shoe["uuid"], used_ids)
        gear_id = entry["gear_id"]

        # --- séances du workspace ---
        missing = []
        for a in acts:
            fs = by_ws_id.get(a["id"])
            if fs is None:
                if a["id"] in ambiguous_ids:
                    continue   # signalée plus bas, jamais comptée dans `départ` (deux paires la revendiquent)
                missing.append(a)
                continue
            if len(fs) > 1:    # plusieurs fichiers pour la même séance : jamais écrits, à trier à la main
                entry["duplicates"] += 1
                rec = dup_seen.setdefault(a["id"], {"id": a["id"], "paths": [f["path"] for f in fs], "shoes": []})
                rec["shoes"].append(shoe["uuid"])
                continue
            f = fs[0]
            entry["matched"] += 1
            entry["workspace_km"] += (f.get("distance_m") or 0.0)
            if a["id"] in ambiguous_ids:
                entry["ambiguous"] += 1
                continue
            if since and f.get("date") and f["date"] < since:
                entry["before_since"] += 1
                continue
            current, source = f.get("gear_id"), f.get("gear_source")
            if not current:
                if source in ("garmin", "chat"):
                    entry["inconsistent"] += 1     # source sans gear_id : fichier incohérent, jamais réécrit
                    result["inconsistent"].append({"path": f["path"], "gear_source": source})
                    continue
                entry["to_write"] += 1
                result["assignments"].append({
                    "path": f["path"], "date": f.get("date"), "gear_id": gear_id, "gear_uuid": shoe["uuid"],
                    "replaces_unmapped": source == "garmin_unmapped"})
            elif current == gear_id:
                entry["already"] += 1
            else:
                entry["conflicts"] += 1
                result["conflicts"].append({
                    "path": f["path"], "date": f.get("date"), "kept": current, "kept_source": source or "?",
                    "garmin": gear_id, "garmin_name": shoe["name"]})
        entry["workspace_km"] = _km(entry["workspace_km"])
        entry["missing_from_workspace"] = len(missing)
        buckets: Dict[str, List[dict]] = {"before": [], "in_period": [], "after": [], "undated": []}
        for a in missing:
            b = _bucket(a["date"], ws_min, ws_max)
            buckets[b].append(a)
            result["missing_from_workspace"].append({"id": a["id"], "date": a["date"], "uuid": shoe["uuid"],
                                                     "distance_km": _km(a["distance_m"]), "bucket": b})
        for b, items in buckets.items():
            entry[f"missing_{b}"] = len(items)

        # --- départ (puce nouvelle seulement) ---
        if entry["status"] in ("new", "out_of_period") and not existing and linking is None:
            entry["depart_km"], entry["depart_note"] = _depart(shoe, acts, buckets, entry, ws_min, since, info)
            entry["bullet"] = build_bullet(shoe, gear_id, entry["depart_km"])
            result["new_bullets"].append({"uuid": shoe["uuid"], "gear_id": gear_id, "bullet": entry["bullet"],
                                          "date_begin": shoe["date_begin"]})
    result["duplicate_ids"] = sorted(dup_seen.values(), key=lambda r: r["id"])
    for aid in sorted(ambiguous_ids):
        if not (set(claimed[aid]) & selected_uuids):
            continue
        fs = by_ws_id.get(aid) or []
        result["ambiguous"].append({"id": aid, "date": fs[0].get("date") if fs else None,
                                    "path": fs[0]["path"] if fs else None,
                                    "in_workspace": bool(fs), "shoes": sorted(claimed[aid])})
    return result


def _depart(shoe, acts, buckets, entry, ws_min, since, info) -> Tuple[Optional[int], str]:
    """`(km | None, explication)` : km Garmin des séances de la paire datées STRICTEMENT AVANT le premier fichier
    du workspace. Les séances absentes mais dans la période (trous) ou postérieures (la synchronisation les
    importera : les compter ici les doublerait) ne sont jamais comptées ; elles sont listées au rapport."""
    if since:
        return None, ("non calculé avec --since : des séances du workspace antérieures à la date seraient "
                      "comptées deux fois (relancer sans --since pour proposer un départ)")
    if info.get("truncated"):
        return None, "non calculé : liste Garmin tronquée (plafond de l'API), total incertain"
    if not acts:
        return None, "aucune séance côté Garmin"
    before = buckets["before"]
    km = round(sum(a["distance_m"] for a in before) / 1000.0)
    total = round(sum(a["distance_m"] for a in acts) / 1000.0)
    excluded = []
    for key, label in (("in_period", "dans la période du workspace (trous, à importer par la synchronisation)"),
                       ("after", "postérieure(s) au dernier fichier (la synchronisation les importera)"),
                       ("undated", "sans date")):
        if buckets[key]:
            excluded.append(f"{len(buckets[key])} {label}")
    tail = f" ; non comptée(s) : {' ; '.join(excluded)}" if excluded else ""
    if km < 1:
        return None, "aucun kilométrage antérieur au premier fichier du workspace" + tail
    return km, (f"{km} km = {len(before)} séance(s) Garmin de la paire antérieures au premier fichier du workspace "
                f"({ws_min or '?'}) ; les séances déjà dans le workspace ({entry['matched']}) ne sont pas recomptées "
                f"(total Garmin {total} km){tail}")


# ---------------------------------------------------------------------------
# Profil : insertion des puces (pur)
# ---------------------------------------------------------------------------

def _mask_comments(text: str) -> str:
    """Remplace les commentaires HTML par des espaces (mêmes offsets, sauts de ligne conservés)."""
    return re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


# Mêmes titres que `arc_legacy` (`_GEAR_HEADING_RE`, `\s*$`) : le `\r` d'un fichier CRLF est toléré en fin de
# ligne (`[ \t\r]*$` plutôt que `\s*$`, qui avalerait aussi les lignes vides suivantes et décalerait les offsets).
_H_CHAUSSURES = re.compile(r"^[ ]{0,3}#{2,4}[ \t]*chaussures[ \t\r]*$", re.I | re.M)
_H_MATERIEL_SECTION = re.compile(r"^[ ]{0,3}##[ \t]+mat[ée]riel\b[^\n]*$", re.I | re.M)
_H_ANY = re.compile(r"^[ ]{0,3}#{1,6}[ \t]", re.M)
_H_LEVEL1_2 = re.compile(r"^[ ]{0,3}#{1,2}[ \t]", re.M)
_H_EQUIPMENT_SUB = re.compile(r"^[ ]{0,3}#{3,4}[ \t]*mat[ée]riel[ \t\r]*$", re.I | re.M)


def _with_lf(fn):
    """Applique `fn(text, …)` sur une vue LF d'un fichier CRLF UNIFORME, puis rétablit les CRLF : le fichier
    garde ses fins de ligne. Un fichier mixte est traité tel quel (lignes ajoutées en LF)."""
    def wrapper(text, *args, **kwargs):
        uniform = "\r\n" in text and "\n" not in text.replace("\r\n", "")
        if not uniform:
            return fn(text, *args, **kwargs)
        out = fn(text.replace("\r\n", "\n"), *args, **kwargs)
        return out if out is None else out.replace("\n", "\r\n")
    return wrapper


@_with_lf
def insert_gear_bullets(text: str, bullets: List[str]) -> str:
    """Ajoute `bullets` sous `### Chaussures` sans toucher aux lignes existantes. Sous-section absente :
    créée dans `## Matériel & lieux` (avant `### Matériel` s'il existe, sinon en fin de section) ; section
    `## Matériel & lieux` absente : créée en fin de fichier. Fins de ligne CRLF conservées."""
    if not bullets:
        return text
    if not text.endswith("\n"):
        text += "\n"
    masked = _mask_comments(text)
    block = "\n".join(bullets) + "\n"
    m = _H_CHAUSSURES.search(masked)
    if m:
        after = m.end() + 1
        nxt = _H_ANY.search(masked, after)
        end = nxt.start() if nxt else len(text)
        lines = text[after:end].splitlines(keepends=True)
        last_bullet_end = None
        cursor = after
        for ln in lines:
            cursor += len(ln)
            if re.match(r"^\s*[-*]\s+\S", masked[cursor - len(ln):cursor]):
                last_bullet_end = cursor
        if last_bullet_end is not None:
            return text[:last_bullet_end] + block + text[last_bullet_end:]
        # aucune puce : juste sous le titre (sous d'éventuelles consignes commentées)
        return _splice_after_heading(text, after, end, block)
    sub = "### Chaussures\n\n" + block
    sec = _H_MATERIEL_SECTION.search(masked)
    if sec:
        start = sec.end() + 1
        nxt = _H_LEVEL1_2.search(masked, start)
        end = nxt.start() if nxt else len(text)
        eq = _H_EQUIPMENT_SUB.search(masked, start, end)
        if eq:
            pre = text[:eq.start()]
            if pre and not pre.endswith("\n\n"):
                pre += "\n"
            return pre + sub + "\n" + text[eq.start():]
        body = text[start:end].rstrip("\n")
        insert_at = start + len(body) + (1 if body else 0)
        lead = "\n" if body else ""
        rest = text[insert_at:]
        return text[:insert_at] + lead + sub + ("\n" if rest and not rest.startswith("\n") else "") + rest
    sep = "" if text.endswith("\n\n") else "\n"
    return text + sep + "## Matériel & lieux\n\n" + sub


def _splice_after_heading(text: str, after: int, end: int, block: str) -> str:
    body = text[after:end]
    stripped = body.rstrip("\n")
    tail = body[len(stripped):]              # lignes vides finales, conservées avant le titre suivant
    lead = "" if stripped else "\n"
    joined = stripped + ("\n" if stripped else "") + lead + block
    return text[:after] + joined + (tail if tail else ("\n" if end < len(text) else "")) + text[end:]


@_with_lf
def append_garmin_segment(text: str, gear_id: str, uuid: str) -> Optional[str]:
    """Ajoute le SEUL segment ` — garmin: <uuid>` à la puce `### Chaussures` qui porte `gear_id` et n'a pas encore
    de segment `garmin:` (jamais rien d'autre sur une puce existante). `None` si la puce n'est pas trouvée
    exactement une fois (lue seule, sans suffixe de collision) — l'appelant le signale sans rien écrire."""
    masked = _mask_comments(text)
    m = _H_CHAUSSURES.search(masked)
    if not m:
        return None
    after = m.end() + 1
    nxt = _H_ANY.search(masked, after)
    end = nxt.start() if nxt else len(text)
    hits, cursor = [], after
    for ln in text[after:end].splitlines(keepends=True):
        line_start, cursor = cursor, cursor + len(ln)
        top = L._GEAR_TOP_BULLET_RE.match(masked[line_start:cursor].rstrip("\r\n"))
        if not top:
            continue
        parsed = _try_parse("- " + top.group(1))
        if parsed and parsed.get("gear_id") == gear_id and not parsed.get("garmin_uuid") \
                and not parsed.get("garmin_uuid_invalid"):
            hits.append(cursor - len(ln) + len(ln.rstrip("\r\n")))
    if len(hits) != 1:
        return None
    return text[:hits[0]] + f" — garmin: {uuid}" + text[hits[0]:]


@_with_lf
def append_retired_marker(text: str, gear_id: str, retired_date: Optional[str] = None) -> Optional[str]:
    """Ajoute ` (retirée AAAA-MM-JJ)` (ou ` (retirée)` sans date) en fin de la puce `### Chaussures` qui porte
    `gear_id` et n'est pas déjà retirée — rien d'autre n'est touché. `None` si la puce n'est pas trouvée
    exactement une fois (l'appelant le signale sans rien écrire)."""
    masked = _mask_comments(text)
    m = _H_CHAUSSURES.search(masked)
    if not m:
        return None
    after = m.end() + 1
    nxt = _H_ANY.search(masked, after)
    end = nxt.start() if nxt else len(text)
    hits, cursor = [], after
    for ln in text[after:end].splitlines(keepends=True):
        line_start, cursor = cursor, cursor + len(ln)
        top = L._GEAR_TOP_BULLET_RE.match(masked[line_start:cursor].rstrip("\r\n"))
        if not top:
            continue
        parsed = _try_parse("- " + top.group(1))
        if parsed and parsed.get("gear_id") == gear_id and not parsed.get("retired"):
            hits.append(line_start + len(ln.rstrip("\r\n").rstrip()))
    if len(hits) != 1:
        return None
    marker = f" (retirée {retired_date})" if retired_date else " (retirée)"
    return text[:hits[0]] + marker + text[hits[0]:]


# ---------------------------------------------------------------------------
# Bloc `arc` d'une activité : écriture textuelle minimale (pur)
# ---------------------------------------------------------------------------

def set_block_keys(text: str, updates: Dict[str, Any]) -> str:
    """Ajoute/remplace des clés de premier niveau du bloc ```arc SANS reformater le reste : une clé déjà présente
    (ex. `gear_source: "garmin_unmapped"`) voit SEULE sa valeur remplacée sur place ; les clés absentes sont
    insérées avant l'accolade finale (ordre et mise en forme conservés, ligne unique ou multi-lignes)."""
    m = C.BLOCK_RE.search(text)
    if not m:
        raise C.ContractError("bloc ```arc absent")
    body = m.group(1)
    data = json.loads(body)
    expected = dict(data)
    expected.update(updates)
    new_body = body
    for key, value in updates.items():
        if key not in data:
            continue
        pattern = re.compile(r'("%s"\s*:\s*)%s' % (re.escape(key), re.escape(json.dumps(data[key], ensure_ascii=False))))
        new_body, n = pattern.subn(lambda mm, v=value: mm.group(1) + json.dumps(v, ensure_ascii=False), new_body, count=1)
        if n == 0:
            raise C.ContractError(f"valeur de « {key} » introuvable telle quelle dans le bloc ```arc")
    added = {k: v for k, v in updates.items() if k not in data}
    if added:
        close = new_body.rstrip().rfind("}")
        before = new_body[:close].rstrip()
        items = [f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in added.items()]
        if "\n" in body:
            last_line = before.rsplit("\n", 1)[-1]
            indent = re.match(r"[ \t]*", last_line).group(0) or "  "
            new_body = before + ",\n" + ",\n".join(indent + it for it in items) + "\n" + new_body[close:].rstrip()
        else:
            new_body = before + ", " + ", ".join(items) + "}"
    if json.loads(new_body) != expected:
        raise C.ContractError("réécriture du bloc ```arc non conforme à l'attendu")
    return text[:m.start(1)] + new_body + text[m.end(1):]


# ---------------------------------------------------------------------------
# Workspace (E/S locales)
# ---------------------------------------------------------------------------

def scan_workspace(workspace: Path) -> List[dict]:
    """Une entrée par `activities/*.md` (niveau supérieur seulement) portant un bloc `activity`. Lecture en
    octets : un fichier CRLF n'a pas de bloc lisible par le contrat (comme pour l'index), il est compté « sans
    identifiant »."""
    out = []
    folder = workspace / "activities"
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        rel = f"activities/{path.name}"
        entry = {"path": rel, "date": L.filename_date(path.name), "garmin_activity_id": None,
                 "distance_m": 0.0, "gear_id": None, "gear_source": None, "has_block": False}
        try:
            block = C.extract_block(path.read_bytes().decode("utf-8", errors="replace"))
        except (C.ContractError, OSError):
            block = None
        if block and block.get("kind") == "activity":
            entry["has_block"] = True
            entry["date"] = block.get("date") or entry["date"]
            aid = block.get("garmin_activity_id")
            entry["garmin_activity_id"] = int(aid) if isinstance(aid, int) and not isinstance(aid, bool) else None
            entry["distance_m"] = float(block.get("distance_m") or 0)
            entry["gear_id"] = block.get("gear_id") or None
            entry["gear_source"] = block.get("gear_source") or None
        elif block is not None:
            continue   # autre type de bloc dans activities/ : ni séance ni « fichier sans identifiant »
        out.append(entry)
    return out


def _atomic_write(path: Path, data: bytes) -> None:
    """Écriture atomique EN OCTETS (fins de ligne intactes), permissions du fichier d'origine conservées."""
    tmp = path.with_name(path.name + ".tmp-gearbackfill")
    tmp.write_bytes(data)
    try:
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
    except OSError:
        pass
    os.replace(tmp, path)


def apply_plan(workspace: Path, profile: Path, result: dict, *, validate=None) -> dict:
    """Écrit puces puis `gear_id` ; chaque fichier est validé AVANT (déjà hors contrat : signalé à part, jamais
    réécrit) et APRÈS écriture (refus : octets d'origine restaurés, seulement si on avait écrit)."""
    if validate is None:
        import arc_index
        validate = arc_index.validate_file
    out: Dict[str, Any] = {"profile_written": False, "linked": [], "retired": [], "written": [], "failed": [], "skipped": [],
                           "out_of_contract": []}
    rel_profile = str(profile.relative_to(workspace)) if profile.is_relative_to(workspace) else str(profile)
    if result["new_bullets"] or result["links"] or result.get("retirements"):
        original = profile.read_bytes()
        text = original.decode("utf-8")
        failed_link = None
        for link in result["links"]:
            updated = append_garmin_segment(text, link["gear_id"], link["uuid"])
            if updated is None:
                failed_link = link
                break
            text = updated
        if failed_link is not None:
            out["failed"].append({"path": rel_profile, "error": f"puce « {failed_link['name']} » introuvable "
                                  "exactement une fois pour y ajouter garmin: — profil inchangé"})
            return out
        for ret in result.get("retirements", []):
            updated = append_retired_marker(text, ret["gear_id"], ret.get("date_end"))
            if updated is None:
                out["failed"].append({"path": rel_profile, "error": f"puce « {ret['name']} » introuvable "
                                      "exactement une fois pour y ajouter (retirée) — profil inchangé"})
                return out
            text = updated
        text = insert_gear_bullets(text, [b["bullet"] for b in result["new_bullets"]])
        _atomic_write(profile, text.encode("utf-8"))
        parsed = {g.get("garmin_uuid"): g["gear_id"] for g in L.parse_gear(text)}
        expected = [(b["uuid"], b["gear_id"]) for b in result["new_bullets"]] + \
                   [(k["uuid"], k["gear_id"]) for k in result["links"]]
        retired_now = {g["gear_id"] for g in L.parse_gear(text) if g.get("retired")}
        if any(parsed.get(u) != gid for u, gid in expected) or \
                any(r["gear_id"] not in retired_now for r in result.get("retirements", [])):
            _atomic_write(profile, original)
            out["failed"].append({"path": rel_profile, "error": "puces non relues après écriture — profil restauré"})
            return out
        out["profile_written"] = True
        out["linked"] = [k["gear_id"] for k in result["links"]]
        out["retired"] = [r["gear_id"] for r in result.get("retirements", [])]
    for a in result["assignments"]:
        path = workspace / a["path"]
        original = path.read_bytes()
        ok, errors, _warnings = validate(path)
        if not ok:
            out["out_of_contract"].append({"path": a["path"], "errors": errors,
                                           "reason": "fichier déjà hors contrat (voir /arc-backfill)"})
            continue
        written = False
        try:
            text = original.decode("utf-8")
            if (C.extract_block(text) or {}).get("gear_id"):
                out["skipped"].append({"path": a["path"], "reason": "gear_id apparu depuis la simulation"})
                continue
            updated = set_block_keys(text, {"gear_id": a["gear_id"], "gear_source": "garmin"})
            _atomic_write(path, updated.encode("utf-8"))
            written = True
            ok, errors, _warnings = validate(path)
            if not ok:
                raise C.ContractError("; ".join(errors) or "validation refusée")
        except (C.ContractError, OSError, ValueError) as exc:
            if written:
                _atomic_write(path, original)
            out["failed"].append({"path": a["path"], "error": str(exc)})
            continue
        out["written"].append(a["path"])
    return out


def reindex(workspace: Path) -> dict:
    import arc_index
    conn = arc_index.open_db(workspace)
    try:
        counts = arc_index.index_workspace(conn, workspace)
        gear = arc_index.gear_mileage(conn)
    finally:
        conn.close()
    return {"index": counts, "gear": gear}


# ---------------------------------------------------------------------------
# Client Garmin (E/S ; garminconnect importé paresseusement)
# ---------------------------------------------------------------------------

class GarminSource:
    """Adaptateur mince : inventaire, séances d'une paire (avec pagination quand l'API le permet)."""

    def __init__(self, client):
        self.client = client
        self._profile_id = None

    def profile_id(self):
        if self._profile_id is None:   # un seul appel `get_device_last_used` par exécution
            self._profile_id = self.client.get_device_last_used().get("userProfileNumber")
        return self._profile_id

    def gear(self) -> List[dict]:
        raw = self.client.get_gear(self.profile_id())
        if not isinstance(raw, list):   # charge d'erreur (dict) : jamais lue comme « aucune chaussure »
            raise RuntimeError(f"réponse get_gear inattendue ({type(raw).__name__}) : {str(raw)[:120]}")
        return raw

    def defaults(self) -> List[dict]:
        try:
            return self.client.get_gear_defaults(self.profile_id()) or []
        except Exception:
            return []

    def gear_activities(self, uuid: str) -> dict:
        """`{"activities": [...], "error": str|None, "truncated": bool}`. `get_gear_activities` n'a pas de
        décalage (`start`) : au plafond de 1000, on pagine par `connectapi` quand le client l'expose,
        sinon la liste est déclarée tronquée (jamais un total présenté comme complet)."""
        try:
            raw = list(self.client.get_gear_activities(uuid, limit=GEAR_ACTIVITIES_PAGE) or [])
        except Exception as exc:   # noqa: BLE001 — une paire injoignable ne doit pas arrêter le rapport
            return {"activities": [], "error": f"{type(exc).__name__}: {exc}", "truncated": False}
        truncated = False
        if len(raw) >= GEAR_ACTIVITIES_PAGE:
            base = getattr(self.client, "garmin_connect_activities_baseurl", None)
            fetch = getattr(self.client, "connectapi", None)
            if base and fetch:
                seen = {a.get("activityId") for a in raw if isinstance(a, dict)}
                offset = len(raw)
                try:
                    for _page in range(GEAR_ACTIVITIES_MAX_PAGES):
                        page = fetch(f"{base}{uuid}/gear?start={offset}&limit={GEAR_ACTIVITIES_PAGE}") or []
                        fresh = [a for a in page if isinstance(a, dict) and a.get("activityId") not in seen]
                        if not fresh:
                            # page vide, ou `start` ignoré (mêmes séances) : fin non garantie
                            truncated = bool(page)
                            break
                        raw.extend(fresh)
                        seen.update(a.get("activityId") for a in fresh)
                        if len(page) < GEAR_ACTIVITIES_PAGE:
                            break
                        offset += len(page)
                    else:
                        truncated = True    # plafond de pages atteint
                except Exception:   # noqa: BLE001
                    truncated = True
            else:
                truncated = True
        return {"activities": normalize_gear_activities(raw), "error": None, "truncated": truncated}


class FakeClient:
    """Client de test (`--fake-client fichier.json`, option cachée) : aucun réseau, aucun jeton."""

    def __init__(self, spec: dict):
        self.spec = spec

    def get_device_last_used(self):
        return {"userProfileNumber": self.spec.get("profile_id", 1)}

    def get_gear(self, _pid):
        return self.spec.get("gear", [])

    def get_gear_defaults(self, _pid):
        return self.spec.get("defaults", [])

    def get_gear_activities(self, uuid, limit=1000):
        value = self.spec.get("gear_activities", {}).get(uuid, [])
        if isinstance(value, str):
            raise RuntimeError(value)
        return value[:limit]


def relaunch_candidates(garmin_python=None, garmin_mcp_exe=None, home=None) -> List[str]:
    """Interpréteurs candidats (ordre de priorité) : `GARMIN_PYTHON`, le venv du binaire `garmin-mcp` du PATH, puis
    l'emplacement uv par défaut. `python3` ET `python` à chaque fois (sur Linux l'un est un lien vers l'autre)."""
    candidates: List[str] = []
    if garmin_python:
        candidates.append(os.path.expanduser(garmin_python))
    if garmin_mcp_exe:
        bindir = os.path.dirname(os.path.realpath(garmin_mcp_exe))
        candidates += [os.path.join(bindir, n) for n in ("python3", "python")]
    base = os.path.join(home or os.path.expanduser("~"), ".local/share/uv/tools/garmin-mcp/bin")
    candidates += [os.path.join(base, n) for n in ("python3", "python")]
    return candidates


def is_current_interpreter(candidate: str, prefix: str = None, executable: str = None) -> bool:
    """Le candidat est-il l'interpréteur courant ? Un venv se reconnaît à son dossier (`pyvenv.cfg` à côté de
    `bin/`), PAS au `realpath` de son python : sur Linux `bin/python` d'un venv uv est un lien vers
    `/usr/bin/python3.x`, donc identique au python système une fois résolu — alors que les deux n'ont pas les
    mêmes paquets. Sans `pyvenv.cfg`, repli sur la comparaison des chemins résolus."""
    prefix = prefix or sys.prefix
    executable = executable or sys.executable
    venv_dir = os.path.dirname(os.path.dirname(os.path.abspath(candidate)))
    if os.path.isfile(os.path.join(venv_dir, "pyvenv.cfg")):
        return os.path.realpath(venv_dir) == os.path.realpath(prefix)
    return os.path.realpath(candidate) == os.path.realpath(executable)


def pick_relaunch_candidate(candidates, prefix: str = None, executable: str = None) -> Optional[str]:
    for py in candidates:
        if os.path.exists(py) and not is_current_interpreter(py, prefix, executable):
            return py
    return None


def _auto_relaunch(argv: List[str]) -> None:
    """Relance avec le python de garmin-mcp quand `garminconnect` manque (comme `download_fit.py`)."""
    try:
        import garminconnect  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("ARC_GEAR_BACKFILL_RELAUNCHED"):   # déjà relancé une fois : pas de ping-pong
        print("ERREUR : 'garminconnect' introuvable même après relance avec le python de garmin-mcp.", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    py = pick_relaunch_candidate(relaunch_candidates(os.environ.get("GARMIN_PYTHON"), shutil.which("garmin-mcp")))
    if py:
        env = dict(os.environ, ARC_GEAR_BACKFILL_RELAUNCHED="1")
        sys.exit(subprocess.run([py, os.path.abspath(__file__)] + argv, env=env).returncode)
    print("ERREUR : module 'garminconnect' introuvable dans cet interpréteur.\n"
          "→ utilisez le python de garmin-mcp : GARMIN_PYTHON=~/.local/share/uv/tools/garmin-mcp/bin/python3",
          file=sys.stderr)
    sys.exit(EXIT_USAGE)


def connect_garmin(token_dir: Path):
    """Client `garminconnect` authentifié par les jetons locaux (aucun mot de passe)."""
    from garminconnect import Garmin   # import paresseux : dépendance non standard documentée
    client = Garmin()
    try:
        client.login(str(token_dir))
    except TypeError:
        client.login()
    return client


# ---------------------------------------------------------------------------
# Rapport
# ---------------------------------------------------------------------------

_STATUS_LABEL = {
    "new": "puce à ajouter", "existing": "puce existante (id réutilisé)", "ignored": "(ignorée) — jamais attribuée",
    "out_of_period": "hors période du workspace", "error": "erreur Garmin",
    "duplicate_in_profile": "uuid dupliqué dans le profil",
    "link_existing": "puce existante sans garmin: — segment à ajouter",
    "name_ambiguous": "nom ambigu dans le profil — rien n'est attribué",
}


def render_report(result: dict, applied: Optional[dict] = None, reindexed: Optional[dict] = None) -> str:
    lo, hi = result["workspace_period"]
    lines = [("RATTRAPAGE DU MATÉRIEL GARMIN — " + ("application" if applied is not None else "simulation (rien n'est écrit)")),
             f"Workspace : {result['workspace_files']} fichier(s) d'activité, {result['workspace_with_id']} avec "
             f"garmin_activity_id, période {lo or '?'} → {hi or '?'}"
             + (f" ; --since {result['since']}" if result["since"] else ""), ""]
    shown = [s for s in result["shoes"] if s["status"] not in ("out_of_period",) or result["all_shoes"]]
    hidden = [s for s in result["shoes"] if s not in shown]
    lines.append(f"PAIRES ({len(shown)} retenue(s)" + (f", {len(hidden)} hors période masquée(s) — --all-shoes pour les proposer" if hidden else "") + ")")
    for s in shown:
        lines.append(f"- {s['name']} [{_STATUS_LABEL.get(s['status'], s['status'])}]"
                     + (" (retirée)" if s["retired"] else ""))
        if s["status"] == "error":
            lines.append(f"    erreur : {s['error']}")
            continue
        ret = next((r for r in result.get("retirements", []) if r["uuid"] == s["uuid"]), None)
        if ret:
            lines.append(f"    → retirée dans Garmin" + (f" le {ret['date_end']}" if ret.get("date_end") else "")
                         + f" : ajouter « (retirée{' ' + ret['date_end'] if ret.get('date_end') else ''}) » à la "
                         f"puce « {ret['gear_id']} » (seul ajout sur une puce existante)")
        if s["status"] == "link_existing":
            lines.append(f"    → ajouter « — garmin: {s['uuid']} » à la puce existante « {s['gear_id']} » "
                         "(seul ajout sur une puce existante)")
        elif s["bullet"]:
            lines.append(f"    puce proposée : {s['bullet']}")
        elif s["gear_id"]:
            lines.append(f"    gear_id : {s['gear_id']}")
        if s.get("name_matches"):
            lines.append("    attention : des séances déclarent déjà « " + "», « ".join(s["name_matches"]) +
                         " » sans puce au profil — à vous de décider si c'est cette paire ; l'id proposé est "
                         f"« {s['gear_id']} » pour ne pas leur attribuer ce matériel en silence")
        lines.append(f"    séances rattachées : {s['matched']} (à écrire {s['to_write']}, déjà attribuées "
                     f"{s['already']}, conflits {s['conflicts']}, ambiguës {s['ambiguous']}"
                     + (f", doublons de fichier {s['duplicates']}" if s['duplicates'] else "")
                     + (f", incohérentes {s['inconsistent']}" if s['inconsistent'] else "")
                     + (f", avant --since {s['before_since']}" if s['before_since'] else "") + ")")
        lines.append(f"    km : {s['workspace_km']:g} dans le workspace · {s['garmin_km']:g} au total chez Garmin "
                     f"({s['garmin_sessions']} séance(s))" + (" — LISTE TRONQUÉE" if s["truncated"] else ""))
        if not s["garmin_sessions"]:
            lines.append("    note : aucune séance renvoyée (paire sans séance, ou 404 Garmin — la bibliothèque "
                         "le masque en liste vide, indiscernable ici)")
        if s["depart_note"]:
            lines.append(f"    départ : {s['depart_note']}")
    if result["garmin_defaults"]:
        lines += ["", "PAIRES PAR DÉFAUT CHEZ GARMIN (non reprises : `(par défaut)` n'est jamais posé automatiquement) : "
                  + ", ".join(result["garmin_defaults"])]
    for title, items, fmt in (
        ("INCOMPLET — liste Garmin en erreur ou tronquée : l'ambiguïté n'est pas garantie, --apply refusé",
         result["incomplete"], lambda i: f"- {i['name']} : {i['reason']}"),
        ("CONFLITS — déclaration déjà présente conservée (priorité athlète/chat)", result["conflicts"],
         lambda c: f"- {c['path']} : garde « {c['kept']} » ({c['kept_source']}), Garmin indique « {c['garmin']} » ({c['garmin_name']})"),
        ("AMBIGUËS — revendiquées par deux paires chez Garmin, jamais attribuées", result["ambiguous"],
         lambda a: f"- activité {a['id']} ({a['date'] or '?'}){'' if a['in_workspace'] else ' hors workspace'} : {len(a['shoes'])} paires"),
        ("DOUBLONS — plusieurs fichiers pour la même séance Garmin, jamais écrits (à trier à la main)",
         result["duplicate_ids"], lambda d: f"- activité {d['id']} : {', '.join(d['paths'])}"),
        ("INCOHÉRENTS — gear_source sans gear_id (contrat invalide), laissés tels quels", result["inconsistent"],
         lambda i: f"- {i['path']} (gear_source: {i['gear_source']})"),
    ):
        if items:
            lines += ["", f"{title} ({len(items)})"] + [fmt(i) for i in items[:20]]
            if len(items) > 20:
                lines.append(f"  … et {len(items) - 20} autre(s) (voir --json)")
    miss = result["missing_from_workspace"]
    if miss:
        labels = (("before", "antérieures au premier fichier du workspace — comptées dans « départ » des puces nouvelles"),
                  ("in_period", "dans la période du workspace (trous) — non comptées, jamais réimportées ici"),
                  ("after", "postérieures au dernier fichier — non comptées (la synchronisation les importera)"),
                  ("undated", "sans date — non comptées"))
        lines += ["", f"SÉANCES GARMIN ABSENTES DU WORKSPACE ({len(miss)}, {sum(m['distance_km'] for m in miss):.0f} km)"]
        for key, label in labels:
            part = [m for m in miss if m["bucket"] == key]
            if part:
                lines.append(f"  - {len(part)} ({sum(m['distance_km'] for m in part):.0f} km) {label}")
    if result["workspace_without_id"]:
        lines += ["", f"FICHIERS SANS garmin_activity_id : {len(result['workspace_without_id'])} — non rattachables "
                  "automatiquement (déclarer la paire dans le chat)"]
    total_write = len(result["assignments"])
    lines += ["", f"BILAN : {len(result['new_bullets'])} puce(s) à ajouter, {len(result['links'])} segment(s) garmin: à "
              f"ajouter à une puce existante, {len(result.get('retirements', []))} retraite(s) Garmin à reporter, {total_write} séance(s) à renseigner, {len(result['conflicts'])} "
              f"conflit(s), {len(result['ambiguous'])} ambiguë(s)."]
    if applied is None:
        lines.append("Simulation seulement. Pour écrire : relancer avec --apply.")
    else:
        lines.append(f"Appliqué : profil {'mis à jour' if applied['profile_written'] else 'inchangé'}, "
                     f"{len(applied['written'])} séance(s) écrite(s), {len(applied['failed'])} échec(s), "
                     f"{len(applied['out_of_contract'])} déjà hors contrat, {len(applied['skipped'])} ignorée(s).")
        for f in applied["failed"]:
            lines.append(f"  échec : {f['path']} — {f['error']}")
        for f in applied["out_of_contract"]:
            lines.append(f"  {f['path']} — {f['reason']}")
        if reindexed:
            lines.append(f"Index reconstruit : {reindexed['index']}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workspace", help="racine du workspace (sinon ARC_WORKSPACE / défaut du moteur)")
    p.add_argument("--apply", action="store_true", help="écrit (sinon simulation)")
    p.add_argument("--since", metavar="AAAA-MM-JJ", help="ne renseigne que les séances du workspace à partir de cette date")
    p.add_argument("--gear", metavar="UUID", help="une seule paire Garmin (toutes sont tout de même lues, pour l'ambiguïté)")
    p.add_argument("--all-shoes", action="store_true",
                   help="propose aussi les paires sans séance dans la période du workspace (puces `(retirée)`)")
    p.add_argument("--json", action="store_true", help="sortie machine")
    p.add_argument("--tokens-dir", help="répertoire des jetons Garmin (défaut : résolution de coach_doctor)")
    p.add_argument("--fake-client", help=argparse.SUPPRESS)   # tests : JSON d'un client simulé, aucun réseau
    return p


def _profile_path(workspace: Path) -> Path:
    import arc_index
    try:
        rel = arc_index.load_config(workspace).get("athlete", {}).get("profile") or DEFAULT_PROFILE_REL
    except Exception:   # noqa: BLE001 — TOML invalide : le doctor le signale, défaut ici
        rel = DEFAULT_PROFILE_REL
    return workspace / rel


def run(args, source=None) -> Tuple[int, dict, str]:
    """Cœur testable : `(code, charge JSON, rapport texte)`. `source` = `GarminSource` (injectable)."""
    from coach_setup import workspace_root
    workspace = workspace_root(args.workspace)
    if args.since:
        try:
            date.fromisoformat(args.since)
        except ValueError:
            return EXIT_USAGE, {"error": "--since"}, f"--since : date AAAA-MM-JJ attendue, « {args.since} » reçue."
    profile = _profile_path(workspace)
    profile_text = profile.read_text(encoding="utf-8") if profile.is_file() else ""
    if args.apply and not profile.is_file():
        return EXIT_NO_PROFILE, {"error": "profile_missing"}, (
            f"Profil athlète introuvable ({profile}) : lancez /coach-setup avant --apply.")
    if source is None:
        return EXIT_USAGE, {"error": "no_source"}, "aucune source Garmin"
    try:
        raw_gear = source.gear()
        shoes = normalize_shoes(raw_gear)
    except Exception as exc:   # noqa: BLE001
        return EXIT_USAGE, {"error": "garmin"}, f"Garmin injoignable : {type(exc).__name__}: {exc}"
    if args.gear and not any(s["uuid"] == args.gear.strip().lower() for s in shoes):
        return EXIT_USAGE, {"error": "gear_not_found"}, f"--gear : aucune chaussure Garmin d'uuid {args.gear}."
    # TOUTES les paires sont lues : `--gear` ne restreint que ce qui est proposé/écrit, jamais la détection
    # d'ambiguïté (une séance commune à la paire choisie et à une autre n'est attribuée à aucune des deux).
    gear_acts = {s["uuid"]: source.gear_activities(s["uuid"]) for s in shoes}
    ws_files = scan_workspace(workspace)
    equipment_ids = {e["gear_id"] for e in L.parse_equipment(profile_text)} if profile_text else set()
    shoe_names = {s["uuid"]: s["name"] for s in shoes}
    default_names = sorted({shoe_names.get(str(d.get("uuid") or "").lower(), "") for d in source.defaults()} - {""})
    result = plan(shoes, gear_acts, ws_files, L.parse_gear(profile_text) if profile_text else [],
                  since=args.since, only_gear=args.gear, all_shoes=args.all_shoes,
                  extra_used_ids=equipment_ids, garmin_defaults=default_names)
    code, applied, reindexed = EXIT_OK, None, None
    if result["incomplete"]:
        code = EXIT_PARTIAL
    if args.apply and result["incomplete"]:
        # Une paire illisible ou tronquée peut cacher une ambiguïté : aucune écriture, nulle part.
        payload = {"dry_run": True, "apply_refused": True, "workspace": str(workspace), **result}
        return EXIT_PARTIAL, payload, render_report(result) + (
            "\n\n--apply REFUSÉ : au moins une paire est en erreur ou tronquée (section INCOMPLET) ; rien n'a été écrit. "
            "Relancez quand Garmin répond, ou après avoir réglé le problème.")
    if args.apply:
        # Instantané du statut Garmin (`.arc/garmin_gear.json`, dérivé) : la retraite d'une paire liée prend effet
        # dans l'index même si la puce n'est pas (encore) modifiée. Écrit seulement avec --apply (simulation = rien).
        import arc_garmin_gear as GG
        try:
            GG.write_cache(workspace, GG.normalize_garmin_shoes(raw_gear))
        except (OSError, GG.GarminGearError):
            pass
        applied = apply_plan(workspace, profile, result)
        if applied["failed"]:
            code = EXIT_PARTIAL
        reindexed = reindex(workspace)
    payload = {"dry_run": not args.apply, "workspace": str(workspace), **result}
    if applied is not None:
        payload["applied"] = applied
        payload["reindexed"] = reindexed
    return code, payload, render_report(result, applied, reindexed)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.fake_client:
        source = GarminSource(FakeClient(json.loads(Path(args.fake_client).read_text(encoding="utf-8"))))
    else:
        _auto_relaunch(sys.argv[1:] if argv is None else list(argv))
        from coach_doctor import resolve_tokens_dir
        from coach_setup import workspace_root
        tokens = resolve_tokens_dir(args.tokens_dir, workspace_root(args.workspace))
        print("Connexion à Garmin Connect (jusqu'à ~2 min)…", file=sys.stderr)
        try:
            source = GarminSource(connect_garmin(tokens))
        except Exception as exc:   # noqa: BLE001
            print(f"Authentification Garmin impossible ({type(exc).__name__}: {exc}). Vérifiez {tokens} "
                  "(/coach-doctor).", file=sys.stderr)
            return EXIT_USAGE
    code, payload, report = run(args, source)
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else report)
    return code


if __name__ == "__main__":
    sys.exit(main())
