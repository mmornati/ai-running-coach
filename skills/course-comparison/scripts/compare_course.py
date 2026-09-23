#!/usr/bin/env python3
"""
compare_course.py — Analyse comparative générique de séances sur un même lieu/parcours.

Objectif
--------
Comparer des séances de trail/course à pied enregistrées sur le MÊME parcours
(ou lieu) à des dates différentes, en alignant les segments comparables
(premier tour, montées, splits km) et en produisant un rapport Markdown.

Le script travaille sur les fichiers Markdown déjà persistés dans `activities/`
(convention `YYYY-MM-DD_type.md`, bloc `## Données brutes Garmin (référence)`
+ tableau `## Analyse par splits (km)`). Il est conçu pour être piloté par
l'agent coach après un sync Garmin (voir le skill `course-comparison`).

Usage
-----
    python3 skills/course-comparison/scripts/compare_course.py \
        --lieu "Tournai" \
        --ref 2026-08-22 \
        --aliases "Tournai Trail" "Tournai - Sortie" \
        --loop-length 10 \
        --tolerance 50 \
        --output /tmp/comparaison_tournai.md

Paramètres génériques
---------------------
    --lieu           Lieu / parcours à matcher (regex ou texte, insensible à la casse)
    --aliases        Noms alternatifs du parcours (ex. "Tournai Trail", "Trail de Tournai")
    --ref            Date de la séance de référence (YYYY-MM-DD) — alignement sur elle
    --dates          Plage de dates optionnelle "YYYY-MM-DD:YYYY-MM-DD"
    --loop-length    Longueur de boucle en km (ex. 10). Si absent → auto-détection
                     par corrélation du profil de D+ cumulé.
    --tolerance      Tolérance d'alignement en mètres (défaut 50 m)
    --min-climb      Seuil de détection d'une "montée" en m D+ sur 1 km (défaut 40 m)
    --dir            Dossier des activités (défaut activities/)
    --output         Fichier Markdown de sortie (défaut stdout)
    --json           Fichier JSON de sortie (dump structuré, réutilisable)

Sortie
------
- Tableau comparatif global (distance, durée, allure, D+, FC moy/max, HRR, TE)
- Alignement des tours (si boucle détectée ou --loop-length fourni)
- Détection et comparaison des montées (> --min-climb sur 1 km)
- Verdict automatique : progression / régression sur segments comparables

Prérequis
---------
- Python 3.8+ (stdlib uniquement, aucune dépendance externe)
- Les fichiers MD doivent contenir le bloc YAML de référence ET le tableau de
  splits km (format produit par le sync Garmin du coach). Un fichier sans ces
  blocs est ignoré avec un warning.
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Moteur : scripts/ à la racine (le skill peut être atteint par un lien symbolique
# depuis un workspace séparé — resolve() remonte au vrai dossier du moteur).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import arc_contract as C  # noqa: E402
from arc_legacy import parse_split_time, parse_splits_table, parse_yaml_block  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Parsing des fichiers MD
# ---------------------------------------------------------------------------

def parse_duration(seconds: float) -> str:
    """Formate des secondes en HH:MM:SS (ou MM:SS si < 1h)."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_pace(seconds_per_km: float) -> str:
    """Formate une allure en secondes/km vers MM:SS/km."""
    if not seconds_per_km or seconds_per_km <= 0:
        return "—"
    m, s = divmod(int(round(seconds_per_km)), 60)
    return f"{m}:{s:02d}/km"


def parse_activity_file(path: str) -> Optional[Dict[str, Any]]:
    """Parse un fichier MD d'activité → dict structuré (ou None si inexploitable)."""
    fname = os.path.basename(path)
    mdate = re.match(r"(\d{4}-\d{2}-\d{2})_", fname)
    if not mdate:
        return None
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    act = _from_arc_block(path, text)
    if act is not None:
        return _fill_from_splits(act)
    yaml_data = parse_yaml_block(text)
    splits = parse_splits_table(text)
    # extraction du lieu et du nom (fallback si pas de YAML)
    lieu_m = re.search(r"\*\*Lieu :\*\*\s*(.+)", text)
    name_m = re.search(r"\*\*Activité Garmin :\*\*\s*.*?`([^`]+)`", text)
    title_m = re.match(r"#\s+(.+)", text)
    act = {
        "file": path,
        "date": mdate.group(1),
        "name": (name_m.group(1) if name_m else (title_m.group(1) if title_m else fname)),
        "lieu": lieu_m.group(1).strip() if lieu_m else "",
        "splits": splits,
    }
    act.update(yaml_data)
    return _fill_from_splits(act)


def _from_arc_block(path: str, text: str) -> Optional[Dict[str, Any]]:
    """Activité lue dans le bloc ```arc (contrat `workspace-data-contract`), ou None.

    Le bloc a des clés fixes en anglais : la comparaison ne dépend plus des titres
    français (`## Données brutes Garmin (référence)`) ni de l'ordre des colonnes.
    """
    try:
        block = C.extract_block(text)
    except C.ContractError:
        return None
    if not block or block.get("kind") != "activity" or C.validate(block)[0]:
        return None
    splits = [
        {"num": row["km"], "duration_s": row["duration_s"],
         "dplus_m": row.get("elev_gain_m") or 0.0, "dminus_m": row.get("elev_loss_m") or 0.0,
         "hr_avg_bpm": row.get("avg_hr_bpm")}
        for row in C.split_rows(block) if row.get("km") is not None and row.get("duration_s") is not None
    ]
    return {
        "file": path, "date": block["date"], "name": block.get("name") or os.path.basename(path),
        "lieu": block.get("location") or "", "splits": splits,
        "activity_id": block.get("garmin_activity_id"),
        "distance_m": block.get("distance_m"), "duration_s": block.get("duration_s"),
        "elevation_gain_m": block.get("elevation_gain_m"), "elevation_loss_m": block.get("elevation_loss_m"),
        "avg_hr_bpm": block.get("avg_hr_bpm"), "max_hr_bpm": block.get("max_hr_bpm"),
        "recovery_hr_bpm": block.get("recovery_hr_bpm"),
        "training_effect": block.get("training_effect_aerobic"),
        # D+ absent des splits (profil d'altitude non enregistré) : inconnu, pas 0.
        "_elev_known": any(r.get("elev_gain_m") is not None for r in C.split_rows(block)),
    }


def _fill_from_splits(act: Dict[str, Any]) -> Dict[str, Any]:
    splits = act.get("splits") or []
    # distance / durée / D+ : priorité aux données de séance, repli sur les splits
    if act.get("distance_m") is None and splits:
        act["distance_m"] = float(len(splits)) * 1000.0
    if act.get("duration_s") is None and splits:
        act["duration_s"] = float(sum(s["duration_s"] for s in splits))
    elev_known = act.pop("_elev_known", True)
    if act.get("elevation_gain_m") is None and splits and elev_known:
        act["elevation_gain_m"] = float(sum(s["dplus_m"] for s in splits))
    if act.get("elevation_loss_m") is None and splits and elev_known:
        act["elevation_loss_m"] = float(sum(s["dminus_m"] for s in splits))
    return act


# ---------------------------------------------------------------------------
# Découverte des activités d'un lieu
# ---------------------------------------------------------------------------

def match_lieu(act: Dict[str, Any], patterns: List[str]) -> bool:
    """Vrai si l'activité correspond à l'un des patterns (lieu ou nom)."""
    haystack = f"{act.get('lieu','')} {act.get('name','')}".lower()
    for p in patterns:
        if not p:
            continue
        if p.lower() in haystack:
            return True
        try:
            if re.search(p.lower(), haystack):
                return True
        except re.error:
            continue        # pas une regex valide : le texte littéral a déjà été essayé
    return False


def discover_activities(activities_dir: str, patterns: List[str],
                        date_start: Optional[str] = None,
                        date_end: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retourne les activités du lieu, triées par date croissante."""
    out: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(activities_dir, "*.md"))):
        act = parse_activity_file(path)
        if not act:
            continue
        if not match_lieu(act, patterns):
            continue
        if date_start and act["date"] < date_start:
            continue
        if date_end and act["date"] > date_end:
            continue
        out.append(act)
    out.sort(key=lambda a: a["date"])
    return out


# ---------------------------------------------------------------------------
# Alignement des segments / tours
# ---------------------------------------------------------------------------

def cumulative_profile(splits: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    """Profil cumulé par split : distance (m), temps (s), D+ (m), D- (m)."""
    dist, time, dplus, dminus = [], [], [], []
    d = t = p = m = 0.0
    for s in splits:
        d += 1000.0
        t += s["duration_s"]
        p += s["dplus_m"]
        m += s["dminus_m"]
        dist.append(d)
        time.append(t)
        dplus.append(p)
        dminus.append(m)
    return {"dist": dist, "time": time, "dplus": dplus, "dminus": dminus}


def detect_loop_length(act: Dict[str, Any], other_acts: Optional[List[Dict[str, Any]]] = None) -> Optional[float]:
    """Auto-détection de la longueur de boucle (km).

    Stratégie (robuste) :
    1. Corrélation de Pearson sur le profil D+ PAR km (stationnaire) entre
       [0, N-L] et [L, N], avec contrainte "L diviseur approximatif de la
       distance totale" (une boucle se reproduit un nombre entier de fois).
    2. Fallback : si d'autres séances du même parcours existent, la plus
       courte distance (arrondie au km) est une bonne estimée de la boucle,
       à condition qu'elle divise approximativement la distance de référence.
    3. Sinon → None (comparaison sur la séance entière).
    """
    splits = act.get("splits") or []
    if len(splits) < 8:
        return None
    dplus_per_km = [s["dplus_m"] for s in splits]
    total_km = len(splits)

    def pearson(a: List[float], b: List[float]) -> float:
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        da = (sum((x - ma) ** 2 for x in a)) ** 0.5
        db = (sum((y - mb) ** 2 for y in b)) ** 0.5
        if da == 0 or db == 0:
            return 0.0
        return num / (da * db)

    best_L, best_score = None, 0.0
    for L in range(3, min(31, total_km // 2 + 1)):
        a = dplus_per_km[: total_km - L]
        b = dplus_per_km[L:]
        if len(a) < 3:
            break
        mult = total_km / L
        div_ok = abs(mult - round(mult)) / mult < 0.12
        r = pearson(a, b)
        score = r if div_ok else r * 0.5
        if score > best_score:
            best_score, best_L = score, L
    if best_L and best_score > 0.45:
        return float(best_L)

    # Fallback : longueur de boucle commune qui divise le mieux plusieurs
    # séances du parcours (ex. 10 km pour les boucles Tournai : 2 × 10, 3 × 10…)
    candidates = []
    all_seances = [act] + (other_acts or [])
    for L in range(5, 26):
        compat, errs = 0, []
        for o in all_seances:
            o_total = len(o.get("splits") or [])
            if o_total < 8:
                continue
            mult = o_total / L
            if mult < 0.85:  # au moins ~1 boucle (tolère la séance la plus courte)
                continue
            err = abs(mult - round(mult)) / max(mult, 1.0)
            if err > 0.15:
                continue
            compat += 1
            errs.append(err)
        if compat >= 3:  # au moins 3 séances compatibles avec cette boucle
            candidates.append((sum(errs) / len(errs), compat, L))
    # Sélection : priorité à l'erreur moyenne faible, puis au PLUS GRAND L
    # (la vraie boucle est la plus longue compatible, ex. 10 km pour Tournai)
    if candidates:
        candidates.sort(key=lambda x: (x[0], -x[1]))
        if candidates[0][0] <= 0.12:
            valid = [c for c in candidates if c[0] <= 0.12]
            valid.sort(key=lambda c: (-c[1], c[0]))
            # parmi les meilleures erreurs, privilégier le plus grand L
            best_err = valid[0][0]
            best = max((c for c in valid if c[0] <= best_err + 0.02), key=lambda c: c[2])
            return float(best[2])
    return None


def build_loops(act: Dict[str, Any], loop_length_km: Optional[float]) -> List[Dict[str, Any]]:
    """Découpe l'activité en tours de `loop_length_km` km (ou auto-détecté)."""
    splits = act.get("splits") or []
    if not splits:
        return []
    if loop_length_km is None:
        loop_length_km = detect_loop_length(act) or (len(splits))
    loops: List[Dict[str, Any]] = []
    cur = {"km_start": 0, "duration_s": 0.0, "dplus_m": 0.0, "dminus_m": 0.0,
           "hr_sum": 0.0, "hr_n": 0, "splits": []}
    for i, s in enumerate(splits):
        cur["duration_s"] += s["duration_s"]
        cur["dplus_m"] += s["dplus_m"]
        cur["dminus_m"] += s["dminus_m"]
        if s.get("hr_avg_bpm") is not None:
            cur["hr_sum"] += s["hr_avg_bpm"]
            cur["hr_n"] += 1
        cur["splits"].append(s)
        if (i + 1) % int(round(loop_length_km)) == 0:
            cur["km_end"] = i + 1
            cur["distance_km"] = float(cur["km_end"] - cur["km_start"])
            cur["hr_avg_bpm"] = cur["hr_sum"] / cur["hr_n"] if cur["hr_n"] else None
            cur["pace_spkm"] = cur["duration_s"] / cur["distance_km"] if cur["distance_km"] else 0
            loops.append(cur)
            cur = {"km_start": i + 1, "duration_s": 0.0, "dplus_m": 0.0, "dminus_m": 0.0,
                   "hr_sum": 0.0, "hr_n": 0, "splits": []}
    # dernier tour partiel
    if cur["splits"]:
        cur["km_end"] = len(splits)
        cur["distance_km"] = cur["km_end"] - cur["km_start"]
        cur["hr_avg_bpm"] = cur["hr_sum"] / cur["hr_n"] if cur["hr_n"] else None
        cur["pace_spkm"] = cur["duration_s"] / cur["distance_km"] if cur["distance_km"] else 0
        loops.append(cur)
    return loops


def detect_climbs(act: Dict[str, Any], min_climb_m: float) -> List[Dict[str, Any]]:
    """Détecte les montées : splits avec D+ ≥ min_climb_m."""
    out = []
    for i, s in enumerate(act.get("splits") or []):
        if s["dplus_m"] >= min_climb_m:
            out.append({
                "km": s["num"],
                "dplus_m": s["dplus_m"],
                "duration_s": s["duration_s"],
                "hr_avg_bpm": s.get("hr_avg_bpm"),
                "pace_spkm": s["duration_s"],  # split = ~1 km
            })
    return out


# ---------------------------------------------------------------------------
# Rapport Markdown
# ---------------------------------------------------------------------------

def _fmt_pace(spkm: float) -> str:
    return parse_pace(spkm)


def _fmt_hr(v: Optional[float]) -> str:
    return f"{v:.0f}" if v is not None else "—"


def render_report(ref: Dict[str, Any], others: List[Dict[str, Any]],
                  loop_length_km: Optional[float], tolerance_m: int,
                  min_climb_m: float) -> str:
    """Génère le rapport Markdown comparatif (FRENCH)."""
    L = []
    L.append(f"# Comparaison de parcours — {ref.get('lieu') or ref.get('name')}")
    L.append("")
    L.append(f"**Séance de référence :** {ref['date']} — {ref.get('name')}")
    L.append(f"**Séances comparées :** {', '.join(o['date'] for o in others) if others else 'aucune'}")
    L.append("")
    L.append(f"_Alignement : boucle {loop_length_km if loop_length_km else 'auto-détectée'} km · "
             f"tolérance {tolerance_m} m · montée ≥ {min_climb_m:.0f} m D+/km_")
    L.append("")

    # --- Tableau global ---
    L.append("## 1. Comparaison globale")
    L.append("")
    L.append("| Séance | Distance | Durée | Allure moy | D+ | D- | FC moy | FC max | HRR | TE |")
    L.append("|:--------|---------:|------:|:----------:|----:|----:|-------:|-------:|----:|---:|")
    all_acts = [ref] + others
    for a in all_acts:
        dist = (a.get("distance_m") or 0) / 1000.0
        dur = a.get("duration_s") or 0
        dplus = a.get("elevation_gain_m")
        dminus = a.get("elevation_loss_m")
        hr_avg = a.get("avg_hr_bpm")
        hr_max = a.get("max_hr_bpm")
        hrr = a.get("recovery_hr_bpm")
        te = a.get("training_effect")
        pace = dur / dist if dist else 0
        L.append(f"| {a['date']} | {dist:.1f} km | {parse_duration(dur)} | {_fmt_pace(pace)} "
                 f"| {'—' if dplus is None else f'{dplus:.0f}'} | {'—' if dminus is None else f'{dminus:.0f}'} "
                 f"| {_fmt_hr(hr_avg)} | {_fmt_hr(hr_max)} "
                 f"| {hrr if hrr is not None else '—'} | {te if te is not None else '—'} |")
    L.append("")

    # --- Alignement des tours ---
    L.append("## 2. Alignement des tours (segments comparables)")
    L.append("")
    ref_loops = build_loops(ref, loop_length_km)
    other_loops = [build_loops(o, loop_length_km) for o in others]
    n_loops = max(len(ref_loops), *(len(x) for x in other_loops)) if other_loops else len(ref_loops)
    if n_loops:
        L.append("| Tour | Séance | Km | Durée | Allure moy | D+ | FC moy |")
        L.append("|:-----|:-------|:--:|------:|:----------:|:--:|-------:|")
        for i in range(n_loops):
            rows = []
            if i < len(ref_loops):
                r = ref_loops[i]
                rows.append(("**" + ref["date"] + "**", f"{r['km_start']+1}-{r['km_end']}",
                             parse_duration(r["duration_s"]), _fmt_pace(r["pace_spkm"]),
                             f"{r['dplus_m']:.0f}", _fmt_hr(r["hr_avg_bpm"])))
            for o, loops in zip(others, other_loops):
                if i < len(loops):
                    r = loops[i]
                    rows.append((o["date"], f"{r['km_start']+1}-{r['km_end']}",
                                 parse_duration(r["duration_s"]), _fmt_pace(r["pace_spkm"]),
                                 f"{r['dplus_m']:.0f}", _fmt_hr(r["hr_avg_bpm"])))
            for j, (sdate, km, dur, pace, dp, hr) in enumerate(rows):
                prefix = "| **T" + str(i + 1) + "** |" if j == 0 else "| |"
                L.append(f"{prefix} {sdate} | {km} | {dur} | {pace} | {dp} | {hr} |")
        L.append("")

    # --- Montées ---
    L.append(f"## 3. Montées comparables (≥ {min_climb_m:.0f} m D+/km)")
    L.append("")
    climbs_ref = detect_climbs(ref, min_climb_m)
    climbs_others = [detect_climbs(o, min_climb_m) for o in others]
    if climbs_ref or any(climbs_others):
        L.append("| Séance | Montée (km) | D+ | Durée | Allure | FC moy |")
        L.append("|:-------|:-----------:|:--:|------:|:------:|-------:|")
        all_c = [(ref["date"], climbs_ref)] + [(o["date"], c) for o, c in zip(others, climbs_others)]
        for sdate, climbs in all_c:
            if not climbs:
                L.append(f"| {sdate} | — | — | — | — | — |")
                continue
            for c in climbs:
                L.append(f"| {sdate} | km {c['km']} | {c['dplus_m']:.0f} m | "
                         f"{parse_duration(c['duration_s'])} | {_fmt_pace(c['pace_spkm'])} | "
                         f"{_fmt_hr(c['hr_avg_bpm'])} |")
        L.append("")

    # --- Verdict ---
    L.append("## 4. Verdict automatique")
    L.append("")
    if others:
        ref_pace = (ref.get("duration_s") or 0) / ((ref.get("distance_m") or 0) / 1000.0) if (ref.get("distance_m") or 0) else 0
        for o in others:
            o_pace = (o.get("duration_s") or 0) / ((o.get("distance_m") or 0) / 1000.0) if (o.get("distance_m") or 0) else 0
            ref_fc = ref.get("avg_hr_bpm")
            o_fc = o.get("avg_hr_bpm")
            pace_delta = ((ref_pace - o_pace) / o_pace * 100) if o_pace else 0
            fc_delta = (ref_fc - o_fc) if (ref_fc and o_fc) else None
            verdict_pace = "plus rapide" if pace_delta < 0 else ("plus lent" if pace_delta > 0 else "égal")
            fc_txt = ""
            if fc_delta is not None:
                if abs(fc_delta) < 3:
                    fc_txt = "FC équivalente"
                elif fc_delta < 0:
                    fc_txt = f"FC inférieure de {-fc_delta:.0f} bpm (meilleure gestion)"
                else:
                    fc_txt = f"FC supérieure de {fc_delta:.0f} bpm"
            L.append(f"- **{ref['date']} vs {o['date']} :** allure {verdict_pace} de "
                     f"{abs(pace_delta):.1f} % ({_fmt_pace(ref_pace)} vs {_fmt_pace(o_pace)}) — {fc_txt}.")
        L.append("")
        L.append("> ⚠️ Verdict indicatif : à confirmer par l'analyse coach (contexte, fatigue, "
                 "dénivelé réel, conditions météo, blessure).")
    else:
        L.append("Aucune autre séance trouvée sur ce parcours dans la plage donnée.")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compare des séances sur un même parcours (fichiers MD activities/).")
    ap.add_argument("--lieu", required=True, help="Lieu/parcours (regex ou texte)")
    ap.add_argument("--aliases", nargs="*", default=[],
                    help="Noms alternatifs du parcours (ex. 'Tournai Trail')")
    ap.add_argument("--ref", required=True, help="Date de référence YYYY-MM-DD")
    ap.add_argument("--dates", default=None,
                    help="Plage de dates 'YYYY-MM-DD:YYYY-MM-DD' (optionnel)")
    ap.add_argument("--exclude-dates", nargs="*", default=[],
                    help="Dates à exclure (YYYY-MM-DD, répétable)")
    ap.add_argument("--loop-length", type=float, default=None,
                    help="Longueur de boucle en km (défaut: auto-détection)")
    ap.add_argument("--tolerance", type=int, default=50,
                    help="Tolérance d'alignement en mètres (défaut 50)")
    ap.add_argument("--min-climb", type=float, default=40.0,
                    help="Seuil montée en m D+ sur 1 km (défaut 40)")
    ap.add_argument("--dir", default="activities", help="Dossier des activités")
    ap.add_argument("--output", default=None, help="Fichier Markdown de sortie")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="Fichier JSON de sortie (dump structuré)")
    args = ap.parse_args(argv)

    base_dir = args.dir
    if not os.path.isdir(base_dir):
        # fallback: relatif au workspace si lancé depuis le skill
        for cand in ("../activities", "activities"):
            if os.path.isdir(cand):
                base_dir = cand
                break
        else:
            print(f"ERREUR: dossier introuvable: {args.dir}", file=sys.stderr)
            return 2

    patterns = [args.lieu] + args.aliases
    date_start = date_end = None
    if args.dates and ":" in args.dates:
        date_start, date_end = args.dates.split(":", 1)
        date_start = date_start.strip() or None
        date_end = date_end.strip() or None

    acts = discover_activities(base_dir, patterns, date_start, date_end)
    if not acts:
        print(f"Aucune activité trouvée pour le lieu '{args.lieu}' dans {base_dir}.",
              file=sys.stderr)
        return 1

    ref = next((a for a in acts if a["date"] == args.ref), None)
    if ref is None:
        print(f"Séance de référence {args.ref} introuvable. Disponibles: "
              + ", ".join(a["date"] for a in acts), file=sys.stderr)
        return 1
    others = [a for a in acts if a["date"] != args.ref
              and a["date"] not in (args.exclude_dates or [])]

    if args.loop_length is None:
        detected = detect_loop_length(ref, others)
        loop_len = detected
    else:
        loop_len = args.loop_length

    report = render_report(ref, others, loop_len, args.tolerance, args.min_climb)

    if args.json_out:
        payload = {
            "lieu": args.lieu,
            "reference": ref["date"],
            "loop_length_km": loop_len,
            "activities": [
                {
                    "date": a["date"],
                    "name": a.get("name"),
                    "distance_km": round((a.get("distance_m") or 0) / 1000.0, 2),
                    "duration_s": a.get("duration_s"),
                    "elevation_gain_m": a.get("elevation_gain_m"),
                    "avg_hr_bpm": a.get("avg_hr_bpm"),
                    "max_hr_bpm": a.get("max_hr_bpm"),
                    "recovery_hr_bpm": a.get("recovery_hr_bpm"),
                    "training_effect": a.get("training_effect"),
                    "climbs": detect_climbs(a, args.min_climb),
                }
                for a in [ref] + others
            ],
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"Rapport écrit dans {args.output}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())