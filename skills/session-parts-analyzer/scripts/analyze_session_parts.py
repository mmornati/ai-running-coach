#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_session_parts.py
========================

Detect and analyze specific portions of a Garmin running/trail session
(strides/lignes droites, climbs, sprints, intervals, cooldowns, custom
speed/HR/elevation windows) and report per-segment execution metrics.

Two input modes
---------------
1. **FIT file** (recommended, second-by-second records):
   python analyze_session_parts.py --fit path/to/activity.FIT --part stride
2. **Garmin MCP JSON** (splits only, 1 km granularity; less precise but
   works without the binary file):
   python analyze_session_parts.py --activity-id 24059541901 --part stride \
       --garmin-host http://localhost:8080

Outputs
-------
- Markdown table to stdout (or to --output file)
- JSON dump to --json file (optional) for downstream reuse
- Exit code 0 on success, 1 on no segment detected, 2 on input error

Author: Trail Running Coach skill — sport-workspace / opencode
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

# Moteur : scripts/ à la racine (le skill peut être atteint par un lien symbolique
# depuis un workspace séparé — resolve() remonte au vrai dossier du moteur).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import arc_climb  # noqa: E402
import arc_samples  # noqa: E402

# Résolution des échantillons passés au détecteur de montées — celle de l'index
# (`arc_samples.DEFAULT_RESOLUTION_S`), pour des bornes identiques à #46/#49.
CLIMB_RESOLUTION_S = arc_samples.DEFAULT_RESOLUTION_S

# ---------------------------------------------------------------------------
# Default thresholds — tunable via CLI flags
# ---------------------------------------------------------------------------

DEFAULTS = {
    # Stride / ligne droite detection
    "stride_speed_threshold_kmh": 12.0,   # pic min pour entrer dans une LD
    "stride_min_duration_s": 8,           # durée min du pic
    "stride_max_duration_s": 30,          # durée max du pic (au-delà = sprint)
    "stride_recovery_speed_kmh": 9.5,     # vitesse max pendant la récup
    "stride_recovery_min_s": 60,          # durée min de récup entre 2 LD
    "stride_recovery_max_s": 180,         # durée max (au-delà, fin du bloc LD)
    "stride_distance_min_m": 60,          # distance min d'une LD (~80 m cible)
    "stride_distance_max_m": 160,         # distance max d'une LD (~120 m cible)
    # Climb detection (moteur : scripts/arc_climb.py::detect_climbs)
    "climb_grade_min_pct": 4.0,           # pente moyenne min (gain net / distance)
    # 150 m (250 m avant la migration vers le moteur) : les bornes rognées du moteur
    # sont plus courtes que l'ancienne fenêtre « pente instantanée ≥ seuil » — une
    # côte de 300 m (drill de côtes) doit rester détectée.
    "climb_min_distance_m": 150,
    "climb_min_ascent_m": 15,             # gain net min (altitude lissée)
    # Sprint / interval
    "sprint_speed_threshold_kmh": 15.0,
    "sprint_min_duration_s": 4,
    "sprint_max_duration_s": 12,
    # Smoothing
    "speed_smooth_window_s": 5,
    # HR color (compared to segment average)
    "hr_drift_alert_bpm": 10,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Record:
    """One second-by-second sample of the activity."""
    t: float          # seconds since session start
    distance_m: float  # cumulative distance, meters
    speed_kmh: float   # instantaneous speed (smoothed)
    hr: Optional[int]  # bpm
    elevation_m: Optional[float]
    grade_pct: Optional[float]
    cadence: Optional[int]
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class Segment:
    """A detected portion of the session (stride, climb, etc.)."""
    kind: str
    index: int
    start_t: float
    end_t: float
    duration_s: float
    distance_m: float
    avg_speed_kmh: float
    max_speed_kmh: float
    avg_hr_bpm: Optional[float]
    max_hr_bpm: Optional[int]
    hr_before_bpm: Optional[float]  # avg HR over N seconds before start
    hr_after_bpm: Optional[float]   # avg HR over N seconds after end
    elevation_gain_m: float
    avg_grade_pct: Optional[float]
    recovery_before_s: Optional[float]  # gap from previous segment of same kind
    cadence_avg: Optional[float]
    flags: List[str] = field(default_factory=list)
    # Montées seulement (`None` ailleurs) — voir `arc_climb.detect_climbs`.
    grade_class: Optional[str] = None
    vam_elapsed_m_h: Optional[float] = None
    vam_moving_m_h: Optional[float] = None

    @property
    def delta_hr_in(self) -> Optional[float]:
        if self.hr_before_bpm is None or self.avg_hr_bpm is None:
            return None
        return round(self.avg_hr_bpm - self.hr_before_bpm, 1)

    @property
    def delta_hr_out(self) -> Optional[float]:
        if self.hr_after_bpm is None or self.avg_hr_bpm is None:
            return None
        return round(self.hr_after_bpm - self.avg_hr_bpm, 1)

    def to_row(self) -> List[str]:
        def fmt(x, n=1):
            if x is None:
                return "—"
            if isinstance(x, float):
                return f"{x:.{n}f}"
            return str(x)
        return [
            f"#{self.index}",
            f"{self.start_t:.0f}–{self.end_t:.0f}",
            f"{self.duration_s:.1f}",
            f"{self.distance_m:.0f}",
            f"{self.avg_speed_kmh:.1f}",
            f"{self.max_speed_kmh:.1f}",
            fmt(self.hr_before_bpm, 0),
            fmt(self.avg_hr_bpm, 0),
            fmt(self.hr_after_bpm, 0),
            fmt(self.cadence_avg, 0),
            f"{self.elevation_gain_m:+.0f}",
            " | ".join(self.flags) if self.flags else "✅",
        ]


# ---------------------------------------------------------------------------
# FIT loader
# ---------------------------------------------------------------------------

def load_records_from_fit(fit_path: Path) -> List[Record]:
    """Parse a Garmin FIT file and return per-second Records."""
    try:
        from fitparse import FitFile
    except ImportError as exc:
        raise SystemExit(
            "Le module 'fitparse' est requis pour lire les FIT. "
            "Installe-le avec : pip install fitparse"
        ) from exc

    fit = FitFile(str(fit_path))
    records_raw: List[dict] = []
    for msg in fit.get_messages("record"):
        d = {fld.name: fld.value for fld in msg.fields}
        records_raw.append(d)

    if not records_raw:
        raise SystemExit(f"Aucun record trouvé dans {fit_path}")

    # Distance is cumulative in FIT; if missing, fall back to integration
    have_dist = "distance" in records_raw[0]
    # Garmin FIT files commonly use "enhanced_speed" (m/s) instead of legacy "speed".
    have_speed = "speed" in records_raw[0] or "enhanced_speed" in records_raw[0]

    # Time anchor
    t0 = None
    out: List[Record] = []
    cum_dist = 0.0
    last_lat = None
    last_lon = None

    for i, r in enumerate(records_raw):
        ts = r.get("timestamp")
        if t0 is None:
            t0 = ts
        t = (ts - t0).total_seconds() if ts else float(i)

        # Speed (prefer "speed", fall back to "enhanced_speed")
        speed_mps = r.get("speed")
        if speed_mps is None:
            speed_mps = r.get("enhanced_speed")
        if speed_mps is None:
            # fall back to integration over 1 s
            speed_mps = 0.0
        speed_kmh = speed_mps * 3.6

        # Distance
        if have_dist and r.get("distance") is not None:
            cum_dist = float(r["distance"])
        else:
            cum_dist += float(speed_mps)

        # Grade
        grade = r.get("grade")  # Garmin stores %
        if grade is None:
            grade = None

        hr = r.get("heart_rate")
        ele = r.get("enhanced_altitude") or r.get("altitude")
        cad = r.get("cadence")
        lat = r.get("position_lat")
        lon = r.get("position_long")

        # Semicircles → degrees
        if lat is not None and abs(lat) > 360:
            lat = lat * (180.0 / 2**31)
        if lon is not None and abs(lon) > 360:
            lon = lon * (180.0 / 2**31)

        out.append(Record(
            t=t, distance_m=cum_dist, speed_kmh=speed_kmh,
            hr=int(hr) if hr is not None else None,
            elevation_m=float(ele) if ele is not None else None,
            grade_pct=float(grade) if grade is not None else None,
            cadence=int(cad) if cad is not None else None,
            lat=lat, lon=lon,
        ))
    return out


# ---------------------------------------------------------------------------
# Smoothing
# ---------------------------------------------------------------------------

def smooth_speed(records: Sequence[Record], window_s: int = 5) -> None:
    """In-place moving average over the last `window_s` seconds."""
    if window_s <= 1:
        return
    speeds = [r.speed_kmh for r in records]
    n = len(records)
    half = window_s // 2
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        records[i].speed_kmh = sum(speeds[lo:hi]) / (hi - lo)


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def detect_strides(records: Sequence[Record], cfg: dict) -> List[Segment]:
    """
    Detect "lignes droites" (strides): a short burst where speed jumps
    above `stride_speed_threshold_kmh` for `stride_min_duration_s` to
    `stride_max_duration_s` seconds, followed by a recovery window where
    speed drops under `stride_recovery_speed_kmh` for at least
    `stride_recovery_min_s` seconds.

    Implementation:
    1. Locate candidate "burst" intervals where smoothed speed > threshold
       and duration is in [min, max] range.
    2. Merge bursts < min into neighbors; split bursts > max.
    3. Validate distance window.
    4. Require a recovery window of `recovery_min_s` < gap < recovery_max_s`
       after the burst to confirm it as a stride.
    """
    thr_high = cfg["stride_speed_threshold_kmh"]
    thr_low = cfg["stride_recovery_speed_kmh"]
    min_d = cfg["stride_min_duration_s"]
    max_d = cfg["stride_max_duration_s"]
    min_rec = cfg["stride_recovery_min_s"]
    max_rec = cfg["stride_recovery_max_s"]
    min_dist = cfg["stride_distance_min_m"]
    max_dist = cfg["stride_distance_max_m"]

    bursts: List[tuple] = []  # (start_idx, end_idx_exclusive)
    n = len(records)
    i = 0
    while i < n:
        if records[i].speed_kmh >= thr_high:
            j = i
            while j < n and records[j].speed_kmh >= thr_high:
                j += 1
            burst_len = records[j - 1].t - records[i].t
            if min_d <= burst_len <= max_d:
                bursts.append((i, j))
            i = j
        else:
            i += 1

    # If no burst matches the strict window, also accept very short bursts
    # (single GPS spike) but flag them.
    if not bursts:
        i = 0
        while i < n:
            if records[i].speed_kmh >= thr_high:
                j = i
                while j < n and records[j].speed_kmh >= thr_high:
                    j += 1
                bursts.append((i, j))
                i = j
            else:
                i += 1

    segments: List[Segment] = []
    for idx, (a, b) in enumerate(bursts, start=1):
        start_t = records[a].t
        end_t = records[b - 1].t
        duration = end_t - start_t
        dist_start = records[a].distance_m
        dist_end = records[b - 1].distance_m
        distance = dist_end - dist_start
        speeds = [r.speed_kmh for r in records[a:b]]
        hrs = [r.hr for r in records[a:b] if r.hr is not None]
        max_speed = max(speeds) if speeds else 0.0
        avg_speed = sum(speeds) / len(speeds) if speeds else 0.0
        avg_hr = sum(hrs) / len(hrs) if hrs else None
        max_hr = max(hrs) if hrs else None

        # HR before/after (10 s window each side)
        hr_before = _avg_hr_window(records, a, look_back=10)
        hr_after = _avg_hr_window(records, b - 1, look_fwd=10)

        # Recovery before: gap to previous burst
        recovery_before = None
        if segments:
            prev_end_t = segments[-1].end_t
            recovery_before = start_t - prev_end_t

        # Elevation
        e0 = records[a].elevation_m
        e1 = records[b - 1].elevation_m
        elev_gain = (e1 - e0) if (e0 is not None and e1 is not None) else 0.0

        # Cadence
        cads = [r.cadence for r in records[a:b] if r.cadence]
        cad_avg = sum(cads) / len(cads) if cads else None

        flags: List[str] = []
        if distance < min_dist or distance > max_dist:
            flags.append(f"distance_hors_cible ({distance:.0f} m)")
        if max_speed > thr_high + 3.5:
            flags.append(f"pic_trop_eleve ({max_speed:.1f} km/h)")
        if avg_speed > thr_high + 1.0:
            flags.append("acceleration_trop_brutale")
        if recovery_before is not None and recovery_before < min_rec:
            flags.append(f"recup_courte ({recovery_before:.0f}s)")
        elif recovery_before is not None and recovery_before > max_rec:
            flags.append(f"recup_trop_longue ({recovery_before:.0f}s)")

        segments.append(Segment(
            kind="stride",
            index=idx,
            start_t=start_t,
            end_t=end_t,
            duration_s=duration,
            distance_m=distance,
            avg_speed_kmh=avg_speed,
            max_speed_kmh=max_speed,
            avg_hr_bpm=avg_hr,
            max_hr_bpm=max_hr,
            hr_before_bpm=hr_before,
            hr_after_bpm=hr_after,
            elevation_gain_m=elev_gain,
            avg_grade_pct=None,
            recovery_before_s=recovery_before,
            cadence_avg=cad_avg,
            flags=flags,
        ))
    return segments


def climb_samples(records: Sequence[Record], resolution_s: int = CLIMB_RESOLUTION_S) -> List[dict]:
    """Records → échantillons normalisés (`t_s, distance_m, altitude_m, speed_ms`)
    sous-échantillonnés comme à l'indexation (`arc_samples.downsample`, 5 s) : le
    détecteur du moteur voit alors les mêmes points que `arc_index.py vam` et
    l'identité de montée #49 (`arc_climb_match.py`), donc les mêmes bornes."""
    raw = [{"t_s": r.t, "distance_m": r.distance_m, "altitude_m": r.elevation_m,
            "speed_ms": r.speed_kmh / 3.6 if r.speed_kmh is not None else None}
           for r in records]
    return arc_samples.downsample(raw, resolution_s)


def detect_climbs(records: Sequence[Record], cfg: dict) -> List[Segment]:
    """Montées via le détecteur canonique du moteur (`scripts/arc_climb.py::detect_climbs` :
    segmentation par trou de signal, lissage, zigzag à hystérésis, rognage, fusion des
    petits creux), puis métriques d'exécution (FC, vitesse, cadence) sur les records bruts
    de chaque montée. Seuils propres au skill : `climb_min_ascent_m` (gain net) et
    `climb_grade_min_pct` (pente moyenne) passés au moteur, `climb_min_distance_m`
    appliqué ici. Un seuil plus bas que celui de l'index ne change jamais les bornes
    d'une montée que les deux retiennent : le filtre du moteur s'applique en dernier."""
    samples = climb_samples(records)
    found = arc_climb.detect_climbs(
        samples,
        min_gain_m=cfg["climb_min_ascent_m"],
        min_avg_grade=cfg["climb_grade_min_pct"] / 100.0,
        resolution_s=CLIMB_RESOLUTION_S,
    )
    times = [r.t for r in records]
    segments: List[Segment] = []
    for c in found:
        if c["distance_m"] < cfg["climb_min_distance_m"]:
            continue
        # Records couverts par la montée : les buckets de `start_t_s` à `end_t_s`
        # inclus (un bucket porte la borne inférieure de sa fenêtre de 5 s).
        i = bisect.bisect_left(times, c["start_t_s"])
        j = bisect.bisect_left(times, c["end_t_s"] + CLIMB_RESOLUTION_S)
        seg_records = records[i:j]
        if not seg_records:
            continue
        speeds = [r.speed_kmh for r in seg_records]
        hrs = [r.hr for r in seg_records if r.hr]
        cads = [r.cadence for r in seg_records if r.cadence]
        segments.append(Segment(
            kind="climb",
            index=len(segments) + 1,
            start_t=c["start_t_s"],
            end_t=c["end_t_s"],
            duration_s=c["duration_elapsed_s"],
            distance_m=c["distance_m"],
            avg_speed_kmh=sum(speeds) / len(speeds),
            max_speed_kmh=max(speeds),
            avg_hr_bpm=sum(hrs) / len(hrs) if hrs else None,
            max_hr_bpm=max(hrs) if hrs else None,
            hr_before_bpm=_avg_hr_window(records, i, look_back=15),
            hr_after_bpm=_avg_hr_window(records, j - 1, look_fwd=15),
            elevation_gain_m=c["gain_m"],
            avg_grade_pct=round(c["avg_grade"] * 100, 1),
            recovery_before_s=(c["start_t_s"] - segments[-1].end_t) if segments else None,
            cadence_avg=sum(cads) / len(cads) if cads else None,
            grade_class=c["grade_class"],
            vam_elapsed_m_h=c["vam_elapsed_m_h"],
            vam_moving_m_h=c["vam_moving_m_h"],
        ))
    return segments


def detect_sprints(records: Sequence[Record], cfg: dict) -> List[Segment]:
    """Detect true sprints: very short, very fast bursts."""
    thr = cfg["sprint_speed_threshold_kmh"]
    min_d = cfg["sprint_min_duration_s"]
    max_d = cfg["sprint_max_duration_s"]
    bursts = []
    i = 0
    n = len(records)
    while i < n:
        if records[i].speed_kmh >= thr:
            j = i
            while j < n and records[j].speed_kmh >= thr:
                j += 1
            d = records[j - 1].t - records[i].t
            if min_d <= d <= max_d:
                bursts.append((i, j))
            i = j
        else:
            i += 1

    out = []
    for idx, (a, b) in enumerate(bursts, start=1):
        seg = records[a:b]
        hrs = [r.hr for r in seg if r.hr]
        out.append(Segment(
            kind="sprint",
            index=idx,
            start_t=seg[0].t,
            end_t=seg[-1].t,
            duration_s=seg[-1].t - seg[0].t,
            distance_m=seg[-1].distance_m - seg[0].distance_m,
            avg_speed_kmh=sum(r.speed_kmh for r in seg) / len(seg),
            max_speed_kmh=max(r.speed_kmh for r in seg),
            avg_hr_bpm=sum(hrs) / len(hrs) if hrs else None,
            max_hr_bpm=max(hrs) if hrs else None,
            hr_before_bpm=_avg_hr_window(records, a, look_back=10),
            hr_after_bpm=_avg_hr_window(records, b - 1, look_fwd=10),
            elevation_gain_m=0.0,
            avg_grade_pct=None,
            recovery_before_s=(seg[0].t - out[-1].end_t) if out else None,
            cadence_avg=None,
        ))
    return out


def detect_intervals(records: Sequence[Record], cfg: dict) -> List[Segment]:
    """
    Detect generic intervals: alternating high/low speed at least 3 times.
    A simple heuristic — speed alternates between > 12 km/h and < 10 km/h
    within 3 minutes.
    """
    segments: List[Segment] = []
    in_high = False
    i = 0
    n = len(records)
    rep_start: Optional[int] = None
    reps: List[tuple] = []
    while i < n:
        if records[i].speed_kmh >= 12.0:
            if not in_high:
                in_high = True
                rep_start = i
            # continue
        elif records[i].speed_kmh < 10.0:
            if in_high:
                reps.append((rep_start, i))  # [start, end) of high block
                in_high = False
        i += 1
    if in_high and rep_start is not None:
        reps.append((rep_start, n - 1))

    if len(reps) < 2:
        return segments
    # We just return each rep as a Segment
    for idx, (a, b) in enumerate(reps, start=1):
        seg = records[a:b]
        hrs = [r.hr for r in seg if r.hr]
        segments.append(Segment(
            kind="interval",
            index=idx,
            start_t=seg[0].t,
            end_t=seg[-1].t,
            duration_s=seg[-1].t - seg[0].t,
            distance_m=seg[-1].distance_m - seg[0].distance_m,
            avg_speed_kmh=sum(r.speed_kmh for r in seg) / len(seg),
            max_speed_kmh=max(r.speed_kmh for r in seg),
            avg_hr_bpm=sum(hrs) / len(hrs) if hrs else None,
            max_hr_bpm=max(hrs) if hrs else None,
            hr_before_bpm=_avg_hr_window(records, a, look_back=10),
            hr_after_bpm=_avg_hr_window(records, b - 1, look_fwd=10),
            elevation_gain_m=0.0,
            avg_grade_pct=None,
            recovery_before_s=(seg[0].t - segments[-1].end_t) if segments else None,
            cadence_avg=None,
        ))
    return segments


def detect_cooldown(records: Sequence[Record], cfg: dict) -> List[Segment]:
    """Detect the last 5 minutes of the session — assumed cooldown."""
    if len(records) < 10:
        return []
    end_t = records[-1].t
    start_t = max(0.0, end_t - 300.0)
    a = next(i for i, r in enumerate(records) if r.t >= start_t)
    seg = records[a:]
    hrs = [r.hr for r in seg if r.hr]
    return [Segment(
        kind="cooldown",
        index=1,
        start_t=seg[0].t,
        end_t=seg[-1].t,
        duration_s=seg[-1].t - seg[0].t,
        distance_m=seg[-1].distance_m - seg[0].distance_m,
        avg_speed_kmh=sum(r.speed_kmh for r in seg) / len(seg),
        max_speed_kmh=max(r.speed_kmh for r in seg),
        avg_hr_bpm=sum(hrs) / len(hrs) if hrs else None,
        max_hr_bpm=max(hrs) if hrs else None,
        hr_before_bpm=_avg_hr_window(records, a, look_back=30),
        hr_after_bpm=None,
        elevation_gain_m=0.0,
        avg_grade_pct=None,
        recovery_before_s=None,
        cadence_avg=None,
    )]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _avg_hr_window(records: Sequence[Record], idx: int,
                   look_back: int = 0, look_fwd: int = 0) -> Optional[float]:
    """Average HR over [idx-look_back, idx+look_fwd] (inclusive)."""
    lo = max(0, idx - look_back)
    hi = min(len(records) - 1, idx + look_fwd)
    hrs = [records[k].hr for k in range(lo, hi + 1) if records[k].hr is not None]
    if not hrs:
        return None
    return round(sum(hrs) / len(hrs), 1)


def load_records_from_garmin_json(activity_id: int, host: str) -> List[Record]:
    """
    Fetch per-km splits + session summary from a Garmin MCP server (HTTP)
    and synthesize coarse 1-km Records. NOTE: this loses per-second fidelity;
    use the FIT file for stride / sprint detection.
    """
    try:
        import urllib.request
        import urllib.parse
    except ImportError:
        raise SystemExit("urllib manquant (impossible)")

    base = host.rstrip("/")
    url = f"{base}/activities/{activity_id}/splits?token="
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise SystemExit(f"Impossible de joindre {host} ({exc})")

    records: List[Record] = []
    t = 0.0
    prev_dist = 0.0
    for split in data.get("laps", []):
        d = float(split.get("distance_meters", 0))
        dur = float(split.get("duration_seconds", 0))
        avg_s = float(split.get("avg_speed_mps", 0))
        hr = int(split.get("avg_hr_bpm", 0)) or None
        n_samp = max(1, int(dur))
        for s in range(n_samp):
            records.append(Record(
                t=t + s,
                distance_m=prev_dist + (d * (s + 1) / n_samp),
                speed_kmh=avg_s * 3.6,
                hr=hr,
                elevation_m=None,
                grade_pct=None,
                cadence=None,
            ))
        t += dur
        prev_dist += d
    return records


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

HEADER = [
    "#", "Plage (s)", "Durée (s)", "Dist (m)",
    "V moy (km/h)", "V max (km/h)",
    "HR avant", "HR seg", "HR après",
    "Cad moy", "Δ+ (m)", "Flags",
]


def render_markdown(part: str, segments: List[Segment], meta: dict) -> str:
    lines: List[str] = []
    lines.append(f"# Analyse des segments `{part}`")
    lines.append("")
    if meta:
        lines.append("## Métadonnées")
        for k, v in meta.items():
            lines.append(f"- **{k}** : {v}")
        lines.append("")
    if not segments:
        lines.append(f"_Aucun segment détecté pour `{part}` avec les seuils actuels._")
        return "\n".join(lines) + "\n"

    lines.append(f"_Segments détectés : **{len(segments)}**_")
    lines.append("")
    lines.append("| " + " | ".join(HEADER) + " |")
    lines.append("|" + "|".join(["---"] * len(HEADER)) + "|")
    for s in segments:
        lines.append("| " + " | ".join(s.to_row()) + " |")
    lines.append("")
    # Aggregate stats
    avg_speeds = [s.avg_speed_kmh for s in segments]
    max_speeds = [s.max_speed_kmh for s in segments]
    avg_dists = [s.distance_m for s in segments]
    avg_recov = [s.recovery_before_s for s in segments if s.recovery_before_s is not None]
    flagged = [s for s in segments if s.flags]
    lines.append("## Synthèse")
    lines.append(f"- Distance moyenne par segment : **{statistics.mean(avg_dists):.0f} m**")
    lines.append(f"- Vitesse moyenne par segment : **{statistics.mean(avg_speeds):.1f} km/h**")
    lines.append(f"- Pic de vitesse moyen : **{statistics.mean(max_speeds):.1f} km/h** (max global : **{max(max_speeds):.1f} km/h**)")
    if avg_recov:
        lines.append(f"- Récupération moyenne entre segments : **{statistics.mean(avg_recov):.0f} s**")
    lines.append(f"- Segments flaggués : **{len(flagged)} / {len(segments)}**")
    if part == "climb":
        lines.append("")
        lines.append("### Montées — pente et VAM")
        lines.append("| # | Pente moy. | Classe | Gain net (m) | VAM écoulée (m/h) | VAM mouvement (m/h) |")
        lines.append("|---|---|---|---|---|---|")
        for s in segments:
            vam_e = f"{s.vam_elapsed_m_h:.0f}" if s.vam_elapsed_m_h is not None else "—"
            vam_m = f"{s.vam_moving_m_h:.0f}" if s.vam_moving_m_h is not None else "—"
            grade = f"{s.avg_grade_pct:.1f} %" if s.avg_grade_pct is not None else "—"
            lines.append(f"| #{s.index} | {grade} | {s.grade_class or '—'} | "
                         f"{s.elevation_gain_m:+.0f} | {vam_e} | {vam_m} |")
    if flagged:
        lines.append("")
        lines.append("### Segments à revoir")
        for s in flagged:
            recup_txt = f"récup {s.recovery_before_s:.0f}s" if s.recovery_before_s is not None else "premier segment"
            lines.append(f"- **#{s.index}** ({s.start_t:.0f}s–{s.end_t:.0f}s) — "
                         f"V max {s.max_speed_kmh:.1f} km/h, dist {s.distance_m:.0f} m, "
                         f"{recup_txt} — _{'; '.join(s.flags)}_")
    return "\n".join(lines) + "\n"


def render_json(segments: List[Segment], meta: dict) -> str:
    payload = {
        "meta": meta,
        "segments": [asdict(s) for s in segments],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyse les portions spécifiques (LD, montées, sprints, etc.) d'une séance Garmin.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--fit", type=Path, help="Chemin vers un fichier FIT exporté depuis Garmin Connect")
    src.add_argument("--activity-id", type=int, help="ID d'activité Garmin (interroge le MCP)")
    src.add_argument("--activity-json", type=Path,
                     help="Fichier JSON pré-téléchargé (via get_activity_fit_data)")
    p.add_argument("--part", required=True,
                   choices=["stride", "climb", "sprint", "interval", "cooldown"],
                   help="Type de portion à détecter")
    p.add_argument("--garmin-host", default="http://localhost:8080",
                   help="Hôte MCP Garmin (mode --activity-id)")
    p.add_argument("--smooth-window", type=int, default=DEFAULTS["speed_smooth_window_s"],
                   help=f"Fenêtre de lissage vitesse (s, défaut {DEFAULTS['speed_smooth_window_s']})")
    p.add_argument("--stride-threshold", type=float,
                   default=DEFAULTS["stride_speed_threshold_kmh"],
                   help=f"Seuil haut vitesse pour stride (km/h, défaut {DEFAULTS['stride_speed_threshold_kmh']})")
    p.add_argument("--recovery-threshold", type=float,
                   default=DEFAULTS["stride_recovery_speed_kmh"],
                   help=f"Seuil bas vitesse pour récup (km/h, défaut {DEFAULTS['stride_recovery_speed_kmh']})")
    p.add_argument("--output", type=Path, help="Fichier Markdown de sortie (défaut: stdout)")
    p.add_argument("--json", dest="json_out", type=Path, help="Fichier JSON de sortie (optionnel)")
    p.add_argument("--quiet", action="store_true", help="N'affiche que les erreurs")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    cfg = dict(DEFAULTS)
    cfg["stride_speed_threshold_kmh"] = args.stride_threshold
    cfg["stride_recovery_speed_kmh"] = args.recovery_threshold

    # ---- Load records -------------------------------------------------
    meta = {"part": args.part}
    if args.fit:
        records = load_records_from_fit(args.fit)
        meta["source"] = str(args.fit)
    elif args.activity_json:
        # JSON FIT export = list of records (already parsed)
        with args.activity_json.open() as fh:
            data = json.load(fh)
        records = _records_from_fit_json(data)
        meta["source"] = str(args.activity_json)
    else:
        records = load_records_from_garmin_json(args.activity_id, args.garmin_host)
        meta["activity_id"] = args.activity_id
        meta["warning"] = "Mode JSON 1 km — précision seconde-par-seconde indisponible"

    meta["records"] = len(records)

    smooth_speed(records, args.smooth_window)

    # ---- Detect --------------------------------------------------------
    detector = {
        "stride": detect_strides,
        "climb": detect_climbs,
        "sprint": detect_sprints,
        "interval": detect_intervals,
        "cooldown": detect_cooldown,
    }[args.part]
    segments = detector(records, cfg)

    # ---- Report --------------------------------------------------------
    md = render_markdown(args.part, segments, meta)
    if args.output:
        args.output.write_text(md, encoding="utf-8")
        if not args.quiet:
            print(f"Markdown écrit dans {args.output}")
    else:
        print(md)

    if args.json_out:
        args.json_out.write_text(render_json(segments, meta), encoding="utf-8")
        if not args.quiet:
            print(f"JSON écrit dans {args.json_out}")

    if not segments:
        return 1
    return 0


def _records_from_fit_json(data: dict) -> List[Record]:
    """
    Convert a get_activity_fit_data payload (already parsed JSON) into Records.
    Each entry in data['records'] (if present) has positions, speed, hr, etc.
    """
    raw = data.get("records") or []
    out: List[Record] = []
    t0 = None
    cum = 0.0
    last = None
    for r in raw:
        ts = r.get("timestamp")
        if t0 is None and ts is not None:
            t0 = ts
        t = (ts - t0).total_seconds() if ts is not None else len(out)
        sp_mps = r.get("speed") or 0.0
        sp_kmh = sp_mps * 3.6
        cum += sp_mps
        out.append(Record(
            t=t, distance_m=cum, speed_kmh=sp_kmh,
            hr=r.get("heart_rate"),
            elevation_m=r.get("enhanced_altitude") or r.get("altitude"),
            grade_pct=r.get("grade"),
            cadence=r.get("cadence"),
            lat=r.get("position_lat"), lon=r.get("position_long"),
        ))
    return out


if __name__ == "__main__":
    sys.exit(main())
