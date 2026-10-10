#!/usr/bin/env python3
"""Choisir un parcours MyWhoosh qui tient dans la durée d'une séance home trainer.

Sous-commandes, stdlib uniquement :

- ``fetch``    : connexion à MyWhoosh (API non officielle, documentée par
                 https://github.com/mywhoosh-community/mywhoosh-api) et mise en cache du
                 catalogue des parcours « free ride » (nom, monde, km, D+, difficulté,
                 boucle ou non). Mot de passe lu par ``getpass`` (ou ``MYWHOOSH_PASSWORD``),
                 jamais écrit ; seul le jeton d'accès est gardé, en mode 600.
- ``suggest``  : classe les parcours dont le temps prévu tient dans la séance, à la
                 puissance que l'athlète tient dans sa plage FC cible — calibrée par
                 ``scripts/arc_index.py power-hr`` (``--calibration``), jamais devinée.
                 Hors ligne : utilisable en headless.
- ``tasks``    : calendrier MyWhoosh, lecture seule (jeton en cache, jamais de connexion).
- ``schedule`` : inscrit une sortie libre au calendrier MyWhoosh. ÉCRITURE : simulation
                 par défaut, ``--yes`` seulement après le « oui » explicite de l'athlète,
                 jamais en headless ; relit le calendrier pour vérifier.

Modèle de temps (approximation du projet) : équation de puissance en régime
permanent (traînée aérodynamique + roulement + gravité), un parcours étant
réduit à une montée régulière sur ``UP_FRACTION`` de sa distance et à une
descente sur le reste. Paramètres choisis pour recouper les temps publiés par
mywhooshinfo.com (Alula Adventure Loop, 1,6 à 4,0 W/kg : écarts −6,5 % à +3,6 %).
Toute prédiction porte une bande de ±10 %, affichée ; un parcours est retenu si
son temps central tombe dans la séance (voir ``suggest``). Ce n'est jamais une mesure.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import json
import math
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

LOGIN_URL = "https://services.mywhoosh.com/http-service/api/login"
ROUTES_URL = "https://services.mywhoosh.com/http-service/v1/free-ride/routes"
TASKS_URL = "https://service14.mywhoosh.com/v1/task"
USER_AGENT = "ai-running-coach/mywhoosh-route"
DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ai-running-coach" / "mywhoosh_routes.json"
# Jeton d'accès (mode 600, hors dépôt, jamais affiché) — même logique que ~/.garminconnect.
DEFAULT_TOKEN = Path.home() / ".config" / "ai-running-coach" / "mywhoosh-token.json"

# Physique (approximation du projet, voir docstring du module).
GRAVITY = 9.81
RHO = 1.2           # kg/m³
CDA = 0.32          # m²
CRR = 0.004
BIKE_KG = 8.0       # vélo virtuel + tenue, si le profil ne déclare pas la masse du vélo
UP_FRACTION = 0.3   # part de la distance en montée
VMAX_MS = 70 / 3.6  # plafond en descente
BAND = 0.10

# Intensité planifiée → zone FC visée et filtres de parcours (approximation du projet).
# `difficulty` = champ `Difficulty` de MyWhoosh (1 facile … 5 très dur) : il voit les murs
# courts qu'une moyenne de D+/km cache (The Muur, Montreal…).
INTENSITY_PRESETS = {
    "recovery": {"zone": 1, "max_difficulty": 1, "max_m_per_km": 5.0},
    "endurance": {"zone": 2, "max_difficulty": 2, "max_m_per_km": 12.0},
    "tempo": {"zone": 3, "max_difficulty": 3, "max_m_per_km": 15.0},
    "threshold": {"zone": 4, "max_difficulty": None, "max_m_per_km": None},
    "vo2max": {"zone": 5, "max_difficulty": None, "max_m_per_km": None},
}


# --------------------------------------------------------------------------- fetch

def _request(url: str, *, method: str = "GET", token: str | None = None, body: dict | None = None):
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def _jwt_exp(token: str) -> int | None:
    """Échéance (epoch) lue dans la charge utile du JWT, sans vérifier la signature."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload))["exp"])
    except (IndexError, KeyError, ValueError, TypeError):
        return None


def load_token(path: Path, now: float | None = None) -> str | None:
    """Jeton encore valide (marge de 5 min) ou None. Jamais affiché."""
    try:
        token = json.loads(path.read_text())["access_token"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    exp = _jwt_exp(token)
    if exp is not None and exp - 300 <= (now if now is not None else time.time()):
        return None
    return token


def save_token(path: Path, token: str) -> None:
    """Écrit le jeton en mode 600 (création atomique), comme les jetons Garmin."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"access_token": token}, f)
    os.replace(tmp, path)


def login(args, *, interactive: bool = True) -> str | None:
    """Jeton en cache, sinon connexion (mot de passe au terminal). ``interactive=False``
    (lecture seule hors terminal) ne demande jamais rien : None si pas de jeton valide."""
    token = load_token(args.token_file)
    if token:
        return token
    if not interactive or (not sys.stdin.isatty() and not os.environ.get("MYWHOOSH_PASSWORD")):
        print("Pas de jeton MyWhoosh valide — relancer `fetch` dans un terminal.", file=sys.stderr)
        return None
    user = getattr(args, "username", None) or os.environ.get("MYWHOOSH_USERNAME") or input("E-mail MyWhoosh : ").strip()
    pwd = os.environ.get("MYWHOOSH_PASSWORD") or getpass.getpass("Mot de passe MyWhoosh : ")
    resp = _request(LOGIN_URL, method="POST", body={
        "Username": user, "Password": pwd, "Platform": "Android", "Action": 1001,
        "CorrelationId": str(uuid.uuid4()), "DeviceId": str(uuid.uuid4()), "Authorization": "",
    })
    del pwd
    if not resp.get("Success") or not resp.get("AccessToken"):
        print(f"Connexion refusée : {resp.get('Message') or 'réponse inattendue'}", file=sys.stderr)
        return None
    save_token(args.token_file, resp["AccessToken"])
    return resp["AccessToken"]


def flatten_routes(worlds: list) -> list[dict]:
    """Réponse brute de ``/free-ride/routes`` (liste de mondes) → liste plate de
    parcours roulables en free ride, avec seulement les champs utiles.
    ``loop`` : ``RouteType == "E_Circuit"`` (boucle répétable) ; ``E_Sprint`` et
    les autres sont des parcours point à point, jamais proposés en plusieurs tours."""
    out = []
    for w in worlds or []:
        for r in w.get("Routes") or []:
            if r.get("bIsAvailableForFreeRide") is False:
                continue
            km, elev = r.get("Km"), r.get("Elevation")
            if not isinstance(km, (int, float)) or km <= 0 or not isinstance(elev, (int, float)):
                continue
            out.append({
                "id": r.get("Id"),
                "name": (r.get("Name") or "").strip(),
                "world": w.get("WorldName"),
                "world_id": w.get("WorldId"),
                "distance_m": round(km * 1000),
                "elevation_gain_m": round(elev),
                "difficulty": r.get("Difficulty"),
                "route_type": r.get("RouteType"),
                "loop": r.get("RouteType") == "E_Circuit",
            })
    return out


def cmd_fetch(args) -> int:
    token = login(args)
    if not token:
        return 2
    routes = flatten_routes(_request(ROUTES_URL, token=token))
    if not routes:
        print("Aucun parcours reçu (format de réponse changé ?) — cache inchangé.", file=sys.stderr)
        return 3
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_text(json.dumps({"source": ROUTES_URL, "fetched_at": int(time.time()), "routes": routes},
                                     ensure_ascii=False, indent=1))
    print(f"OK {len(routes)} parcours -> {args.cache}")
    return 0


def _day_bounds(date_from: str, date_to: str) -> tuple[int, int]:
    start = dt.datetime.combine(dt.date.fromisoformat(date_from), dt.time.min).astimezone()
    end = dt.datetime.combine(dt.date.fromisoformat(date_to), dt.time.max).astimezone()
    return int(start.timestamp()), int(end.timestamp())


def cmd_tasks(args) -> int:
    """Calendrier MyWhoosh (lecture seule). Sortie brute de l'API : sa forme n'est pas
    documentée pour les sorties libres, on ne la réinterprète pas."""
    token = login(args, interactive=False)
    if not token:
        return 2
    lo, hi = _day_bounds(args.date_from, args.date_to or args.date_from)
    resp = _request(f"{TASKS_URL}/date-range-task-list?startDate={lo}&endDate={hi}", token=token)
    print(json.dumps(resp, ensure_ascii=False, indent=1))
    return 0




def build_task(*, route: dict, date: str, start: str, duration_min: float, name: str,
               description: str = "") -> dict:
    """Corps de ``POST /task/create`` pour une sortie libre (``E_FreeRide``).

    Le format d'une sortie libre n'est PAS documenté par la communauté (seuls ceux d'un
    événement et d'un workout le sont) : ``TaskTypeId`` = identifiant du parcours et
    ``MapId`` = identifiant du monde sont une HYPOTHÈSE, à confirmer par la relecture
    (``tasks``) après la première écriture."""
    start_dt = dt.datetime.combine(dt.date.fromisoformat(date), dt.time.fromisoformat(start)).astimezone()
    epoch = int(start_dt.timestamp())
    return {
        "TaskId": "", "TaskType": "E_FreeRide", "TaskStartedTimeEpoc": epoch,
        "TaskTypeId": str(route["id"]), "CurDayId": "", "TaskState": "E_NotStarted", "DayNo": 0,
        "TaskEndEpochTime": epoch + int(duration_min * 60), "MapId": int(route.get("world_id") or 0),
        "TaskName": name, "TaskDescription": description,
        "TotalKilometers": round(route["distance_m"] / 1000, 2),
        "TotalElevation": route["elevation_gain_m"],
        "TSS": 0,  # nom de champ imposé par l'API MyWhoosh (sigle, marque de Peaksware) — jamais affiché
        "SportMode": "E_Cycling",
    }


def cmd_schedule(args) -> int:
    routes = _load_routes(args.cache)
    if routes is None:
        return 2
    route = next((r for r in routes if r.get("id") == args.route_id), None)
    if route is None:
        print(f"Parcours {args.route_id} absent du catalogue — relancer `fetch`.", file=sys.stderr)
        return 2
    body = build_task(route=route, date=args.date, start=args.start, duration_min=args.duration_min,
                      name=args.name or route["name"], description=args.description or "")
    if not args.yes:
        print(json.dumps({"dry_run": True, "task": body}, ensure_ascii=False, indent=1))
        print("Simulation : rien n'est écrit. Ajouter --yes après le « oui » explicite de l'athlète.", file=sys.stderr)
        return 0
    if not sys.stdin.isatty() and not args.allow_non_tty:
        print("Écriture MyWhoosh refusée hors session interactive (jamais en headless).", file=sys.stderr)
        return 2
    token = login(args, interactive=False)
    if not token:
        return 2
    lo, hi = _day_bounds(args.date, args.date)
    existing = _request(f"{TASKS_URL}/date-range-task-list?startDate={lo}&endDate={hi}", token=token)
    for task in ((existing.get("data") or {}).get("taskList") or []):
        if str(task.get("TaskTypeId") or task.get("taskTypeId")) == body["TaskTypeId"]:
            print(json.dumps({"status": "already_scheduled", "task": task}, ensure_ascii=False, indent=1))
            return 0
    created = _request(f"{TASKS_URL}/create", method="POST", token=token, body=body)
    after = _request(f"{TASKS_URL}/date-range-task-list?startDate={lo}&endDate={hi}", token=token)
    print(json.dumps({"status": "created", "response": created,
                      "verify": (after.get("data") or {}).get("taskList")}, ensure_ascii=False, indent=1))
    return 0


# ------------------------------------------------------------------------ suggest

def speed_ms(power_w: float, mass_kg: float, grade: float) -> float:
    """Vitesse d'équilibre à puissance constante sur une pente donnée (dichotomie)."""
    th = math.atan(grade)
    lo, hi = 0.1, VMAX_MS
    for _ in range(60):
        v = (lo + hi) / 2
        need = (CRR * mass_kg * GRAVITY * math.cos(th) + mass_kg * GRAVITY * math.sin(th)) * v + 0.5 * RHO * CDA * v ** 3
        lo, hi = (lo, v) if need > power_w else (v, hi)
    return lo


def route_time_s(power_w: float, rider_kg: float, distance_m: float, elevation_m: float,
                 bike_kg: float = BIKE_KG) -> float:
    m = rider_kg + bike_kg
    if elevation_m <= 0.5:
        return distance_m / speed_ms(power_w, m, 0.0)
    up = distance_m * UP_FRACTION
    down = distance_m - up
    return up / speed_ms(power_w, m, elevation_m / up) + down / speed_ms(power_w, m, -elevation_m / down)


def session_power(target_w: float, total_min: float, warmup_min: float, cooldown_min: float) -> float:
    """Puissance moyenne de la séance : échauffement ~75 %, retour au calme ~65 % de la cible."""
    main = max(total_min - warmup_min - cooldown_min, 0)
    return (warmup_min * 0.75 * target_w + main * target_w + cooldown_min * 0.65 * target_w) / total_min


def _is_loop(route: dict) -> bool:
    if "loop" in route:
        return bool(route["loop"])
    return route.get("route_type") == "E_Circuit"


def suggest(routes: list[dict], *, duration_min: float, avg_power_w: float, rider_kg: float,
            bike_kg: float = BIKE_KG, max_m_per_km: float | None = None, max_difficulty: int | None = None,
            min_fill: float = 0.85, overrun_min: float = 5, max_laps: int = 3, top: int = 8) -> list[dict]:
    """Parcours dont le temps prévu (au centre de la bande) tombe entre
    ``min_fill × séance`` et ``séance + overrun_min``. Arriver un peu avant la fin
    n'est pas un problème (on finit en free ride ou on fait le retour au calme
    après la ligne) ; un léger dépassement non plus (on s'arrête à l'heure).
    Plusieurs tours seulement sur une boucle (``E_Circuit``). Les parcours de
    difficulté 0 (événements : UCI, Supertri…) sont écartés."""
    budget = duration_min * 60
    out = []
    for r in routes:
        d, e = r["distance_m"], r["elevation_gain_m"]
        diff = r.get("difficulty")
        if diff == 0:
            continue
        if max_difficulty is not None and diff is not None and diff > max_difficulty:
            continue
        m_per_km = e / (d / 1000)
        if max_m_per_km is not None and m_per_km > max_m_per_km:
            continue
        lap = route_time_s(avg_power_w, rider_kg, d, e, bike_kg)
        laps = min(max(1, round(budget / lap)), max_laps) if _is_loop(r) else 1
        mid = lap * laps
        if not (min_fill * budget <= mid <= budget + overrun_min * 60):
            continue
        out.append({**r, "m_per_km": round(m_per_km, 1), "laps": laps, "lap_s": round(lap),
                    "predicted_s": round(mid), "low_s": round(mid * (1 - BAND)),
                    "high_s": round(mid * (1 + BAND)), "fill": round(mid / budget, 3)})
    # Le plus proche de la durée d'abord ; à égalité, un seul tour, puis le moins vallonné.
    out.sort(key=lambda r: (round(abs(r["fill"] - 1), 2), r["laps"], r["m_per_km"]))
    return out[:top]


def _fmt(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600}h{(s % 3600) // 60:02d}" if s >= 3600 else f"{s // 60} min"


def garmin_label(route: dict, duration_min: float, zone: int | None) -> str:
    """Nom court pour le `workoutName` Garmin : la montre l'affiche, le parcours s'y retrouve.
    ASCII seulement pour la partie fixe (comme les noms poussés par le coach) ; le nom du
    parcours est gardé tel que MyWhoosh l'écrit, pour le retrouver dans l'application."""
    laps = f" x{route['laps']}" if route.get("laps", 1) > 1 else ""
    z = f" Z{zone}" if zone else ""
    return f"HT{z} {duration_min:.0f}min - {route['name']}{laps}"


def virtual_route(route: dict, target_w: float) -> dict:
    """Objet `session.virtual_route` du contrat (`workspace-data-contract`)."""
    out = {"platform": "mywhoosh", "route_id": route["id"], "name": route["name"],
           "world": route.get("world"), "world_id": route.get("world_id"), "laps": route["laps"],
           "distance_m": route["distance_m"] * route["laps"],
           "elevation_gain_m": route["elevation_gain_m"] * route["laps"],
           "predicted_s": route["predicted_s"], "target_power_w": round(target_w)}
    return {k: v for k, v in out.items() if v is not None}


def _load_routes(path: Path) -> list[dict] | None:
    if not path.exists():
        print(f"Catalogue absent ({path}) — lancer d'abord `fetch` (session interactive).", file=sys.stderr)
        return None
    return json.loads(path.read_text())["routes"]


def resolve_target(args, cal: dict | None) -> tuple[float | None, str, list[float] | None]:
    """(puissance cible, provenance, plage FC) : `--target-w` > calibration à la plage FC
    (`--hr-low/--hr-high`, sinon zone de l'intensité dans `zones`) > rien."""
    if args.target_w is not None:
        return args.target_w, "déclarée", None
    fit = (cal or {}).get("fit")
    if not fit:
        return None, (cal or {}).get("reason") or "pas de calibration", None
    if args.hr_low is not None and args.hr_high is not None:
        lo, hi = args.hr_low, args.hr_high
    else:
        preset = INTENSITY_PRESETS.get(args.intensity or "endurance", INTENSITY_PRESETS["endurance"])
        zone = next((z for z in cal.get("zones") or [] if z["zone"] == preset["zone"]), None)
        if not zone:
            return None, "zone FC du profil indisponible (FC max/repos) : passer --hr-low/--hr-high", None
        lo, hi = zone["bounds_bpm"]
        if args.low_half:
            hi = (lo + hi) / 2
    hr = (lo + hi) / 2
    target = fit["intercept_w"] + fit["slope_w_per_bpm"] * hr
    return target, f"calibration FC {lo:.0f}-{hi:.0f} bpm (±{fit['resid_sd_w']:.0f} W)", [lo, hi]


def cmd_suggest(args) -> int:
    routes = _load_routes(args.cache)
    if routes is None:
        return 2
    cal = json.loads(Path(args.calibration).read_text()) if args.calibration else None
    target, source, hr_band = resolve_target(args, cal)
    if target is None:
        print(f"Pas de puissance cible ({source}) : pas de suggestion.", file=sys.stderr)
        return 2
    weight = args.weight_kg or (cal or {}).get("weight_kg")
    if not weight:
        print("Poids inconnu : passer --weight-kg (ou renseigner le profil / une pesée).", file=sys.stderr)
        return 2
    bike = args.bike_kg or ((cal or {}).get("equipment") or {}).get("bike_mass_kg") or BIKE_KG
    preset = INTENSITY_PRESETS.get(args.intensity or "endurance", INTENSITY_PRESETS["endurance"])
    max_m = args.max_m_per_km if args.max_m_per_km is not None else preset["max_m_per_km"]
    max_diff = args.max_difficulty if args.max_difficulty is not None else preset["max_difficulty"]
    avg = session_power(target, args.duration_min, args.warmup_min, args.cooldown_min)
    res = suggest(routes, duration_min=args.duration_min, avg_power_w=avg, rider_kg=weight, bike_kg=bike,
                  max_m_per_km=max_m, max_difficulty=max_diff, min_fill=args.min_fill,
                  overrun_min=args.overrun_min, max_laps=args.max_laps, top=args.top)
    for r in res:
        r["garmin_workout_name"] = garmin_label(r, args.duration_min, preset["zone"])
        r["virtual_route"] = virtual_route(r, target)
    out = {"duration_min": args.duration_min, "intensity": args.intensity or "endurance",
           "hr_band_bpm": [round(x) for x in hr_band] if hr_band else None,
           "target_power_w": round(target), "target_source": source,
           "session_avg_power_w": round(avg), "w_per_kg": round(avg / weight, 2),
           "weight_kg": weight, "bike_kg": bike, "max_m_per_km": max_m, "max_difficulty": max_diff,
           "routes": res, "note": "estimation à ±10 % (approximation du projet), jamais une mesure ; la FC commande"}
    if not args.text:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    print(f"Séance {args.duration_min:.0f} min · cible {round(target)} W ({source}) · "
          f"moyenne séance ~{round(avg)} W ({out['w_per_kg']} W/kg)")
    if not res:
        print("Aucun parcours ne tient dans la séance avec ces filtres.")
    for r in res:
        laps = f" × {r['laps']} tours" if r["laps"] > 1 else ""
        print(f"- {r['name']} ({r['world']}, difficulté {r.get('difficulty')}) : {r['distance_m'] / 1000:.1f} km, "
              f"D+ {r['elevation_gain_m']} m ({r['m_per_km']} m/km){laps} → {_fmt(r['predicted_s'])} "
              f"[{_fmt(r['low_s'])}–{_fmt(r['high_s'])}], remplit {r['fill'] * 100:.0f} %")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help=f"catalogue des parcours (défaut {DEFAULT_CACHE})")
    ap.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN, help="jeton MyWhoosh (mode 600)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="récupère le catalogue des parcours MyWhoosh (connexion requise)")
    f.add_argument("--username")
    f.set_defaults(func=cmd_fetch)

    t = sub.add_parser("tasks", help="calendrier MyWhoosh, lecture seule (jeton en cache requis)")
    t.add_argument("date_from", help="AAAA-MM-JJ")
    t.add_argument("date_to", nargs="?", help="AAAA-MM-JJ (défaut : date_from)")
    t.set_defaults(func=cmd_tasks)

    w = sub.add_parser("schedule", help="inscrit une sortie libre au calendrier MyWhoosh (simulation par défaut)")
    w.add_argument("--route-id", type=int, required=True)
    w.add_argument("--date", required=True, help="AAAA-MM-JJ")
    w.add_argument("--start", default="18:00", help="HH:MM, heure locale")
    w.add_argument("--duration-min", type=float, required=True)
    w.add_argument("--name")
    w.add_argument("--description")
    w.add_argument("--yes", action="store_true", help="écrit vraiment (après le « oui » explicite de l'athlète)")
    w.add_argument("--allow-non-tty", action="store_true", help=argparse.SUPPRESS)
    w.set_defaults(func=cmd_schedule)

    s = sub.add_parser("suggest", help="parcours qui tiennent dans la séance (hors ligne)")
    s.add_argument("--duration-min", type=float, required=True)
    s.add_argument("--intensity", choices=sorted(INTENSITY_PRESETS), default="endurance",
                   help="intensité planifiée : zone FC visée et filtres de parcours")
    s.add_argument("--calibration", help="sortie JSON de `scripts/arc_index.py power-hr`")
    s.add_argument("--target-w", type=float, help="puissance cible du bloc principal (prime sur la calibration)")
    s.add_argument("--hr-low", type=float, help="plage FC explicite (prime sur la zone de l'intensité)")
    s.add_argument("--hr-high", type=float)
    s.add_argument("--low-half", action="store_true", help="moitié basse de la zone (bilan matinal prudent)")
    s.add_argument("--weight-kg", type=float, help="défaut : poids de la calibration (dernière pesée / profil)")
    s.add_argument("--bike-kg", type=float, help=f"défaut : masse du vélo du profil, sinon {BIKE_KG:g} kg")
    s.add_argument("--warmup-min", type=float, default=5)
    s.add_argument("--cooldown-min", type=float, default=5)
    s.add_argument("--max-m-per-km", type=float, help="D+ moyen maximal (m/km), défaut selon l'intensité")
    s.add_argument("--max-difficulty", type=int, help="difficulté MyWhoosh maximale (1-5), défaut selon l'intensité")
    s.add_argument("--min-fill", type=float, default=0.85, help="part minimale de la séance couverte par le parcours")
    s.add_argument("--overrun-min", type=float, default=5, help="dépassement toléré (min) au-delà de la séance")
    s.add_argument("--max-laps", type=int, default=3)
    s.add_argument("--top", type=int, default=5)
    s.add_argument("--text", action="store_true")
    s.set_defaults(func=cmd_suggest)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
