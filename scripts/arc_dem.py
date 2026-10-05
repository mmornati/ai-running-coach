#!/usr/bin/env python3
"""Correction altimétrique par modèle numérique de terrain (MNT) — #176.

Rééchantillonne l'altitude d'une trace (GPX de parcours, ou séance FIT en opt-in)
sur un MNT public :

- **France métropolitaine** : API d'altimétrie de la Géoplateforme de l'IGN
  (`https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json`, ressource
  `ign_rge_alti_wld`, RGE ALTI® au pas de 1 m là où il est disponible, Licence Ouverte
  Etalab 2.0, sans clé, 5 requêtes/s par IP) ;
- **ailleurs** (et repli quand l'IGN ne couvre pas un point, `z = -99999`) :
  Open-Meteo Elevation API (`https://api.open-meteo.com/v1/elevation`, Copernicus
  DEM GLO-90 au pas de 90 m, 100 coordonnées par requête, attribution obligatoire).

Stdlib uniquement (`urllib`), **aucun appel réseau à l'import** : tout le réseau passe
par `http_get`, injectable (les tests, palier D, l'ont remplacé par un stub — jamais de
réseau en test). Fonctions pures pour tout le reste (amincissement, découpage en lots,
routage par zone, interpolation, comparaison de D+).

## Vie privée

Seules des **coordonnées** (latitude/longitude arrondies) partent vers le fournisseur
— jamais d'identifiant, de date, de fréquence cardiaque ni de nom de fichier ; la trace
est amincie (un point tous les `step_m`). Une trace de séance personnelle révèle
l'adresse de l'athlète : elle n'est donc interrogée qu'avec `[privacy].dem_for_activities
= true`, et son début/sa fin (`[privacy].dem_trim_m`, 500 m par défaut) ne sont jamais
envoyés — une protection PARTIELLE seulement (la trace restante passe souvent encore près
du domicile). Voir
`docs/elevation.md` et `ASSUMPTIONS["privacy"]`.

## Hors ligne

Toute indisponibilité (réseau, quota, couverture insuffisante) rend `status =
"unavailable"` avec un message explicite et laisse la trace INCHANGÉE : le comportement
antérieur (altitude du fichier) reste le repli, jamais une valeur inventée.

Usage (CLI, pour contrôle manuel) :
    python3 scripts/arc_dem.py settings --workspace <ws>
    python3 scripts/arc_dem.py route <lat> <lon>
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arc_elevation as EL  # noqa: E402

IGN_URL = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"
IGN_RESOURCE = "ign_rge_alti_wld"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/elevation"
USER_AGENT = "ai-running-coach/arc_dem (+https://github.com/mmornati/ai-running-coach)"

# Boîte englobante APPROCHÉE de la France métropolitaine (Corse incluse) : elle déborde sur
# les pays voisins, c'est voulu — l'IGN rend `-99999` hors de sa couverture et le point est
# alors redemandé à Open-Meteo (`NO_DATA_Z`).
FRANCE_BBOX = {"lat_min": 41.2, "lat_max": 51.2, "lon_min": -5.5, "lon_max": 9.8}
NO_DATA_Z = -99999.0

# Taille des lots : Open-Meteo documente 100 coordonnées par appel ; l'IGN en accepte 5000,
# mais la requête est un GET (URL) : 200 points restent très en deçà de toute limite d'URL.
BATCH_SIZE = {"ign": 200, "open-meteo": 100}
# Pause minimale entre deux appels réseau d'un même fournisseur (IGN : 5 req/s/IP documentés).
MIN_INTERVAL_S = {"ign": 0.25, "open-meteo": 0.25}
# Décimales conservées par coordonnée (clé de cache ET coordonnée envoyée) : 5 ≈ 1,1 m,
# adapté au MNT de 1 m ; 4 ≈ 11 m, largement sous les 90 m de GLO-90.
COORD_DECIMALS = {"ign": 5, "open-meteo": 4}

DEFAULT_STEP_M = 50.0
DEFAULT_MAX_POINTS = 3000
# Début/fin de trace jamais envoyés pour une séance personnelle (domicile) : défaut et
# bornes de `[privacy].dem_trim_m`. Protection PARTIELLE (voir ASSUMPTIONS["privacy"]) : le
# plancher de 200 m empêche seulement de l'affaiblir davantage par configuration.
PRIVACY_TRIM_M = 500.0
PRIVACY_TRIM_BOUNDS_M = (200.0, 5000.0)
# Part minimale de nœuds résolus pour accepter la correction d'une trace.
MIN_COVERAGE = 0.8
RETRIES = 3
BACKOFF_S = 1.0
TIMEOUT_S = 20.0

ATTRIBUTION = {
    "ign": "Altitudes : IGN — RGE ALTI® via la Géoplateforme (Licence Ouverte Etalab 2.0).",
    "open-meteo": "Altitudes : Copernicus DEM GLO-90 (ESA, DOI 10.5270/ESA-c5d3d65) via Open-Meteo.com.",
}

SETTINGS_DEFAULTS = {"dem": "off", "step_m": DEFAULT_STEP_M, "cache": True, "activities": False,
                     "activity_trim_m": PRIVACY_TRIM_M}

ASSUMPTIONS = {
    "resolution": (
        "Le MNT donne l'altitude du TERRAIN (sol nu), pas celle du capteur : RGE ALTI® a un pas de "
        "1 m en France (précision verticale très variable selon la source de mesure — l'API "
        "renvoie elle-même « Variable suivant la source de mesure »), Copernicus GLO-90 un pas de "
        "90 m (altitudes entières rendues par Open-Meteo, MNT de surface : cime des arbres et "
        "toits peuvent y entrer, erreur verticale de l'ordre de quelques mètres, pire en relief "
        "abrupt). Une crête étroite ou un fond de gorge plus fins que la maille sont lissés."
    ),
    "horizontal_error": (
        "Une erreur horizontale du GPS de 5 à 10 m décale le point dans la maille : sur une pente "
        "raide (30 %) elle vaut 1,5 à 3 m d'altitude avec un MNT à 1 m. Le D+ MNT n'ayant pas de "
        "seuil, ce décalage peut le SURESTIMER sur une traversée à flanc de pente (sentier en "
        "balcon, lacets) : simulation du projet (relecture #176, 10 km, nœuds à 50 m, 500 m de vrai "
        "D+) — erreur GPS corrélée sur ~200 m (cas habituel), σ = 5 m, dévers 30 % : +0 à +1 % ; "
        "dévers 60 % ou σ = 10 m : environ +4 % ; erreur NON corrélée d'un nœud à l'autre (pire "
        "cas, trace très bruitée) : +5 à +30 %. Une trace amincie à `step_m` limite ce bruit "
        "cumulé, sans l'annuler ; un seuil anti-bruit n'y change presque rien (+20 % restants à "
        "3 m de seuil dans le pire cas) et coûterait les vraies petites bosses."
    ),
    "gain_reference": (
        "Pour un parcours de COURSE (GPX publié), le D+ MNT est la référence du plan "
        "(`arc_race_pacing`) et de l'évaluation de parcours, affiché à côté du D+ du fichier. Pour "
        "une SÉANCE, il n'est que proposé : un baromètre récent est souvent meilleur sur un FIT, "
        "et les tunnels, ponts, galeries ne figurent pas dans un MNT — l'altitude enregistrée "
        "n'est jamais remplacée (`dem-check` compare, rien d'autre)."
    ),
    "thinning": (
        "La trace est amincie (un nœud tous les `step_m`, 50 m par défaut, plafonné à "
        f"{DEFAULT_MAX_POINTS} nœuds en agrandissant le pas) puis l'altitude est interpolée "
        "linéairement ENTRE les nœuds par distance cumulée : une ondulation plus courte que le pas "
        "n'est pas comptée (voir `arc_elevation.ASSUMPTIONS['dem_series']`) : l'interpolation "
        "linéaire entre altitudes vraies ne peut que SOUS-estimer le D+ du terrain — simulation du "
        "projet (relecture #176) : ondulations de 300 m de long et plus, écart < 2,5 % ; bosses de "
        "3 m tous les 100 m, -24 % au pas de 50 m. Le pas réel s'élargit au-delà de 150 km "
        f"({DEFAULT_MAX_POINTS} nœuds au plus). Une trace qui passe d'un fournisseur à l'autre "
        "(frontière, trou de couverture IGN) peut montrer une marche de quelques mètres à la "
        "transition (MNT de terrain contre MNT de surface)."
    ),
    "privacy": (
        "Seules des coordonnées arrondies (5 décimales IGN, 4 Open-Meteo) sont envoyées, par lots, "
        "à data.geopf.fr (IGN, France) ou api.open-meteo.com (ailleurs) — l'adresse IP de la "
        "machine est évidemment visible du fournisseur. Les GPX de course (itinéraires publics) "
        "peuvent être interrogés sur demande (`--dem`) ou avec `[elevation].dem = \"auto\"` ; les "
        "traces de séances ne le sont qu'avec `[privacy].dem_for_activities = true`, début et fin "
        f"exclus (`[privacy].dem_trim_m`, {PRIVACY_TRIM_M:.0f} m par défaut, "
        f"{PRIVACY_TRIM_BOUNDS_M[0]:.0f} à {PRIVACY_TRIM_BOUNDS_M[1]:.0f} m). Ce rognage est une "
        "protection PARTIELLE : une sortie qui part de chez soi suit ensuite sa rue et son "
        "quartier, et plusieurs séances superposées désignent le même point de départ à quelques "
        "centaines de mètres près ; il ne masque pas non plus un lieu fréquent au milieu de la "
        "trace (travail, club). Aucun envoi par défaut."
    ),
    "cache": (
        "Chaque altitude obtenue est mémorisée localement (`<workspace>/.arc/dem-cache.json`, "
        "gitignoré, jamais dans le dépôt) par fournisseur et coordonnée arrondie : un parcours "
        "déjà analysé ne refait aucun appel. Le MNT bouge très rarement ; le cache n'expire pas "
        "(supprimer le fichier pour le vider, `[elevation].cache = false` pour l'ignorer)."
    ),
    "rate_limits": (
        "IGN : 5 requêtes par seconde par adresse IP, 5000 points par requête (documentation de "
        "la Géoplateforme) — le module espace ses appels de 0,25 s. Open-Meteo : 100 coordonnées "
        "par requête (au-delà, HTTP 400) ; l'API GRATUITE est réservée à un usage NON COMMERCIAL "
        "(conditions d'utilisation d'Open-Meteo : moins de 10 000 appels par jour, 5 000 par heure, "
        "600 par minute ; données sous CC BY 4.0) — un usage commercial exige un abonnement "
        "Open-Meteo (clé d'API), que ce module ne gère pas. Un parcours de 3000 nœuds coûte 30 "
        "appels. En cas de HTTP 429/5xx, `RETRIES` essais avec attente exponentielle puis repli "
        "hors ligne."
    ),
}


class DemError(RuntimeError):
    """Erreur explicite du service d'altimétrie (réseau, quota, réponse inattendue)."""


# ---------------------------------------------------------------------------
# Fonctions pures
# ---------------------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux points GPS."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def cumulative_distances(pts: Sequence[dict]) -> List[float]:
    dist = [0.0]
    for i in range(1, len(pts)):
        dist.append(dist[-1] + haversine(pts[i - 1]["lat"], pts[i - 1]["lon"], pts[i]["lat"], pts[i]["lon"]))
    return dist


def provider_for(lat: float, lon: float) -> str:
    """`"ign"` pour un point dans la boîte englobante de la France métropolitaine, sinon
    `"open-meteo"`."""
    b = FRANCE_BBOX
    if b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]:
        return "ign"
    return "open-meteo"


def effective_step_m(total_m: float, step_m: float = DEFAULT_STEP_M, max_points: int = DEFAULT_MAX_POINTS) -> float:
    """Pas d'amincissement réel : `step_m`, agrandi si la trace dépasserait `max_points` nœuds."""
    step = max(float(step_m), 1.0)
    if total_m > 0 and total_m / step > max_points - 1:
        step = total_m / (max_points - 1)
    return step


def thin_indices(dist: Sequence[float], step_m: float = DEFAULT_STEP_M,
                 max_points: int = DEFAULT_MAX_POINTS) -> List[int]:
    """Indices des nœuds conservés : le premier, puis chaque point qui s'écarte d'au moins
    `effective_step_m` du dernier conservé, et le dernier point (toujours)."""
    n = len(dist)
    if n == 0:
        return []
    step = effective_step_m(dist[-1] - dist[0], step_m, max_points)
    keep = [0]
    last = dist[0]
    for i in range(1, n - 1):
        if dist[i] - last >= step:
            keep.append(i)
            last = dist[i]
    if n > 1:
        keep.append(n - 1)
    return keep


def chunked(seq: Sequence, size: int) -> List[list]:
    """Lots consécutifs de `size` éléments au plus."""
    if size < 1:
        raise ValueError("size doit être >= 1")
    return [list(seq[i:i + size]) for i in range(0, len(seq), size)]


def round_coord(provider: str, lat: float, lon: float) -> Tuple[float, float]:
    d = COORD_DECIMALS[provider]
    return round(lat, d), round(lon, d)


def cache_key(provider: str, lat: float, lon: float) -> str:
    rlat, rlon = round_coord(provider, lat, lon)
    d = COORD_DECIMALS[provider]
    return f"{provider}:{rlat:.{d}f},{rlon:.{d}f}"


def interpolate_by_distance(node_d: Sequence[float], node_z: Sequence[float],
                            dists: Sequence[float]) -> List[float]:
    """Altitude interpolée linéairement en chaque distance de `dists`, à partir de nœuds
    `(node_d, node_z)` triés ; hors bornes, la valeur du nœud extrême."""
    out: List[float] = []
    for d in dists:
        j = bisect.bisect_left(node_d, d)
        if j <= 0:
            out.append(node_z[0])
        elif j >= len(node_d):
            out.append(node_z[-1])
        else:
            d0, d1 = node_d[j - 1], node_d[j]
            z0, z1 = node_z[j - 1], node_z[j]
            out.append(z0 if d1 == d0 else z0 + (z1 - z0) * (d - d0) / (d1 - d0))
    return out


def compare_gain_loss(file_ele: Sequence[Optional[float]], dem_ele: Sequence[Optional[float]],
                      *, file_smooth: int = 3, file_min_step_m: float = 1.0) -> dict:
    """D+/D- du fichier (même méthode que `analyze_gpx.compute_metrics` : lissage + seuil de
    1 m) et du MNT (sans lissage ni seuil, `arc_elevation.ASSUMPTIONS["dem_series"]`), avec
    l'écart absolu et relatif. `delta_pct` vaut `None` si le D+ du fichier est nul."""
    fg, fl = EL.gain_loss(file_ele, smooth_taps=file_smooth, min_step_m=file_min_step_m)
    dg, dl = EL.gain_loss(dem_ele)
    return {
        "file_gain_m": round(fg, 1), "dem_gain_m": round(dg, 1),
        "file_loss_m": round(fl, 1), "dem_loss_m": round(dl, 1),
        "delta_gain_m": round(dg - fg, 1),
        "delta_gain_pct": round((dg - fg) / fg * 100.0, 1) if fg > 0 else None,
    }


# ---------------------------------------------------------------------------
# Réglages
# ---------------------------------------------------------------------------

def load_settings(workspace: Optional[Path], *, warn: Callable[[str], None] = None) -> dict:
    """Réglages `[elevation]` / `[privacy]` (workspace.toml puis workspace.user.toml, clé par
    clé). Valeur invalide : défaut + avertissement, jamais d'exception. Défauts prudents :
    `dem = "off"`, `dem_for_activities = false`."""
    warn = warn or (lambda m: print(f"AVERTISSEMENT : {m}", file=sys.stderr))
    out = dict(SETTINGS_DEFAULTS)
    if workspace is None:
        return out
    try:
        from coach_config import read_toml
        merged: Dict[str, dict] = {}
        for path in (Path(workspace) / "config/workspace.toml", Path(workspace) / "config/workspace.user.toml"):
            for section, values in read_toml(path).items():
                if isinstance(values, dict):
                    merged.setdefault(section, {}).update(values)
    except Exception as exc:  # TOML illisible : défauts prudents
        warn(f"configuration illisible ({exc}) — correction MNT désactivée.")
        return out
    elev, priv = merged.get("elevation", {}), merged.get("privacy", {})
    mode = elev.get("dem", out["dem"])
    if mode in ("off", "auto"):
        out["dem"] = mode
    else:
        warn(f"[elevation].dem = {mode!r} invalide (attendu \"off\" ou \"auto\") — « off » retenu.")
    step = elev.get("step_m", out["step_m"])
    if isinstance(step, (int, float)) and not isinstance(step, bool) and 5 <= step <= 500:
        out["step_m"] = float(step)
    else:
        warn(f"[elevation].step_m = {step!r} invalide (5 à 500 m) — {DEFAULT_STEP_M:.0f} m retenu.")
    trim = priv.get("dem_trim_m", out["activity_trim_m"])
    lo, hi = PRIVACY_TRIM_BOUNDS_M
    if isinstance(trim, (int, float)) and not isinstance(trim, bool) and lo <= trim <= hi:
        out["activity_trim_m"] = float(trim)
    else:
        warn(f"[privacy].dem_trim_m = {trim!r} invalide ({lo:.0f} à {hi:.0f} m) — "
             f"{PRIVACY_TRIM_M:.0f} m retenu.")
    for key, section, name in (("cache", elev, "[elevation].cache"),
                               ("activities", priv, "[privacy].dem_for_activities")):
        raw = section.get("cache" if key == "cache" else "dem_for_activities", out[key])
        if isinstance(raw, bool):
            out[key] = raw
        else:
            warn(f"{name} = {raw!r} invalide (booléen attendu) — {str(out[key]).lower()} retenu.")
    return out


def cache_path(workspace: Optional[Path]) -> Optional[Path]:
    """`<workspace>/.arc/dem-cache.json` (jamais dans le dépôt : `/.arc/` est gitignoré) ;
    à défaut de workspace, `ARC_DEM_CACHE`, sinon `~/.cache/ai-running-coach/dem-cache.json`."""
    env = os.environ.get("ARC_DEM_CACHE")
    if env:
        return Path(env).expanduser()
    if workspace is not None:
        return Path(workspace) / ".arc" / "dem-cache.json"
    return Path.home() / ".cache" / "ai-running-coach" / "dem-cache.json"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class DemCache:
    """Cache JSON `{clé: altitude | null}` ; `null` = « le fournisseur n'a pas de donnée ici »
    (évite de redemander un point hors couverture). `path=None` : cache en mémoire seulement."""

    def __init__(self, path: Optional[Path] = None, *, enabled: bool = True):
        self.path = Path(path) if path else None
        self.enabled = enabled
        self.data: Dict[str, Optional[float]] = {}
        self.dirty = False
        if enabled and self.path and self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data = {k: v for k, v in raw.items() if v is None or isinstance(v, (int, float))}
            except (OSError, ValueError):
                self.data = {}  # cache corrompu : reconstruit, jamais bloquant

    def has(self, key: str) -> bool:
        return self.enabled and key in self.data

    def get(self, key: str) -> Optional[float]:
        return self.data.get(key) if self.enabled else None

    def set(self, key: str, value: Optional[float]) -> None:
        if self.enabled:
            self.data[key] = value
            self.dirty = True

    def save(self) -> None:
        if not (self.enabled and self.dirty and self.path):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".arc-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, separators=(",", ":"))
            os.replace(tmp, self.path)
            self.dirty = False
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


# ---------------------------------------------------------------------------
# Réseau (injectable)
# ---------------------------------------------------------------------------

def default_http_get(url: str, timeout: float = TIMEOUT_S) -> dict:
    """GET JSON via `urllib`. Lève `urllib.error.HTTPError`/`URLError`/`TimeoutError`/`ValueError`."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — https, hôtes fixes
        return json.loads(resp.read().decode("utf-8"))


def _call_with_retries(url: str, http_get: Callable[[str], dict], sleep: Callable[[float], None],
                       stats: dict) -> dict:
    last: Optional[BaseException] = None
    for attempt in range(RETRIES):
        stats["network_calls"] += 1
        try:
            return http_get(url)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code != 429 and exc.code < 500:
                break  # 4xx hors quota : inutile de réessayer
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
        if attempt < RETRIES - 1:
            sleep(BACKOFF_S * (2 ** attempt))
    raise DemError(f"service d'altimétrie indisponible ({type(last).__name__}: {last})")


def _fmt(values: Sequence[float], decimals: int) -> str:
    return ",".join(f"{v:.{decimals}f}" for v in values)


def ign_url(coords: Sequence[Tuple[float, float]]) -> str:
    d = COORD_DECIMALS["ign"]
    lon = "|".join(f"{c[1]:.{d}f}" for c in coords)
    lat = "|".join(f"{c[0]:.{d}f}" for c in coords)
    q = urllib.parse.urlencode({"lon": lon, "lat": lat, "resource": IGN_RESOURCE,
                                "delimiter": "|", "zonly": "true"}, safe="|")
    return f"{IGN_URL}?{q}"


def open_meteo_url(coords: Sequence[Tuple[float, float]]) -> str:
    d = COORD_DECIMALS["open-meteo"]
    q = urllib.parse.urlencode({"latitude": _fmt([c[0] for c in coords], d),
                                "longitude": _fmt([c[1] for c in coords], d)}, safe=",")
    return f"{OPEN_METEO_URL}?{q}"


def parse_ign(payload: dict, expected: int) -> List[Optional[float]]:
    z = payload.get("elevations") if isinstance(payload, dict) else None
    if not isinstance(z, list) or len(z) != expected:
        raise DemError("réponse IGN inattendue (clé « elevations » absente ou de mauvaise taille)")
    out: List[Optional[float]] = []
    for item in z:
        v = item.get("z") if isinstance(item, dict) else item  # zonly=true : liste de nombres
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= NO_DATA_Z + 1:
            out.append(None)
        else:
            out.append(float(v))
    return out


def parse_open_meteo(payload: dict, expected: int) -> List[Optional[float]]:
    z = payload.get("elevation") if isinstance(payload, dict) else None
    if not isinstance(z, list) or len(z) != expected:
        raise DemError("réponse Open-Meteo inattendue (clé « elevation » absente ou de mauvaise taille)")
    return [float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None for v in z]


_BUILDERS = {"ign": (ign_url, parse_ign), "open-meteo": (open_meteo_url, parse_open_meteo)}


class _Throttle:
    def __init__(self, sleep: Callable[[float], None], clock: Callable[[], float] = time.monotonic):
        self.sleep, self.clock, self.last = sleep, clock, {}

    def wait(self, provider: str) -> None:
        prev = self.last.get(provider)
        if prev is not None:
            delta = MIN_INTERVAL_S[provider] - (self.clock() - prev)
            if delta > 0:
                self.sleep(delta)
        self.last[provider] = self.clock()


def lookup(points: Sequence[Tuple[float, float]], *, cache: Optional[DemCache] = None,
           http_get: Optional[Callable[[str], dict]] = None,
           sleep: Callable[[float], None] = time.sleep, stats: Optional[dict] = None
           ) -> List[Tuple[Optional[float], Optional[str]]]:
    """`(altitude, fournisseur)` pour chaque `(lat, lon)` : cache d'abord, puis lots par
    fournisseur (IGN en France, Open-Meteo ailleurs et pour les points que l'IGN ne couvre pas).
    Les coordonnées identiques après arrondi ne sont demandées qu'une fois. Lève `DemError` si
    un lot échoue après les essais."""
    cache = cache or DemCache(None)
    http_get = http_get or default_http_get
    stats = stats if stats is not None else {}
    for k in ("network_calls", "cache_hits", "coords_sent"):
        stats.setdefault(k, 0)
    throttle = _Throttle(sleep)
    resolved: Dict[Tuple[int, str], Optional[float]] = {}  # (index du point, fournisseur) -> altitude
    result: List[Tuple[Optional[float], Optional[str]]] = [(None, None)] * len(points)

    def fetch(provider: str, idxs: List[int]) -> None:
        """Résout `idxs` (indices de `points`) chez `provider` ; remplit `resolved`."""
        todo: Dict[str, List[int]] = {}
        for i in idxs:
            key = cache_key(provider, *points[i])
            if cache.has(key):
                resolved[(i, provider)] = cache.get(key)
                stats["cache_hits"] += 1
            else:
                todo.setdefault(key, []).append(i)
        keys = list(todo)
        build, parse = _BUILDERS[provider]
        for batch in chunked(keys, BATCH_SIZE[provider]):
            coords = [round_coord(provider, *points[todo[k][0]]) for k in batch]
            throttle.wait(provider)
            payload = _call_with_retries(build(coords), http_get, sleep, stats)
            stats["coords_sent"] += len(coords)
            for k, z in zip(batch, parse(payload, len(coords))):
                cache.set(k, z)
                for i in todo[k]:
                    resolved[(i, provider)] = z

    first: Dict[str, List[int]] = {"ign": [], "open-meteo": []}
    for i, (lat, lon) in enumerate(points):
        first[provider_for(lat, lon)].append(i)
    try:
        fetch("ign", first["ign"])
        # Points français sans donnée IGN (bord de couverture) -> Open-Meteo.
        fallback = [i for i in first["ign"] if resolved.get((i, "ign")) is None]
        fetch("open-meteo", first["open-meteo"] + fallback)
    finally:
        cache.save()
    for i in first["ign"]:
        z = resolved.get((i, "ign"))
        result[i] = (z, "ign") if z is not None else (resolved.get((i, "open-meteo")),
                                                      "open-meteo" if resolved.get((i, "open-meteo")) is not None else None)
    for i in first["open-meteo"]:
        z = resolved.get((i, "open-meteo"))
        result[i] = (z, "open-meteo" if z is not None else None)
    return result


# ---------------------------------------------------------------------------
# Rééchantillonnage d'une trace
# ---------------------------------------------------------------------------

def resample_track(pts: Sequence[dict], *, step_m: float = DEFAULT_STEP_M,
                   max_points: int = DEFAULT_MAX_POINTS, cache: Optional[DemCache] = None,
                   http_get: Optional[Callable[[str], dict]] = None,
                   sleep: Callable[[float], None] = time.sleep, strict: bool = False) -> dict:
    """Altitude MNT d'une trace `[{lat, lon, ele?}, ...]`.

    Rend `{"status", "ele", "report"}` : `ele` = altitude MNT par point (interpolée entre les
    nœuds amincis), même longueur que `pts` ; `status` = `"ok"` | `"partial"` (nœuds sans
    donnée ignorés, couverture >= `MIN_COVERAGE`) | `"unavailable"` (`ele` = `None`, `report`
    porte `error`). Les points de `pts` ne sont jamais modifiés. `strict=True` lève `DemError`
    au lieu de rendre `"unavailable"`."""
    stats: dict = {"network_calls": 0, "cache_hits": 0, "coords_sent": 0}
    report: dict = {"step_m": None, "nodes": 0, "providers": {}, "attribution": [], **stats}

    def unavailable(msg: str) -> dict:
        if strict:
            raise DemError(msg)
        return {"status": "unavailable", "ele": None, "report": {**report, **stats, "error": msg}}

    if len(pts) < 2:
        return unavailable("trace trop courte (moins de 2 points)")
    dist = cumulative_distances(pts)
    idx = thin_indices(dist, step_m, max_points)
    report["step_m"] = round(effective_step_m(dist[-1], step_m, max_points), 1)
    report["nodes"] = len(idx)
    try:
        found = lookup([(pts[i]["lat"], pts[i]["lon"]) for i in idx], cache=cache,
                       http_get=http_get, sleep=sleep, stats=stats)
    except DemError as exc:
        return unavailable(str(exc))
    nodes = [(dist[i], z, prov) for i, (z, prov) in zip(idx, found) if z is not None]
    coverage = len(nodes) / len(idx)
    report.update(stats)
    report["coverage_pct"] = round(coverage * 100.0, 1)
    if len(nodes) < 2 or coverage < MIN_COVERAGE:
        return unavailable(f"couverture MNT insuffisante ({coverage * 100:.0f} % des nœuds)")
    providers: Dict[str, int] = {}
    for _, _, prov in nodes:
        providers[prov] = providers.get(prov, 0) + 1
    report["providers"] = providers
    report["attribution"] = [ATTRIBUTION[p] for p in ("ign", "open-meteo") if p in providers]
    ele = interpolate_by_distance([n[0] for n in nodes], [n[1] for n in nodes], dist)
    return {"status": "ok" if len(nodes) == len(idx) else "partial",
            "ele": [round(v, 2) for v in ele], "report": report}


def trim_for_privacy(pts: Sequence[dict], trim_m: float = PRIVACY_TRIM_M) -> Tuple[int, int]:
    """Bornes `[lo, hi)` des indices conservés après suppression des `trim_m` premiers et
    derniers mètres (adresse de l'athlète). Rend `(0, 0)` si la trace est trop courte."""
    if len(pts) < 2:
        return 0, 0
    dist = cumulative_distances(pts)
    total = dist[-1]
    if total <= 3 * trim_m:
        return 0, 0
    lo = next(i for i, d in enumerate(dist) if d >= trim_m)
    hi = max(i for i, d in enumerate(dist) if d <= total - trim_m) + 1
    return lo, hi


def activity_check(samples: Sequence[dict], *, step_m: float = 100.0, cache: Optional[DemCache] = None,
                   http_get: Optional[Callable[[str], dict]] = None,
                   sleep: Callable[[float], None] = time.sleep, trim_m: float = PRIVACY_TRIM_M) -> dict:
    """Compare l'altitude enregistrée d'une séance (échantillons `lat_deg`/`lon_deg`/
    `altitude_m`) au MNT — **lecture seule**, l'altitude enregistrée n'est jamais remplacée.
    L'appelant a déjà vérifié l'opt-in `[privacy].dem_for_activities`. Début et fin de trace
    (`trim_m`, `[privacy].dem_trim_m`) ne sont ni envoyés ni comparés. Rend `{"status", "reason"?, ...}`."""
    gps = [s for s in samples if s.get("lat_deg") is not None and s.get("lon_deg") is not None]
    if len(gps) < 2:
        return {"status": "no_gps", "reason": "aucune coordonnée GPS exploitable dans les échantillons"}
    pts = [{"lat": s["lat_deg"], "lon": s["lon_deg"], "ele": s.get("altitude_m")} for s in gps]
    trim_m = max(float(trim_m), PRIVACY_TRIM_BOUNDS_M[0])  # jamais en deçà du plancher
    lo, hi = trim_for_privacy(pts, trim_m)
    if hi - lo < 2:
        return {"status": "too_short",
                "reason": f"trace trop courte une fois les {trim_m:.0f} premiers/derniers mètres "
                          "retirés (vie privée)"}
    core = pts[lo:hi]
    res = resample_track(core, step_m=step_m, cache=cache, http_get=http_get, sleep=sleep)
    if res["status"] == "unavailable":
        return {"status": "unavailable", "reason": res["report"].get("error"), "report": res["report"]}
    recorded = [p["ele"] for p in core]
    if sum(1 for v in recorded if v is not None) < 2:
        return {"status": "no_altitude", "reason": "aucune altitude enregistrée à comparer", "report": res["report"]}
    # Séance FIT : altitude barométrique déjà lissée à l'ingestion -> lissage 3 pts + seuil 1 m,
    # même méthode que le D+ d'un GPX (`compare_gain_loss`).
    comp = compare_gain_loss(recorded, res["ele"])
    diffs = [m - r for m, r in zip(res["ele"], recorded) if r is not None]
    comp.update({
        "status": res["status"],
        "mean_offset_m": round(sum(diffs) / len(diffs), 1),  # MNT - enregistré : biais moyen du capteur
        "trimmed_m": trim_m,
        "points_compared": len(core),
        "report": res["report"],
    })
    return comp


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("settings", help="réglages effectifs ([elevation]/[privacy])")
    s.add_argument("--workspace")
    r = sub.add_parser("route", help="fournisseur choisi pour une coordonnée (aucun appel réseau)")
    r.add_argument("lat", type=float)
    r.add_argument("lon", type=float)
    args = ap.parse_args(argv)
    if args.cmd == "settings":
        from coach_setup import workspace_root
        print(json.dumps(load_settings(workspace_root(args.workspace)), ensure_ascii=False))
    else:
        print(provider_for(args.lat, args.lon))
    return 0


if __name__ == "__main__":
    sys.exit(main())
