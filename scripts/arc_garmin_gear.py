#!/usr/bin/env python3
"""Cycle de vie des chaussures Garmin (retraite) — stdlib seule.

Une paire retirée dans Garmin Connect (`gearStatusName = "retired"`) l'était jusqu'ici pour le coach
SEULEMENT si sa puce du profil portait `(retirée)` : la puce n'était créée qu'une fois (rattrapage
#145 ou association #133), et une retraite décidée PLUS TARD dans Garmin ne remontait jamais — la
paire restait « À surveiller » / « Inspection conseillée » alors qu'elle n'était plus portée.

Ce module :
  - normalise la réponse de `get_gear` (forme du serveur MCP `garmin-mcp` — `type`, `status`,
    `date_end`… — ou forme brute de `garminconnect` — `gearTypeName`, `gearStatusName`, `dateEnd`…) ;
  - tient un instantané local `.arc/garmin_gear.json` (dérivé, jetable comme `.arc/coach.db`,
    réécrit à chaque lecture de `get_gear`) ;
  - calcule le statut EFFECTIF de chaque puce : profil `(retirée)` OU paire liée (`garmin: <uuid>`)
    retirée dans Garmin. La retraite Garmin prend effet IMMÉDIATEMENT, sans attendre que la puce
    soit modifiée (`retired_source: "garmin"`) ; le profil n'est jamais écrit ici ;
  - liste les désaccords profil ↔ Garmin (`status_drift`) pour que le coach PROPOSE, une fois et
    en interactif seulement, d'écrire `(retirée AAAA-MM-JJ)` sur la puce.

Règles : seules les puces liées par un `garmin: <uuid>` porté par UNE seule puce sont concernées
(un uuid en double reste ambigu, jamais résolu) ; une puce `(ignorée)` n'est jamais touchée ; une
paire retirée au profil mais active dans Garmin reste retirée (jamais « dé-retirée »
automatiquement), le désaccord est seulement signalé.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CACHE_REL = ".arc/garmin_gear.json"
CACHE_VERSION = 1

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_UUID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{7,63}$")   # même forme que `arc_legacy.GEAR_GARMIN_UUID_RE`


class GarminGearError(ValueError):
    """Réponse `get_gear` illisible (jamais un instantané partiel écrit en silence)."""


def _date(value: Any) -> Optional[str]:
    m = _DATE_RE.match(str(value or "").strip())
    return m.group(1) if m else None


def _text(value: Any) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or None


def normalize_garmin_shoes(payload: Any) -> List[dict]:
    """Réponse de `get_gear` → `[{uuid, name, status, date_begin, date_end}]`, chaussures seulement.

    Accepte l'objet du serveur MCP (`{"gear": [...]}`), une liste nue, et les deux formes d'élément
    (MCP : `type`/`status`/`date_begin`/`date_end`/`name` ; brute : `gearTypeName`/`gearStatusName`/
    `dateBegin`/`dateEnd`/`displayName`). `status` en minuscules (`active` | `retired` | autre tel quel).
    Lève `GarminGearError` si la forme n'est pas reconnue."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise GarminGearError(f"JSON illisible : {exc}") from exc
    if isinstance(payload, dict):
        if not isinstance(payload.get("gear"), list):
            raise GarminGearError("objet sans liste « gear » (réponse get_gear attendue)")
        items = payload["gear"]
    elif isinstance(payload, list):
        items = payload
    else:
        raise GarminGearError("réponse get_gear attendue (objet avec « gear » ou liste)")
    shoes: List[dict] = []
    seen = set()
    for g in items:
        if not isinstance(g, dict):
            continue
        kind = str(g.get("type") or g.get("gearTypeName") or "").strip().lower()
        if kind != "shoes":
            continue
        uuid = str(g.get("uuid") or "").strip().lower()
        if not _UUID_RE.match(uuid) or uuid in seen:
            continue
        seen.add(uuid)
        status = str(g.get("status") or g.get("gearStatusName") or "").strip().lower() or None
        shoe = {"uuid": uuid,
                "name": _text(g.get("name") or g.get("displayName")) or _text(g.get("full_name") or g.get("customMakeModel")),
                "status": status,
                "date_begin": _date(g.get("date_begin") or g.get("dateBegin")),
                "date_end": _date(g.get("date_end") or g.get("dateEnd"))}
        shoes.append({k: v for k, v in shoe.items() if v is not None})
    shoes.sort(key=lambda s: s["uuid"])
    return shoes


def cache_path(workspace: Path) -> Path:
    return Path(workspace) / CACHE_REL


def write_cache(workspace: Path, shoes: List[dict], fetched_at: Optional[str] = None) -> dict:
    """Écrit l'instantané (atomique). Rend son contenu."""
    data = {"version": CACHE_VERSION,
            "fetched_at": fetched_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "shoes": shoes}
    path = cache_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return data


def load_cache(workspace: Path) -> Optional[dict]:
    """Instantané lu, ou `None` (absent, illisible, version inconnue) — jamais une exception :
    sans instantané, le statut est celui du profil, comme avant."""
    try:
        data = json.loads(cache_path(workspace).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or not isinstance(data.get("shoes"), list):
        return None
    return data


def _linked(profile_gear: List[dict]) -> Dict[str, dict]:
    """`{uuid: puce}` des uuid portés par UNE seule puce non `(ignorée)`."""
    by_uuid: Dict[str, List[dict]] = {}
    for g in profile_gear:
        u = (g.get("garmin_uuid") or "").strip().lower()
        if u:
            by_uuid.setdefault(u, []).append(g)
    return {u: gs[0] for u, gs in by_uuid.items() if len(gs) == 1 and not gs[0].get("ignored")}


def effective_status(profile_gear: List[dict], cache: Optional[dict]) -> Dict[str, dict]:
    """`{gear_id: {retired, retired_source, retired_date, garmin_status}}` pour chaque puce.

    `retired_source` : `profile` (puce `(retirée)`), `garmin` (paire liée retirée dans Garmin, puce
    pas encore modifiée) ou absent (active). `retired_date` : celle de la puce, sinon `date_end` de
    Garmin quand Garmin la donne. `garmin_status` : statut Garmin de la paire liée, s'il est connu."""
    garmin = {s["uuid"]: s for s in (cache or {}).get("shoes", []) if isinstance(s, dict) and s.get("uuid")}
    linked = _linked(profile_gear)
    out: Dict[str, dict] = {}
    for g in profile_gear:
        gid = g.get("gear_id")
        if not gid:
            continue
        uuid = (g.get("garmin_uuid") or "").strip().lower()
        remote = garmin.get(uuid) if uuid and linked.get(uuid) is g else None
        st: Dict[str, Any] = {"retired": False}
        if remote and remote.get("status"):
            st["garmin_status"] = remote["status"]
        if g.get("retired"):
            st.update(retired=True, retired_source="profile")
            date = g.get("retired_date")
            if not date and remote and remote.get("status") == "retired":
                date = remote.get("date_end")
            if date:
                st["retired_date"] = date
        elif remote and remote.get("status") == "retired":
            st.update(retired=True, retired_source="garmin")
            if remote.get("date_end"):
                st["retired_date"] = remote["date_end"]
        out[gid] = st
    return out


def status_drift(profile_gear: List[dict], cache: Optional[dict]) -> List[dict]:
    """Désaccords profil ↔ Garmin sur les puces liées : `retired_in_garmin` (à proposer d'écrire
    `(retirée …)` sur la puce) et `active_in_garmin` (signalé seulement, jamais « dé-retiré »)."""
    garmin = {s["uuid"]: s for s in (cache or {}).get("shoes", []) if isinstance(s, dict) and s.get("uuid")}
    drift = []
    for uuid, g in sorted(_linked(profile_gear).items(), key=lambda kv: kv[1]["gear_id"]):
        remote = garmin.get(uuid)
        if not remote:
            continue
        item = {"gear_id": g["gear_id"], "name": g.get("name") or g["gear_id"], "uuid": uuid,
                "garmin_name": remote.get("name")}
        if remote.get("status") == "retired" and not g.get("retired"):
            item["kind"] = "retired_in_garmin"
            if remote.get("date_end"):
                item["date_end"] = remote["date_end"]
            item["marker"] = f"(retirée {remote['date_end']})" if remote.get("date_end") else "(retirée)"
            drift.append(item)
        elif remote.get("status") == "active" and g.get("retired"):
            item["kind"] = "active_in_garmin"
            drift.append(item)
    return drift


def unlinked_garmin_shoes(profile_gear: List[dict], cache: Optional[dict]) -> List[dict]:
    """Chaussures Garmin sans aucune puce (ni liée, ni `(ignorée)`) — pour information."""
    known = {(g.get("garmin_uuid") or "").strip().lower() for g in profile_gear if g.get("garmin_uuid")}
    return [s for s in (cache or {}).get("shoes", []) if isinstance(s, dict) and s.get("uuid") not in known]
