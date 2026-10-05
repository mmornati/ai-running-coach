#!/usr/bin/env python3
"""
analyze_gpx.py — Analyse générique d'un fichier GPX (parcours/course).

Analyse un fichier GPX (Strava, Garmin, TrailRunProject...) et produit un
rapport Markdown structuré : distance réelle, D+/D- (avec lissage anti-bruit),
profil par km, détection des montées significatives, type de boucle (fermée
ou point-to-point), et compatibilité vs une cible optionnelle (distance, D+).

Conçu pour être piloté par l'agent course-strategist (ou coach) via le skill
`gpx-analysis`. Stdlib uniquement (xml.etree + math), aucune dépendance.

Usage
-----
    python3 skills/gpx-analysis/scripts/analyze_gpx.py \
        --gpx ~/Downloads/course.gpx \
        --target-distance 30-32 \
        --target-dp 1500 \
        --name "Mont-de-l'Enclus" \
        --output /tmp/rapport_parcours.md \
        --json /tmp/rapport_parcours.json

Options
-------
    --gpx             Chemin du fichier GPX (requis)
    --name            Nom du parcours (pour le rapport)
    --target-distance Cible distance "MIN-MAX" km (ex. "30-32") → verdict compat
    --target-dp       Cible D+ en m (ex. 1500) → verdict compat
    --smooth          Fenêtre de lissage D+ (points, défaut 3) — réduit le bruit GPS
    --min-gain        Gain net minimal d'une montée (m, défaut 15)
    --min-grade       Pente moyenne minimale d'une montée (%, défaut 5)
    --min-climb-dist  Distance minimale d'une montée (m, défaut 100)
    --output          Fichier Markdown de sortie (défaut stdout)
    --json            Fichier JSON de sortie (dump structuré)
    --quiet           N'affiche que les erreurs
    --dem             Corrige l'altitude par un MNT public (#176) : IGN RGE ALTI en France,
                      Copernicus GLO-90 via Open-Meteo ailleurs. Envoie des COORDONNÉES
                      amincies au fournisseur (voir docs/elevation.md) ; hors ligne, le
                      comportement antérieur (altitude du fichier) reste le repli.
    --no-dem          Désactive la correction même avec `[elevation].dem = "auto"`
    --dem-step        Pas d'amincissement des coordonnées envoyées (m, défaut config/50)
    --workspace       Workspace (config `[elevation]`, cache `.arc/dem-cache.json`)

Sortie
------
- Métadonnées (nom, type boucle, nb points)
- Tableau des indicateurs clés (distance, D+/D-, alt min/max, D+ moyen/km)
- Profil par km (D+ par km → localise les sections vallonnées)
- Liste des montées significatives (km de début/fin, distance, gain, grade moyen),
  détectées par le moteur (`scripts/arc_climb.py::detect_climbs`, voir `detect_climbs`)
- Verdict compatibilité si --target-* fournis

Prérequis
---------
- Python 3.8+ (stdlib uniquement)
"""

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Moteur : scripts/ à la racine (le skill peut être atteint par un lien symbolique
# depuis un workspace séparé — resolve() remonte au vrai dossier du moteur).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from arc_elevation import smooth_moving_average, step_gain_loss  # noqa: E402
import arc_climb  # noqa: E402
import arc_dem  # noqa: E402

NS = {"g": "http://www.topografix.com/GPX/1/1"}

# Pente moyenne minimale d'une montée (%) — même valeur que le moteur
# (`arc_climb.MIN_CLIMB_AVG_GRADE`, 5 %) : un faux plat n'est pas une montée.
DEFAULT_MIN_GRADE_PCT = arc_climb.MIN_CLIMB_AVG_GRADE * 100.0


# ---------------------------------------------------------------------------
# Parsing GPX
# ---------------------------------------------------------------------------

def parse_gpx(path: Path) -> list[dict]:
    """Extrait la liste ordonnée des points {lat, lon, ele} du premier trk/trkseg."""
    tree = ET.parse(path)
    root = tree.getroot()
    pts: list[dict] = []
    # namespace-agnostic : chercher trkpt avec ou sans préfixe
    for trkpt in root.iter():
        tag = trkpt.tag.rsplit("}", 1)[-1]
        if tag != "trkpt":
            continue
        try:
            lat = float(trkpt.attrib["lat"])
            lon = float(trkpt.attrib["lon"])
        except (KeyError, ValueError):
            continue
        ele = None
        for child in trkpt:
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "ele":
                try:
                    ele = float(child.text)
                except (TypeError, ValueError):
                    pass
        pts.append({"lat": lat, "lon": lon, "ele": ele})
    return pts


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance en mètres entre deux points GPS (formule de Haversine)."""
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def compute_metrics(pts: list[dict], smooth: int = 3, min_step_m: float = 1.0) -> dict:
    """Calcule distance, D+/D- (lissé), altitudes et profil par km. `min_step_m` : pas
    d'altitude ignoré (1 m pour un GPX brut ; 0 pour une série MNT interpolée, #176 —
    voir `arc_elevation.ASSUMPTIONS["dem_series"]`)."""
    # 1) distance cumulée + altitude brute
    dist = [0.0]
    for i in range(1, len(pts)):
        d = haversine(pts[i - 1]["lat"], pts[i - 1]["lon"], pts[i]["lat"], pts[i]["lon"])
        dist.append(dist[-1] + d)

    # 2) altitude : lissage glissant pour tuer le bruit GPS (moyenne glissante
    # partagée avec le GAP, `arc_elevation.smooth_moving_average` — #44)
    ele = smooth_moving_average([p["ele"] for p in pts], smooth)

    # 3) D+ / D- : montée/descente de chaque pas `i - 1 -> i` (post-lissage), seuil
    # `min_step_m` STRICT (`arc_elevation.step_gain_loss` : un pas de |d| <= seuil est
    # ignoré). Calculée UNE fois par pas : le total et le profil par km somment les mêmes
    # contributions — le profil sommait les écarts bruts sans seuil et pouvait dépasser
    # le D+ total sans `--dem`.
    step_up, step_down = [0.0] * len(ele), [0.0] * len(ele)
    for i in range(1, len(ele)):
        if ele[i] is None or ele[i - 1] is None:
            continue
        step_up[i], step_down[i] = step_gain_loss(ele[i] - ele[i - 1], min_step_m)
    dp, dm = sum(step_up), sum(step_down)

    # 4) profil par km
    total_km = dist[-1] / 1000
    km_profile = []
    for km in range(int(total_km) + 1):
        start, end = km * 1000, (km + 1) * 1000
        idx = [i for i, d in enumerate(dist) if start <= d < end]
        if not idx:
            km_profile.append({"km": km, "dp": 0.0, "dm": 0.0, "alt_min": None, "alt_max": None})
            continue
        # Pas `i - 1 -> i` attribué au km du point `i` ; `step_up[0]`/`step_down[0]` valent 0
        # par construction — jamais l'écart arrivée/départ dans le km 0 (relecture #176).
        kdp = sum(step_up[i] for i in idx)
        kdm = sum(step_down[i] for i in idx)
        alts = [ele[i] for i in idx if ele[i] is not None]
        km_profile.append({
            "km": km,
            "dp": round(kdp, 1),
            "dm": round(kdm, 1),
            "alt_min": round(min(alts), 1) if alts else None,
            "alt_max": round(max(alts), 1) if alts else None,
        })

    # 5) type de boucle : distance retour-à-départ < 300 m → boucle fermée
    alt_vals = [a for a in ele if a is not None]
    loop = len(pts) > 2 and haversine(pts[0]["lat"], pts[0]["lon"], pts[-1]["lat"], pts[-1]["lon"]) < 300
    return {
        "points": len(pts),
        "distance_m": dist[-1],
        "elevation_gain_m": round(dp, 1),
        "elevation_loss_m": round(dm, 1),
        "alt_min": round(min(alt_vals), 1) if alt_vals else None,
        "alt_max": round(max(alt_vals), 1) if alt_vals else None,
        "is_loop": loop,
        "km_profile": km_profile,
    }


# ---------------------------------------------------------------------------
# Détection des montées
# ---------------------------------------------------------------------------

def gpx_samples(pts: list[dict]) -> list[dict]:
    """Points GPX → échantillons normalisés attendus par `arc_climb.detect_climbs`
    (`t_s, distance_m, altitude_m, speed_ms`).

    `t_s` est l'INDEX du point, jamais la balise `<time>` : un GPX de parcours n'a
    en général pas de temps, et quand il en a un (tracé Strava/Garmin enregistré),
    une pause de l'enregistrement couperait une montée en deux via la segmentation
    par trou de signal (`arc_climb.MAX_GAP_S`) — or ce skill analyse le TERRAIN, pas
    une séance. Un pas constant de 1 garantit un seul segment continu. `speed_ms`
    reste `None` : aucune VAM n'est tirée d'un GPX (durées sans signification)."""
    samples = []
    cum = 0.0
    for i, p in enumerate(pts):
        if i:
            cum += haversine(pts[i - 1]["lat"], pts[i - 1]["lon"], p["lat"], p["lon"])
        samples.append({"t_s": float(i), "distance_m": cum, "altitude_m": p["ele"], "speed_ms": None})
    return samples


def detect_climbs(pts: list[dict], metrics=None, min_gain: float = 15.0,
                  min_dist: float = 100.0, min_grade_pct: float = DEFAULT_MIN_GRADE_PCT,
                  smooth: int = 3) -> list[dict]:
    """Montées du parcours via le détecteur canonique du moteur
    (`scripts/arc_climb.py::detect_climbs` : lissage, zigzag à hystérésis, rognage
    des approches/replats, découpage des plateaux, fusion des petits creux) —
    mêmes bornes de montée que le tableau de bord et #49 pour un même profil.

    Filtres propres au skill, appliqués par le détecteur (`min_gain`,
    `min_grade_pct`) puis ici (`min_dist`, jamais un critère du moteur). `metrics`
    n'est plus utilisé (conservé pour la compatibilité d'appel)."""
    found = arc_climb.detect_climbs(gpx_samples(pts), min_gain_m=min_gain,
                                    min_avg_grade=min_grade_pct / 100.0, smooth_taps=smooth)
    climbs = []
    for c in found:
        if c["distance_m"] < min_dist:
            continue
        climbs.append({
            "start_km": round(c["start_km"], 2),
            "end_km": round(c["end_km"], 2),
            "distance_m": c["distance_m"],
            "gain_m": c["gain_m"],
            "grade_pct": round(c["avg_grade"] * 100, 1),
            "grade_class": c["grade_class"],
        })
    return climbs


# ---------------------------------------------------------------------------
# Rapport Markdown
# ---------------------------------------------------------------------------

def format_kmh_pace(kmh: float) -> str:
    if kmh <= 0:
        return "—"
    return f"{60 / kmh * 60:.0f}:{((60 / kmh) * 60 % 60 * 60 / 60):02.0f}".replace(":", ":")


def _dem_section(dem: dict | None) -> list[str]:
    """Bloc « correction altimétrique » du rapport (#176) : vide si le MNT n'a pas été demandé."""
    if not dem:
        return []
    if dem["status"] == "unavailable":
        return [f"> ⚠️ Correction MNT indisponible ({dem.get('error')}) — altitudes du fichier conservées.", ""]
    c = dem["comparison"]
    pct = f" ({c['delta_gain_pct']:+.0f} %)" if c["delta_gain_pct"] is not None else ""
    lines = ["## Correction altimétrique (MNT)",
             "| | D+ fichier | D+ MNT (référence) | Écart |",
             "|:--|:--|:--|:--|",
             f"| D+ | {c['file_gain_m']:.0f} m | **{c['dem_gain_m']:.0f} m** | {c['delta_gain_m']:+.0f} m{pct} |",
             f"| D- | {c['file_loss_m']:.0f} m | **{c['dem_loss_m']:.0f} m** | "
             f"{c['dem_loss_m'] - c['file_loss_m']:+.0f} m |",
             ""]
    lines.append("Les chiffres du rapport (D+, D-, profil, montées) sont calculés sur l'altitude MNT. "
                 f"Pas d'échantillonnage {dem['report']['step_m']} m : {dem['report']['nodes']} points "
                 f"interrogés, dont {dem['report'].get('coords_sent', 0)} envoyés au fournisseur "
                 "(coordonnées seules, le reste depuis le cache local).")
    if dem["status"] == "partial":
        lines.append(f"Couverture partielle : {dem['report'].get('coverage_pct')} % des points résolus, "
                     "le reste interpolé.")
    lines.extend(f"_{a}_" for a in dem["report"]["attribution"])
    lines.append("")
    return lines


def build_report(name: str, m: dict, climbs: list[dict], target: dict, dem: dict | None = None) -> str:
    km = m["distance_m"] / 1000
    lines = [f"# Analyse parcours GPX — {name or 'Parcours'}", ""]
    lines.append(f"**Fichier analysé :** distance réelle **{km:.1f} km** · D+ **{m['elevation_gain_m']:.0f} m** · "
                 f"D- **{m['elevation_loss_m']:.0f} m** · alt {m['alt_min']} → {m['alt_max']} m · "
                 f"**{'boucle fermée' if m['is_loop'] else 'point-to-point'}** · {m['points']} points GPS")
    lines.append("")
    lines.extend(_dem_section(dem))

    # Verdict compat
    if target.get("distance") or target.get("dp"):
        lines.append("## Verdict compatibilité")
        lines.append("| Critère | Cible | Parcours | Verdict |")
        lines.append("|:--------|:------|:---------|:--------|")
        if target.get("distance"):
            lo, hi = target["distance"]
            v = "✅" if lo <= km <= hi else ("🔴 Trop long" if km > hi else "🔴 Trop court")
            lines.append(f"| Distance | {lo}-{hi} km | **{km:.1f} km** | {v} |")
        if target.get("dp"):
            v = "✅" if m["elevation_gain_m"] >= target["dp"] * 0.9 else f"🟡 Sous la cible (-{int(100 - m['elevation_gain_m'] / target['dp'] * 100)}%)"
            lines.append(f"| D+ | ~{target['dp']} m | **{m['elevation_gain_m']:.0f} m** | {v} |")
        lines.append("")

    # Profil par km
    lines.append("## Profil par km (D+ par km)")
    lines.append("| Km | D+ (m) | D- (m) | Alt min/max | Lecture |")
    lines.append("|:---|:-------|:-------|:------------|:--------|")
    for kp in m["km_profile"]:
        lect = "⛰️ Montée" if kp["dp"] >= 40 else ("〽️ Mixte" if kp["dp"] >= 15 else "🟢 Plat/descente")
        alt = f"{kp['alt_min']}/{kp['alt_max']}" if kp["alt_min"] is not None else "—"
        lines.append(f"| {kp['km']} | {kp['dp']:.0f} | {kp['dm']:.0f} | {alt} | {lect} |")
    lines.append("")

    # Montées significatives
    lines.append(f"## Montées significatives ({len(climbs)})")
    if climbs:
        lines.append("| Début (km) | Fin (km) | Distance (m) | Gain (m) | Grade moyen |")
        lines.append("|:-----------|:---------|:-------------|:---------|:------------|")
        for c in climbs:
            lines.append(f"| {c['start_km']} | {c['end_km']} | {c['distance_m']:.0f} | +{c['gain_m']:.0f} | {c['grade_pct']}% |")
    else:
        lines.append("_Aucune montée ≥ seuil détectée (parcours très roulant)._")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Analyse générique d'un fichier GPX (parcours/course).")
    ap.add_argument("--gpx", type=Path, required=True, help="Chemin du fichier GPX")
    ap.add_argument("--name", default="", help="Nom du parcours (rapport)")
    ap.add_argument("--target-distance", help="Cible distance 'MIN-MAX' km (ex. 30-32)")
    ap.add_argument("--target-dp", type=float, help="Cible D+ en m")
    ap.add_argument("--smooth", type=int, default=3, help="Fenêtre de lissage D+ (points)")
    ap.add_argument("--min-gain", type=float, default=15.0, help="Gain min d'une montée (m)")
    ap.add_argument("--min-grade", type=float, default=DEFAULT_MIN_GRADE_PCT,
                    help="Pente moyenne min d'une montée (%%, défaut %(default).0f)")
    ap.add_argument("--min-climb-dist", type=float, default=100.0, help="Distance min d'une montée (m)")
    ap.add_argument("--output", type=Path, default=None, help="Fichier Markdown de sortie (défaut stdout)")
    ap.add_argument("--json", type=Path, default=None, help="Fichier JSON de sortie")
    ap.add_argument("--quiet", action="store_true", help="N'affiche que les erreurs")
    ap.add_argument("--dem", action="store_true",
                    help="Corrige l'altitude par MNT public (IGN France / Copernicus ailleurs, #176)")
    ap.add_argument("--no-dem", action="store_true", help="Désactive la correction MNT (même en mode auto)")
    ap.add_argument("--dem-step", type=float, default=None, help="Pas d'amincissement des coordonnées (m)")
    ap.add_argument("--workspace", default=None, help="Workspace (config [elevation], cache .arc/)")
    args = ap.parse_args(argv)

    if not args.gpx.exists():
        print(f"ERREUR : fichier GPX introuvable — {args.gpx}", file=sys.stderr)
        return 1

    pts = parse_gpx(args.gpx)
    if not pts:
        print(f"ERREUR : aucun point trkpt dans {args.gpx}", file=sys.stderr)
        return 1

    if args.dem and args.no_dem:
        print("ERREUR : --dem et --no-dem sont incompatibles.", file=sys.stderr)
        return 1
    m = compute_metrics(pts, smooth=args.smooth)
    climbs_smooth = args.smooth
    dem = None
    from coach_setup import workspace_root  # noqa: E402 — config lue seulement ici
    workspace = workspace_root(args.workspace)
    settings = arc_dem.load_settings(workspace)
    if args.dem or (settings["dem"] == "auto" and not args.no_dem):
        cache = arc_dem.DemCache(arc_dem.cache_path(workspace), enabled=settings["cache"])
        res = arc_dem.resample_track(pts, step_m=args.dem_step or settings["step_m"], cache=cache)
        if res["status"] == "unavailable":
            print(f"AVERTISSEMENT : correction MNT indisponible ({res['report'].get('error')}) — "
                  "altitudes du fichier conservées.", file=sys.stderr)
            dem = {"status": "unavailable", "error": res["report"].get("error"), "report": res["report"]}
        else:
            comparison = arc_dem.compare_gain_loss([p["ele"] for p in pts], res["ele"], file_smooth=args.smooth)
            pts = [{**p, "ele_file": p["ele"], "ele": z} for p, z in zip(pts, res["ele"])]
            m = compute_metrics(pts, smooth=1, min_step_m=0.0)
            climbs_smooth = 1
            dem = {"status": res["status"], "comparison": comparison, "report": res["report"]}
    if dem is not None:  # clé absente sans MNT demandé : sortie inchangée par rapport à avant #176
        m["elevation_source"] = "dem" if dem["status"] != "unavailable" else "file"
    climbs = detect_climbs(pts, m, min_gain=args.min_gain, min_dist=args.min_climb_dist,
                           min_grade_pct=args.min_grade, smooth=climbs_smooth)

    target = {}
    if args.target_distance:
        lo, hi = args.target_distance.split("-")
        target["distance"] = (float(lo), float(hi))
    if args.target_dp:
        target["dp"] = args.target_dp

    report = build_report(args.name, m, climbs, target, dem)

    if args.json:
        dump = {
            "name": args.name,
            "metrics": {k: v for k, v in m.items() if k != "km_profile"},
            "km_profile": m["km_profile"],
            "climbs": climbs,
            "target": target,
        }
        if dem:
            dump["dem"] = dem
        args.json.write_text(json.dumps(dump, indent=2, ensure_ascii=False))
        if not args.quiet:
            print(f"JSON écrit dans {args.json}")

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        if not args.quiet:
            print(f"Markdown écrit dans {args.output}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())