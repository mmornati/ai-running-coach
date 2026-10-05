#!/usr/bin/env python3
"""Coefficient de TECHNICITÉ du terrain par section de course (#186, épopée #170).

Module pur (sauf `fetch_ways*`, seul code qui touche réseau/disque, avec un `fetcher` injectable
pour les tests). Stdlib uniquement. Consommé par `arc_race_pacing.py` (étape « technicité » de
`build_race_plan`, voir `ASSUMPTIONS["technicity"]`).

Deux sources, la déclaration de l'athlète gagnant section par section :

* **déclarée** (`--technicity fichier.json`) : `{"sections": [{"km_start": 12, "km_end": 18,
  "coef": 1.25, "note": "pierriers"}]}` — 1.0 = terrain « comme à l'entraînement », 1.25 = très technique ;
* **dérivée d'OpenStreetMap** (`--technicity osm`, opt-in, réseau) : chemins proches de la trace
  (Overpass), appariés au plus proche à moins de `MATCH_RADIUS_M`, tags -> coefficient par la
  table ci-dessous (APPROXIMATIONS DU PROJET, jamais des mesures).

Seules des traces de COURSE (GPX de parcours officiel) sont envoyées à Overpass, jamais une trace
d'activité personnelle : l'appelant décide, ce module n'envoie que des boîtes englobantes
arrondies de la trace qu'on lui donne.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "ai-running-coach/technicity (+https://github.com/mmornati/ai-running-coach)"
OVERPASS_TIMEOUT_S = 60
# Politesse envers l'instance publique : une requête à la fois, pause entre deux requêtes réseau
# (les réponses en cache n'attendent pas).
OVERPASS_PAUSE_S = 1.5
# 429 (quota par IP) et 502/503/504 (instance surchargée, délai dépassé) sont TRANSITOIRES sur
# l'instance publique : quelques nouvelles tentatives espacées avant de conclure « indisponible ».
OVERPASS_RETRY_STATUS = (429, 502, 503, 504)
OVERPASS_RETRIES = 2
OVERPASS_RETRY_BASE_S = 5.0
OVERPASS_RETRY_MAX_WAIT_S = 30.0

# Rayon d'appariement point de trace -> chemin OSM (m) et marge de la boîte de requête (m).
MATCH_RADIUS_M = 20.0
BBOX_PAD_M = 60.0
# La trace est découpée en tronçons de ~CHUNK_KM km (une boîte par tronçon) : une boîte unique
# sur un ultra serait énorme et ferait expirer Overpass.
CHUNK_KM = 8.0
# Pas d'échantillonnage de la trace pour l'appariement (m).
SAMPLE_STEP_M = 40.0
# Part minimale (distance) de la section appariée à un chemin OSM pour dériver un coefficient ;
# en dessous la section reste sans coefficient (1.0, source "none") plutôt qu'une valeur inventée.
MIN_OSM_COVERAGE = 0.30
# Part minimale de la section couverte par une déclaration pour que la déclaration l'emporte.
MIN_DECLARED_COVERAGE = 0.50

# Bornes. Un coefficient DÉCLARÉ peut descendre sous 1 (route roulante) ; un coefficient DÉRIVÉ
# d'OSM ne descend jamais sous 1.0 (aucun crédit de vitesse déduit de tags incertains).
COEF_MIN_DECLARED = 0.80
COEF_MAX = 1.80

# Table tags -> SURCOÛT de temps (coef - 1), approximations du projet (voir ASSUMPTIONS).
SAC_SCALE_EXCESS: Dict[str, float] = {
    "hiking": 0.00,                        # T1
    "mountain_hiking": 0.06,               # T2
    "demanding_mountain_hiking": 0.15,     # T3
    "alpine_hiking": 0.30,                 # T4
    "demanding_alpine_hiking": 0.45,       # T5
    "difficult_alpine_hiking": 0.60,       # T6
}
TRAIL_VISIBILITY_EXCESS: Dict[str, float] = {
    "excellent": 0.00, "good": 0.00, "intermediate": 0.05, "bad": 0.12, "horrible": 0.25, "no": 0.35,
}
SURFACE_EXCESS: Dict[str, float] = {
    "asphalt": 0.00, "paved": 0.00, "concrete": 0.00, "paving_stones": 0.00, "compacted": 0.00,
    "fine_gravel": 0.00, "gravel": 0.03, "unpaved": 0.03, "ground": 0.03, "dirt": 0.03, "earth": 0.03,
    "grass": 0.04, "pebblestone": 0.08, "rock": 0.12, "sand": 0.15, "mud": 0.15, "snow": 0.15,
}
TRACKTYPE_EXCESS: Dict[str, float] = {
    "grade1": 0.00, "grade2": 0.00, "grade3": 0.03, "grade4": 0.06, "grade5": 0.10,
}
HIGHWAY_EXCESS: Dict[str, float] = {
    "steps": 0.15, "path": 0.02, "footway": 0.00, "track": 0.00, "bridleway": 0.00, "cycleway": 0.00,
    "pedestrian": 0.00, "service": 0.00, "unclassified": 0.00, "residential": 0.00, "tertiary": 0.00,
    "secondary": 0.00, "primary": 0.00, "living_street": 0.00, "road": 0.00,
}
# Combinaison : surcoût dominant + moitié du deuxième (les tags sont corrélés : un sentier T4 est
# presque toujours « bad visibility » et « rock », on n'additionne pas).
SECOND_EXCESS_WEIGHT = 0.5

# Pondération montée/descente du surcoût (voir ASSUMPTIONS) : en montée l'effort est limité par la
# puissance plus que par l'appui (poids réduit) ; en descente le terrain technique ralentit
# davantage (poids croissant avec la pente de descente jusqu'à un plafond).
UPHILL_WEIGHT = 0.7
FLAT_GRADE_PCT = 2.0
DOWNHILL_WEIGHT_MAX = 1.5
DOWNHILL_RAMP_GRADE_PCT = 10.0

OVERPASS_HIGHWAY_RE = ("path|track|footway|steps|bridleway|cycleway|pedestrian|service|unclassified|"
                       "residential|tertiary|secondary|primary|living_street|road")


class TechnicityError(ValueError):
    """Entrée déclarée invalide (fichier, bornes) — message affichable tel quel."""


class OverpassError(RuntimeError):
    """Réseau/Overpass indisponible : jamais fatal, le plan dit « pas de coefficient OSM »."""


# ---------------------------------------------------------------------------
# Tags -> coefficient
# ---------------------------------------------------------------------------

def tag_excess(tags: Dict[str, str]) -> Tuple[float, List[str]]:
    """Surcoût de temps (fraction) et liste des tags utilisés pour un chemin OSM.
    Aucun tag exploitable -> `(0.0, [])` ; une valeur de tag inconnue est ignorée (jamais devinée)."""
    found: List[Tuple[float, str]] = []
    for key, table in (("sac_scale", SAC_SCALE_EXCESS), ("trail_visibility", TRAIL_VISIBILITY_EXCESS),
                       ("surface", SURFACE_EXCESS), ("tracktype", TRACKTYPE_EXCESS),
                       ("highway", HIGHWAY_EXCESS)):
        value = (tags.get(key) or "").strip().lower()
        if value in table:
            found.append((table[value], f"{key}={value}"))
    if not found:
        return 0.0, []
    ordered = sorted(found, key=lambda x: -x[0])
    excess = ordered[0][0] + (SECOND_EXCESS_WEIGHT * ordered[1][0] if len(ordered) > 1 else 0.0)
    used = [label for _e, label in found if _e > 0.0] or [found[0][1]]
    return excess, used


def coef_from_tags(tags: Dict[str, str]) -> Tuple[float, List[str]]:
    excess, used = tag_excess(tags)
    return min(COEF_MAX, 1.0 + excess), used


def grade_weight(grade_mean_pct: Optional[float]) -> float:
    """Poids du surcoût selon la pente moyenne de la section (1.0 si inconnue ou à plat)."""
    if grade_mean_pct is None:
        return 1.0
    if grade_mean_pct > FLAT_GRADE_PCT:
        return UPHILL_WEIGHT
    if grade_mean_pct >= -FLAT_GRADE_PCT:
        return 1.0
    ramp = min(1.0, (-grade_mean_pct - FLAT_GRADE_PCT) / DOWNHILL_RAMP_GRADE_PCT)
    return 1.0 + (DOWNHILL_WEIGHT_MAX - 1.0) * ramp


def effective_factor(coef: float, grade_mean_pct: Optional[float]) -> float:
    """Multiplicateur de temps réellement appliqué : `1 + (coef - 1) × poids(pente)`. Un coef
    sous 1 (route déclarée) est pondéré de la même façon (plus de gain en descente roulante)."""
    return 1.0 + (coef - 1.0) * grade_weight(grade_mean_pct)


# ---------------------------------------------------------------------------
# Référence : terrain HABITUEL de l'athlète (ancrage des coefficients OSM)
# ---------------------------------------------------------------------------

def parse_baseline(value: Optional[str]) -> Tuple[float, str]:
    """`--technicity-baseline` -> `(coef de référence, libellé)`. Accepte un nombre dans
    [1.0, COEF_MAX] ou une valeur `sac_scale` (ex. `mountain_hiking` -> 1.06) décrivant le terrain
    sur lequel l'athlète s'entraîne d'habitude. Absent -> `(1.0, "")` (référence = chemin facile).
    Lève `TechnicityError` sur une valeur inconnue (jamais devinée)."""
    if value is None or not str(value).strip():
        return 1.0, ""
    raw = str(value).strip().lower()
    if raw in SAC_SCALE_EXCESS:
        return 1.0 + SAC_SCALE_EXCESS[raw], f"sac_scale={raw}"
    try:
        num = float(raw.replace(",", "."))
    except ValueError:
        raise TechnicityError(
            f"--technicity-baseline : « {value} » n'est ni un nombre ni une valeur sac_scale "
            f"({', '.join(SAC_SCALE_EXCESS)})")
    if not (math.isfinite(num) and 1.0 <= num <= COEF_MAX):
        raise TechnicityError(f"--technicity-baseline : {num} hors de [1.0, {COEF_MAX}]")
    return num, f"{num:g}"


def rebase(coef: float, baseline: float) -> float:
    """Coefficient OSM (absolu, 1.0 = chemin facile) -> relatif au terrain habituel de l'athlète,
    déjà contenu dans son modèle pente -> allure. Plancher 1.0 : un parcours plus facile que
    l'entraînement ne donne aucun crédit de vitesse tiré de tags incertains."""
    return max(1.0, coef / baseline) if baseline > 0 else coef


# ---------------------------------------------------------------------------
# Déclaration
# ---------------------------------------------------------------------------

def load_declared(path: Path) -> List[dict]:
    """Lit `{"sections": [{"km_start", "km_end", "coef", "note"?}]}` ; lève `TechnicityError`."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TechnicityError(f"--technicity : fichier introuvable — {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise TechnicityError(f"--technicity : fichier illisible ({exc})")
    return validate_declared(data)


def validate_declared(data) -> List[dict]:
    sections = data.get("sections") if isinstance(data, dict) else data
    if not isinstance(sections, list) or not sections:
        raise TechnicityError('--technicity : attendu {"sections": [{"km_start", "km_end", "coef"}, ...]}')
    out = []
    for i, sec in enumerate(sections, start=1):
        try:
            a, b, c = float(sec["km_start"]), float(sec["km_end"]), float(sec["coef"])
        except (KeyError, TypeError, ValueError):
            raise TechnicityError(f"--technicity : section {i} invalide (km_start, km_end, coef numériques requis)")
        if not all(math.isfinite(x) for x in (a, b, c)):
            raise TechnicityError(f"--technicity : section {i} : valeur non finie")
        if not (0.0 <= a < b):
            raise TechnicityError(f"--technicity : section {i} : il faut 0 <= km_start < km_end")
        if not (COEF_MIN_DECLARED <= c <= COEF_MAX):
            raise TechnicityError(
                f"--technicity : section {i} : coef {c} hors de [{COEF_MIN_DECLARED}, {COEF_MAX}]")
        out.append({"km_start": a, "km_end": b, "coef": c, "note": str(sec.get("note") or "")})
    return out


def declared_for_segment(declared: Sequence[dict], km_start: float, km_end: float
                          ) -> Optional[Tuple[float, float, List[str]]]:
    """`(coef moyen pondéré par le recouvrement, part couverte, notes)` ou `None` si aucun recouvrement."""
    length = km_end - km_start
    if length <= 0:
        return None
    covered, weighted, notes = 0.0, 0.0, []
    for sec in declared:
        ov = min(km_end, sec["km_end"]) - max(km_start, sec["km_start"])
        if ov > 1e-9:
            covered += ov
            weighted += ov * sec["coef"]
            if sec.get("note") and sec["note"] not in notes:
                notes.append(sec["note"])
    if covered <= 0:
        return None
    return weighted / covered, min(1.0, covered / length), notes


# ---------------------------------------------------------------------------
# Overpass (réseau opt-in) + cache
# ---------------------------------------------------------------------------

def _hav_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def cumulative_m(pts: Sequence[dict]) -> List[float]:
    out = [0.0]
    for a, b in zip(pts, pts[1:]):
        out.append(out[-1] + _hav_m(a["lat"], a["lon"], b["lat"], b["lon"]))
    return out


def sample_track(pts: Sequence[dict], step_m: float = SAMPLE_STEP_M) -> List[dict]:
    """Points `{lat, lon, d_m}` espacés d'au moins `step_m` le long de la trace (premier et dernier inclus)."""
    if not pts:
        return []
    dist = cumulative_m(pts)
    out, last = [], -1e18
    for p, d in zip(pts, dist):
        if d - last >= step_m:
            out.append({"lat": p["lat"], "lon": p["lon"], "d_m": d})
            last = d
    if out[-1]["d_m"] < dist[-1]:
        out.append({"lat": pts[-1]["lat"], "lon": pts[-1]["lon"], "d_m": dist[-1]})
    return out


def chunk_bboxes(samples: Sequence[dict], chunk_km: float = CHUNK_KM, pad_m: float = BBOX_PAD_M
                  ) -> List[Tuple[float, float, float, float]]:
    """Boîtes englobantes `(sud, ouest, nord, est)` arrondies à 4 décimales (~10 m), une par tronçon."""
    if not samples:
        return []
    deg_lat = pad_m / 111_320.0
    boxes, cur = [], []
    start_d = samples[0]["d_m"]
    for s in samples:
        if cur and s["d_m"] - start_d > chunk_km * 1000.0:
            boxes.append(cur)
            cur, start_d = [cur[-1]], cur[-1]["d_m"]  # recouvrement d'un point : aucun trou entre tronçons
        cur.append(s)
    if cur:
        boxes.append(cur)
    out = []
    for grp in boxes:
        lats, lons = [p["lat"] for p in grp], [p["lon"] for p in grp]
        mid = math.radians((min(lats) + max(lats)) / 2.0)
        deg_lon = pad_m / (111_320.0 * max(0.01, math.cos(mid)))
        out.append((round(min(lats) - deg_lat, 4), round(min(lons) - deg_lon, 4),
                    round(max(lats) + deg_lat, 4), round(max(lons) + deg_lon, 4)))
    return out


def build_query(bbox: Tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    return (f'[out:json][timeout:{OVERPASS_TIMEOUT_S}];'
            f'way["highway"~"^({OVERPASS_HIGHWAY_RE})$"]({s},{w},{n},{e});out tags geom;')


def _retry_delay_s(exc: urllib.error.HTTPError, attempt: int) -> float:
    """Pause avant une nouvelle tentative : `Retry-After` (secondes) s'il est fourni, sinon
    attente exponentielle ; toujours plafonnée à `OVERPASS_RETRY_MAX_WAIT_S`."""
    try:
        hinted = float((exc.headers or {}).get("Retry-After") or "")
    except (TypeError, ValueError):
        hinted = None
    wait = hinted if hinted is not None and hinted >= 0 else OVERPASS_RETRY_BASE_S * (2 ** attempt)
    return min(OVERPASS_RETRY_MAX_WAIT_S, wait)


def check_payload(payload) -> dict:
    """Refuse une réponse Overpass inexploitable. Overpass répond HTTP 200 avec un champ `remark`
    (« runtime error: Query timed out… », « out of memory ») et des `elements` vides ou TRONQUÉS
    quand la requête échoue côté serveur : la traiter comme un succès mettrait en cache, pour
    toujours, un tronçon vide (aucun coefficient sur cette partie du parcours)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise OverpassError("réponse Overpass inattendue (pas de liste `elements`)")
    remark = str(payload.get("remark") or "")
    if "error" in remark.lower():
        raise OverpassError(f"Overpass : {remark[:160]}")
    return payload


def _default_fetcher(query: str, *, sleep: Callable[[float], None] = time.sleep,
                     opener: Callable = urllib.request.urlopen) -> dict:
    """POST de la requête à `OVERPASS_URL`. 429 (quota) / 502-504 (surcharge, délai) : jusqu'à
    `OVERPASS_RETRIES` nouvelles tentatives espacées (politesse envers l'instance publique) ; toute
    autre erreur, ou l'échec de la dernière tentative, lève `OverpassError`."""
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    attempt = 0
    while True:
        req = urllib.request.Request(OVERPASS_URL, data=data, headers={"User-Agent": USER_AGENT})
        try:
            with opener(req, timeout=OVERPASS_TIMEOUT_S + 10) as resp:
                return check_payload(json.loads(resp.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            exc.close()  # libère la connexion avant d'attendre / de conclure
            if exc.code in OVERPASS_RETRY_STATUS and attempt < OVERPASS_RETRIES:
                sleep(_retry_delay_s(exc, attempt))
                attempt += 1
                continue
            raise OverpassError(f"HTTP {exc.code}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise OverpassError(str(exc))


def parse_ways(payload: dict) -> List[dict]:
    """Réponse Overpass `out tags geom` -> `[{id, tags, geom: [(lat, lon), ...]}]` (voir le format
    vérifié : `elements[].{type:"way", id, tags, geometry:[{lat, lon}]}`)."""
    ways = []
    for el in (payload or {}).get("elements", []):
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        geom = [(g["lat"], g["lon"]) for g in el["geometry"] if "lat" in g and "lon" in g]
        if len(geom) >= 2:
            ways.append({"id": el.get("id"), "tags": dict(el.get("tags") or {}), "geom": geom})
    return ways


def fetch_ways(pts: Sequence[dict], *, cache_dir: Optional[Path] = None,
               fetcher: Optional[Callable[[str], dict]] = None,
               sleep: Callable[[float], None] = time.sleep) -> Tuple[List[dict], dict]:
    """Chemins OSM autour de la trace, tronçon par tronçon, avec cache disque (`cache_dir`,
    ex. `<workspace>/.arc/overpass`). Lève `OverpassError` si un tronçon échoue (tout ou rien :
    un coefficient dérivé d'une moitié de parcours serait trompeur). Rend `(ways, info)` avec
    `info = {requests, cache_hits}` ; les ways sont dédoublonnés par id."""
    fetch = fetcher or _default_fetcher
    boxes = chunk_bboxes(sample_track(pts))
    seen, ways = set(), []
    requests = hits = 0
    for box in boxes:
        query = build_query(box)
        key = hashlib.sha256(query.encode("utf-8")).hexdigest()[:24]
        payload = None
        cache_file = (Path(cache_dir) / f"{key}.json") if cache_dir else None
        if cache_file and cache_file.is_file():
            try:
                payload = check_payload(json.loads(cache_file.read_text(encoding="utf-8")))
                hits += 1
            except (OSError, ValueError, OverpassError):  # cache illisible/invalide -> refait la requête
                payload = None
        if payload is None:
            if requests:
                sleep(OVERPASS_PAUSE_S)
            payload = check_payload(fetch(query))
            requests += 1
            if cache_file:
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    # écriture atomique : un fichier tronqué (arrêt brutal) ne doit jamais passer pour
                    # une réponse valide au run suivant
                    tmp = cache_file.with_suffix(".tmp")
                    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                    tmp.replace(cache_file)
                except OSError:
                    pass  # cache best-effort : jamais bloquant
        for way in parse_ways(payload):
            if way["id"] not in seen:
                seen.add(way["id"])
                ways.append(way)
    return ways, {"requests": requests, "cache_hits": hits, "chunks": len(boxes)}


# ---------------------------------------------------------------------------
# Appariement au plus proche chemin
# ---------------------------------------------------------------------------

def _point_segment_m(plat, plon, alat, alon, blat, blon) -> float:
    """Distance (m) point -> segment [A, B], projection locale équirectangulaire (valable à ~100 m)."""
    kx = 111_320.0 * math.cos(math.radians(plat))
    ky = 110_540.0
    ax, ay = (alon - plon) * kx, (alat - plat) * ky
    bx, by = (blon - plon) * kx, (blat - plat) * ky
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    t = 0.0 if den == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / den))
    return math.hypot(ax + t * dx, ay + t * dy)


# Index spatial : grille de cellules de `GRID_DEG` degrés -> segments de chemins qui la touchent.
# Sans index, chaque point de trace parcourt TOUS les chemins (un ultra = des milliers de points ×
# des milliers de chemins : plusieurs minutes) ; avec, seuls les segments des cellules voisines.
GRID_DEG = 0.002  # ~220 m en latitude, toujours > MATCH_RADIUS_M


def build_index(ways: Sequence[dict]) -> Dict[Tuple[int, int], List[tuple]]:
    """Grille `(i, j) -> [(rang du chemin, chemin, A, B), ...]` ; le rang départage les égalités de
    distance exactement comme un parcours de la liste (le dernier chemin à égalité l'emporte)."""
    grid: Dict[Tuple[int, int], List[tuple]] = {}
    for rank, way in enumerate(ways):
        g = way["geom"]
        for a, b in zip(g, g[1:]):
            i0, i1 = sorted((math.floor(a[0] / GRID_DEG), math.floor(b[0] / GRID_DEG)))
            j0, j1 = sorted((math.floor(a[1] / GRID_DEG), math.floor(b[1] / GRID_DEG)))
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    grid.setdefault((i, j), []).append((rank, way, a, b))
    return grid


def nearest_way(lat: float, lon: float, ways: Sequence[dict], radius_m: float = MATCH_RADIUS_M,
                index: Optional[dict] = None) -> Optional[dict]:
    """Chemin le plus proche du point à moins de `radius_m` (ou `None`). `index` (de `build_index`)
    évite le parcours exhaustif ; même résultat avec ou sans."""
    grid = index if index is not None else build_index(ways)
    # cellules voisines couvrant le rayon (en longitude, la cellule est plus étroite en mètres)
    di = int(math.ceil(radius_m / (111_320.0 * GRID_DEG)))
    dj = int(math.ceil(radius_m / (111_320.0 * max(0.01, math.cos(math.radians(lat))) * GRID_DEG)))
    ci, cj = math.floor(lat / GRID_DEG), math.floor(lon / GRID_DEG)
    best, best_key = None, (radius_m, -1)
    for i in range(ci - di, ci + di + 1):
        for j in range(cj - dj, cj + dj + 1):
            for rank, way, a, b in grid.get((i, j), ()):
                d = _point_segment_m(lat, lon, a[0], a[1], b[0], b[1])
                if d < best_key[0] or (d == best_key[0] and rank > best_key[1]):
                    best, best_key = way, (d, rank)
    return best


def osm_for_segment(samples: Sequence[dict], ways: Sequence[dict], km_start: float, km_end: float,
                     index: Optional[dict] = None) -> Optional[dict]:
    """Coefficient dérivé d'OSM pour la section `[km_start, km_end]` (km de la trace) : moyenne,
    pondérée par la distance, des coefficients des points appariés ; `None` si la part appariée
    est sous `MIN_OSM_COVERAGE`. Rend `{coef, coverage, tags}`."""
    inside = [s for s in samples if km_start * 1000.0 <= s["d_m"] <= km_end * 1000.0 + 1e-6]
    if not inside:
        return None
    if index is None:
        index = build_index(ways)
    total_w = matched_w = acc = 0.0
    tag_w: Dict[str, float] = {}
    for i, s in enumerate(inside):
        lo = inside[i - 1]["d_m"] if i else s["d_m"]
        hi = inside[i + 1]["d_m"] if i + 1 < len(inside) else s["d_m"]
        w = max(1.0, (hi - lo) / 2.0) if len(inside) > 1 else 1.0
        total_w += w
        way = nearest_way(s["lat"], s["lon"], ways, index=index)
        if way is None:
            continue
        coef, used = coef_from_tags(way["tags"])
        matched_w += w
        acc += w * coef
        for label in used:
            tag_w[label] = tag_w.get(label, 0.0) + w
    if total_w <= 0 or matched_w / total_w < MIN_OSM_COVERAGE:
        return None
    top = sorted(tag_w.items(), key=lambda kv: -kv[1])[:3]
    return {"coef": acc / matched_w, "coverage": matched_w / total_w, "tags": [t for t, _w in top]}


# ---------------------------------------------------------------------------
# Coefficient par section (déclaré > OSM > aucun)
# ---------------------------------------------------------------------------

def section_coefficients(segments: Sequence[dict], pts: Sequence[dict], *,
                          declared: Optional[Sequence[dict]] = None,
                          ways: Optional[Sequence[dict]] = None,
                          osm_baseline: float = 1.0) -> List[dict]:
    """Un dict par segment : `{coef, effective_factor, source, tags, coverage_pct?, osm_coef?}` avec
    `source` in `declared | osm | none`. `none` = coefficient 1.0 (rien d'inventé). Un coefficient
    OSM est rapporté au terrain habituel (`osm_baseline`, voir `rebase`) ; la valeur absolue tirée
    des tags reste dans `osm_coef` quand la référence n'est pas 1.0. Une déclaration est déjà
    relative (1.0 = comme à l'entraînement) : jamais rebasée."""
    samples = sample_track(pts) if ways else []
    index = build_index(ways) if ways else None
    out = []
    for seg in segments:
        k0, k1 = seg["km_start"], seg["km_end"]
        entry = {"coef": 1.0, "source": "none", "tags": []}
        dec = declared_for_segment(declared, k0, k1) if declared else None
        if dec is not None and dec[1] >= MIN_DECLARED_COVERAGE:
            entry = {"coef": dec[0], "source": "declared", "tags": dec[2], "coverage_pct": round(dec[1] * 100, 1)}
        elif ways:
            osm = osm_for_segment(samples, ways, k0, k1, index=index)
            if osm is not None:
                entry = {"coef": rebase(osm["coef"], osm_baseline), "source": "osm", "tags": osm["tags"],
                         "coverage_pct": round(osm["coverage"] * 100, 1)}
                if abs(osm_baseline - 1.0) > 1e-12:
                    entry["osm_coef"] = round(osm["coef"], 3)
        entry["coef"] = round(entry["coef"], 3)
        entry["effective_factor"] = round(effective_factor(entry["coef"], seg.get("grade_mean_pct")), 4)
        out.append(entry)
    return out


def apply_to_segments(segments: Sequence[dict], coefs: Sequence[dict], scenarios: Sequence[str],
                       round_s: int) -> List[dict]:
    """Multiplie temps et allures de CHAQUE scénario par le même `effective_factor` de la section
    (l'ordre prudent >= réaliste >= ambitieux est donc préservé par construction : un même facteur
    positif sur trois temps ordonnés). Une section sans coefficient (`source = "none"`) reste
    inchangée mais porte tout de même son objet `technicity` (elle dit pourquoi)."""
    out = []
    for seg, c in zip(segments, coefs):
        f = c["effective_factor"]
        new_seg = {**seg, "technicity": dict(c)}
        if c["source"] != "none" and abs(f - 1.0) > 1e-12:
            new_seg["predicted_time_s"] = {
                s: (None if seg["predicted_time_s"][s] is None
                    else int(round(seg["predicted_time_s"][s] * f / round_s)) * round_s) for s in scenarios}
            new_seg["pace_s_km"] = {
                s: (None if seg["pace_s_km"][s] is None else round(seg["pace_s_km"][s] * f, 1))
                for s in scenarios}
        out.append(new_seg)
    return out


def summarize(segments: Sequence[dict], coefs: Sequence[dict]) -> dict:
    """Résumé niveau plan : répartition par source et coefficient moyen pondéré par la distance."""
    dist = {"declared": 0.0, "osm": 0.0, "none": 0.0}
    acc = total = 0.0
    for seg, c in zip(segments, coefs):
        d = seg.get("distance_m") or 0.0
        dist[c["source"]] += d
        acc += d * c["coef"]
        total += d
    pct = {k: (round(100.0 * v / total, 1) if total else 0.0) for k, v in dist.items()}
    return {"distance_pct_by_source": pct,
            "mean_coef": round(acc / total, 3) if total else None,
            "max_coef": max((c["coef"] for c in coefs), default=None)}
