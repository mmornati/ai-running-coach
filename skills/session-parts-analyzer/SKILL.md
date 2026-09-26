---
name: session-parts-analyzer
description: Use to analyze specific portions of a Garmin session (strides/lignes droites, climbs, sprints, intervals, last km, cooldowns, etc.) — detects segments by speed/HR/elevation and reports per-segment execution metrics. Use when the user or coach wants detailed feedback on a particular drill, on a session that mixes work + recovery, or to validate stride/interval execution.
---

# Skill: session-parts-analyzer

This skill loads the **stride / climb / sprint / interval / cooldown segment detector** for Garmin activities.
It produces a per-segment Markdown report with distance, pace, HR before/during/after, recovery gaps, and execution flags.

The detector is implemented as a Python script (`scripts/analyze_session_parts.py`)
that reads either a FIT file or a Garmin JSON export and applies heuristics on smoothed speed / HR;
climbs are delegated to the engine detector (`scripts/arc_climb.py`).

---

## When to use

- **Stride / lignes droites analysis** — verify protocol: progressive acceleration, ~100 m work, ~100 m recovery, HR drop between reps.
- **Climb detection** — sustained climbs (net gain ≥ 15 m, average grade ≥ 4 %, over ≥ 150 m) detected by the engine's canonical detector (`scripts/arc_climb.py`), with HR drift, grade class and VAM per climb.
- **Sprint / interval work** — count reps, validate recovery gaps, check that HR returns to baseline between reps.
- **Last km / cooldown** — distinguish finish-line surge from a true cool-down.
- **Mixed sessions** — any time the user wants to know "what really happened in section X of the run".

**Do NOT use this skill** when:
- The user wants the global session analysis only (use the standard `coach` workflow on `get_activity`).
- The data is incomplete (no FIT, no MCP access). In that case, fall back to split-level analysis and mention the limitation.
- The question is a whole-session KPI (time in zone, decoupling/EF, GAP, VAM, descent efficiency, durability/fade) — those are computed by `scripts/arc_index.py` (`zones`/`decoupling`/`gap`/`vam`/`descent`/`durability`, #51), not by this segment detector. Reuse that CLI instead of approximating the same number from segments.

---

## Quick start

### CLI — local FIT file (recommended, per-second precision)

```bash
python3 skills/session-parts-analyzer/scripts/analyze_session_parts.py \
  --fit ~/Downloads/24059541901_ACTIVITY.FIT \
  --part stride \
  --output /tmp/strides_21_08.md \
  --json  /tmp/strides_21_08.json
```

### CLI — Garmin MCP (1 km granularity only)

```bash
# Coarser: only the 1-km splits are available through the MCP JSON,
# stride / sprint detection will be approximate. Prefer FIT.
python3 skills/session-parts-analyzer/scripts/analyze_session_parts.py \
  --activity-id 24059541901 \
  --part stride \
  --garmin-host http://localhost:8080
```

### CLI — JSON file already fetched

```bash
# If `get_activity_fit_data` was called and saved to disk
python3 skills/session-parts-analyzer/scripts/analyze_session_parts.py \
  --activity-json /tmp/24059541901_records.json \
  --part climb
```

### Inside the coach agent (programmatic invocation)

```python
import subprocess, json
result = subprocess.run(
    ["python3", "skills/session-parts-analyzer/scripts/analyze_session_parts.py",
     "--fit", fit_path, "--part", "stride", "--quiet"],
    capture_output=True, text=True
)
markdown_report = result.stdout
# Or load the JSON dump for downstream reuse
data = json.loads(open("/tmp/strides.json").read())
```

---

## Output format

### Markdown (stdout or --output file)

```markdown
# Analyse des segments `stride`

## Métadonnées
- **part** : stride
- **source** : /Users/.../24059541901_ACTIVITY.FIT
- **records** : 3544

_Segments détectés : **8**_

| # | Plage (s) | Durée (s) | Dist (m) | V moy (km/h) | V max (km/h) | HR avant | HR seg | HR après | Cad moy | Δ+ (m) | Flags |
|---|-----------|-----------|----------|--------------|--------------|----------|--------|----------|---------|--------|-------|
| #1 | 1320–1342 | 22.0 | 95 | 15.5 | 16.8 | 124 | 142 | 138 | 174 | +1 | ✅ |
| #2 | 1418–1439 | 21.0 | 91 | 15.6 | 17.1 | 132 | 146 | 140 | 176 | 0 | ✅ |
| ... |

## Synthèse
- Distance moyenne par segment : **93 m**
- Vitesse moyenne par segment : **15.6 km/h**
- Pic de vitesse moyen : **17.1 km/h** (max global : **17.4 km/h**)
- Récupération moyenne entre segments : **75 s**
- Segments flaggués : **2 / 8**
```

### JSON (--json file)

```json
{
  "meta": { "part": "stride", "source": "...", "records": 3544 },
  "segments": [
    {
      "kind": "stride",
      "index": 1,
      "start_t": 1320.0,
      "end_t": 1342.0,
      "duration_s": 22.0,
      "distance_m": 95.0,
      "avg_speed_kmh": 15.5,
      "max_speed_kmh": 16.8,
      "avg_hr_bpm": 142.0,
      "max_hr_bpm": 152,
      "hr_before_bpm": 124.0,
      "hr_after_bpm": 138.0,
      "elevation_gain_m": 1.0,
      "avg_grade_pct": null,
      "recovery_before_s": 75.0,
      "cadence_avg": 174.0,
      "flags": []
    }
  ]
}
```

---

## Configuration (CLI flags)

All thresholds default to typical trail-running values. Override per session:

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--stride-threshold` | 12.0 km/h | Min speed to enter a stride burst |
| `--recovery-threshold` | 9.5 km/h | Max speed during recovery |
| `--smooth-window` | 5 s | Moving average window for speed smoothing |
| `--part` | _(required)_ | `stride`, `climb`, `sprint`, `interval`, `cooldown` |

Inside `DEFAULTS` (top of the script) you can also tune:

| Key | Default | Meaning |
|:----|:--------|:--------|
| `stride_min_duration_s` | 8 | Min burst length for stride |
| `stride_max_duration_s` | 30 | Max burst length for stride |
| `stride_recovery_min_s` | 60 | Min recovery gap |
| `stride_recovery_max_s` | 180 | Max recovery gap (beyond = end of block) |
| `stride_distance_min_m` | 60 | Min distance for stride |
| `stride_distance_max_m` | 160 | Max distance for stride |
| `climb_grade_min_pct` | 4.0 | Min average grade (net gain / distance) for climb |
| `climb_min_distance_m` | 150 | Min distance for climb (was 250 before the engine migration, see below) |
| `climb_min_ascent_m` | 15 | Min net gain for climb |
| `sprint_speed_threshold_kmh` | 15.0 | Min speed for sprint |
| `sprint_min_duration_s` | 4 | Min sprint length |
| `sprint_max_duration_s` | 12 | Max sprint length |

---

## Detection algorithms

### `stride` (lignes droites)

1. Smooth speed with a 5 s moving average to remove GPS noise.
2. Find bursts where smoothed speed > `stride_threshold` for `stride_min_duration_s` to `stride_max_duration_s`.
3. For each burst: compute distance, V max/V avg, HR before/during/after (10 s windows), cadence, elevation.
4. Compute recovery gap to previous stride. Flag if `< stride_recovery_min_s` or `> stride_recovery_max_s`.
5. Flag if V max > `stride_threshold + 3.5 km/h` (suggesting overspeed).

### `climb`

Delegates to the engine's canonical detector, `scripts/arc_climb.py::detect_climbs` (#46) — the same one used by the dashboard VAM and by same-climb identity across sessions (#49, `scripts/arc_climb_match.py`):

1. Records are converted to normalised samples (`t_s`, `distance_m`, `altitude_m`, `speed_ms`) and downsampled to the index resolution (5 s, `arc_samples.downsample`) so that climb boundaries are **identical** to those computed by `scripts/arc_index.py vam` for the same FIT.
2. The engine segments on signal gaps (> 30 s, never bridged), smooths altitude, runs a hysteresis zigzag, trims flat approaches/exits, splits long internal plateaus and merges short dips.
3. The skill filters with its own thresholds (`climb_min_ascent_m`, `climb_grade_min_pct` passed to the engine, `climb_min_distance_m` applied afterwards). Lower thresholds than the index never change the boundaries of a climb both keep: the engine filter is the last step.
4. Execution metrics (speed, HR before/during/after, cadence) come from the raw records within the climb; recovery is the gap to the previous climb.

Changes vs the former detector (instantaneous Garmin `grade` ≥ threshold): climbs are bounded on smoothed altitude rather than the noisy per-record grade, so a short flat no longer splits a climb and short dips are merged; `elevation_gain_m` is the **net** gain (was the sum of positive deltas); `avg_grade_pct` is net gain / distance (was the mean instantaneous grade); boundaries are trimmed, hence slightly shorter — which is why `climb_min_distance_m` went from 250 to 150 m. Added JSON keys (`null` for other parts): `grade_class`, `vam_elapsed_m_h`, `vam_moving_m_h`; the Markdown report gains a "Montées — pente et VAM" table.

### `sprint`

Same algorithm as stride but tighter bounds (4-12 s, > 15 km/h).

### `interval`

Detects alternating speed bands (> 12 km/h / < 10 km/h). Returns each "high" block as a Segment.

### `cooldown`

Last 5 minutes of the session by default.

---

## Limitations

- **GPS noise**: smoothing mitigates but doesn't eliminate. Bursts shorter than the smoothing window (5 s) can be missed.
- **Static threshold for stride**: 12 km/h is fine for an athlete running Z2 at ~5:30/km. For slower runners (6:30/km+) lower `--stride-threshold` to 10 km/h.
- **FIT downloads can time out** via the Garmin MCP (`get_activity_fit_data` returns 30 s timeout for very large files). Fall back to `--activity-id` mode (1 km granularity) or to split-level manual analysis.
- **HR drift detection**: only `climb` and `cooldown` modes include HR drift. For whole-session Pa:HR decoupling/EF, zones, GAP, VAM or durability, do NOT recompute them here — run `python3 scripts/arc_index.py decoupling|zones|gap|vam|durability --activity <garmin_activity_id>` instead (#51). This skill stays scoped to sub-segment detection (stride/sprint/interval/climb-as-drill boundaries) that those whole-session KPIs don't produce.
- **No GPS-hole handling for speed-based parts**: `stride`/`sprint`/`interval` may mis-segment across long gaps (tunnel, pause). `climb` never bridges a gap (> 30 s) — two halves of an interrupted climb are reported separately.

---

## Files

| Path | Role |
|:-----|:-----|
| `SKILL.md` | This file (load via the `skill` tool) |
| `scripts/analyze_session_parts.py` | Detector + reporter (CLI); climbs via the engine |
| `../../scripts/arc_climb.py`, `../../scripts/arc_samples.py` | Engine climb detector and sample downsampling (imported) |
