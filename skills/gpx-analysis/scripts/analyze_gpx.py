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
    --min-gain        Seuil de détection d'une montée (m, défaut 15)
    --min-climb-dist  Distance minimale d'une montée (m, défaut 100)
    --output          Fichier Markdown de sortie (défaut stdout)
    --json            Fichier JSON de sortie (dump structuré)
    --quiet           N'affiche que les erreurs

Sortie
------
- Métadonnées (nom, type boucle, nb points)
- Tableau des indicateurs clés (distance, D+/D-, alt min/max, D+ moyen/km)
- Profil par km (D+ par km → localise les sections vallonnées)
- Liste des montées significatives (km de début/fin, distance, gain, grade moyen)
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
from arc_elevation import smooth_moving_average  # noqa: E402

NS = {"g": "http://www.topografix.com/GPX/1/1"}


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


def compute_metrics(pts: list[dict], smooth: int = 3) -> dict:
    """Calcule distance, D+/D- (lissé), altitudes et profil par km."""
    # 1) distance cumulée + altitude brute
    dist = [0.0]
    for i in range(1, len(pts)):
        d = haversine(pts[i - 1]["lat"], pts[i - 1]["lon"], pts[i]["lat"], pts[i]["lon"])
        dist.append(dist[-1] + d)

    # 2) altitude : lissage glissant pour tuer le bruit GPS (moyenne glissante
    # partagée avec le GAP, `arc_elevation.smooth_moving_average` — #44)
    ele = smooth_moving_average([p["ele"] for p in pts], smooth)

    # 3) D+ / D- : somme des montées/descentes > 1 m (post-lissage)
    dp, dm = 0.0, 0.0
    for i in range(1, len(ele)):
        if ele[i] is None or ele[i - 1] is None:
            continue
        d = ele[i] - ele[i - 1]
        if d > 1.0:
            dp += d
        elif d < -1.0:
            dm += abs(d)

    # 4) profil par km
    total_km = dist[-1] / 1000
    km_profile = []
    for km in range(int(total_km) + 1):
        start, end = km * 1000, (km + 1) * 1000
        idx = [i for i, d in enumerate(dist) if start <= d < end]
        if not idx:
            km_profile.append({"km": km, "dp": 0.0, "dm": 0.0, "alt_min": None, "alt_max": None})
            continue
        kdp = sum(max(0.0, ele[i] - ele[i - 1]) for i in idx if ele[i] is not None and ele[i - 1] is not None and ele[i] > ele[i - 1])
        kdm = sum(max(0.0, ele[i - 1] - ele[i]) for i in idx if ele[i] is not None and ele[i - 1] is not None and ele[i] < ele[i - 1])
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

def detect_climbs(pts: list[dict], metrics: dict, min_gain: float = 15.0, min_dist: float = 100.0) -> list[dict]:
    """Détecte les montées : gain >= min_gain sur une distance >= min_dist."""
    # reconstruction distance + altitude lissée (réutilise compute_metrics)
    dist = [0.0]
    for i in range(1, len(pts)):
        dist.append(dist[-1] + haversine(pts[i - 1]["lat"], pts[i - 1]["lon"], pts[i]["lat"], pts[i]["lon"]))
    climbs = []
    start_i = None
    start_alt = None
    start_dist = None
    peak_alt = None
    for i in range(len(pts)):
        alt = pts[i]["ele"]
        if alt is None:
            continue
        if start_i is None or alt > (peak_alt if peak_alt is not None else alt):
            if start_i is None:
                start_i, start_alt, start_dist = i, alt, dist[i]
                peak_alt = alt
            else:
                peak_alt = max(peak_alt, alt)
        else:
            gain = peak_alt - start_alt
            length = dist[i - 1] - start_dist
            if gain >= min_gain and length >= min_dist:
                climbs.append({
                    "start_km": round(start_dist / 1000, 2),
                    "end_km": round(dist[i - 1] / 1000, 2),
                    "distance_m": round(length, 1),
                    "gain_m": round(gain, 1),
                    "grade_pct": round(gain / length * 100, 1) if length > 0 else 0.0,
                })
            start_i, start_alt, start_dist = None, None, None
            peak_alt = None
    # flush final
    if start_i is not None and peak_alt is not None:
        gain = peak_alt - start_alt
        length = dist[-1] - start_dist
        if gain >= min_gain and length >= min_dist:
            climbs.append({
                "start_km": round(start_dist / 1000, 2),
                "end_km": round(dist[-1] / 1000, 2),
                "distance_m": round(length, 1),
                "gain_m": round(gain, 1),
                "grade_pct": round(gain / length * 100, 1) if length > 0 else 0.0,
            })
    return climbs


# ---------------------------------------------------------------------------
# Rapport Markdown
# ---------------------------------------------------------------------------

def format_kmh_pace(kmh: float) -> str:
    if kmh <= 0:
        return "—"
    return f"{60 / kmh * 60:.0f}:{((60 / kmh) * 60 % 60 * 60 / 60):02.0f}".replace(":", ":")


def build_report(name: str, m: dict, climbs: list[dict], target: dict) -> str:
    km = m["distance_m"] / 1000
    lines = [f"# Analyse parcours GPX — {name or 'Parcours'}", ""]
    lines.append(f"**Fichier analysé :** distance réelle **{km:.1f} km** · D+ **{m['elevation_gain_m']:.0f} m** · "
                 f"D- **{m['elevation_loss_m']:.0f} m** · alt {m['alt_min']} → {m['alt_max']} m · "
                 f"**{'boucle fermée' if m['is_loop'] else 'point-to-point'}** · {m['points']} points GPS")
    lines.append("")

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
    ap.add_argument("--min-climb-dist", type=float, default=100.0, help="Distance min d'une montée (m)")
    ap.add_argument("--output", type=Path, default=None, help="Fichier Markdown de sortie (défaut stdout)")
    ap.add_argument("--json", type=Path, default=None, help="Fichier JSON de sortie")
    ap.add_argument("--quiet", action="store_true", help="N'affiche que les erreurs")
    args = ap.parse_args(argv)

    if not args.gpx.exists():
        print(f"ERREUR : fichier GPX introuvable — {args.gpx}", file=sys.stderr)
        return 1

    pts = parse_gpx(args.gpx)
    if not pts:
        print(f"ERREUR : aucun point trkpt dans {args.gpx}", file=sys.stderr)
        return 1

    m = compute_metrics(pts, smooth=args.smooth)
    climbs = detect_climbs(pts, m, min_gain=args.min_gain, min_dist=args.min_climb_dist)

    target = {}
    if args.target_distance:
        lo, hi = args.target_distance.split("-")
        target["distance"] = (float(lo), float(hi))
    if args.target_dp:
        target["dp"] = args.target_dp

    report = build_report(args.name, m, climbs, target)

    if args.json:
        dump = {
            "name": args.name,
            "metrics": {k: v for k, v in m.items() if k != "km_profile"},
            "km_profile": m["km_profile"],
            "climbs": climbs,
            "target": target,
        }
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