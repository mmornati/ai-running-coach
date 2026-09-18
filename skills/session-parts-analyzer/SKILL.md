---
name: session-parts-analyzer
description: Use to analyze specific portions of a Garmin session (strides/lignes droites, climbs, sprints, intervals, last km, cooldowns, etc.) — detects segments by speed/HR/elevation and reports per-segment execution metrics. Use when the user or coach wants detailed feedback on a particular drill, on a session that mixes work + recovery, or to validate stride/interval execution.
---

# Skill: session-parts-analyzer

This skill loads the **stride / climb / sprint / interval / cooldown segment detector** for Garmin activities.
It produces a per-segment Markdown report with distance, pace, HR before/during/after, recovery gaps, and execution flags.

The detector is implemented as a single self-contained Python script (`scripts/analyze_session_parts.py`)
that reads either a FIT file or a Garmin JSON export and applies heuristics on smoothed speed / HR / grade.

---

## When to use

- **Stride / lignes droites analysis** — verify protocol: progressive acceleration, ~100 m work, ~100 m recovery, HR drop between reps.
- **Climb detection** — flag sustained climbs (grade ≥ 4 % over ≥ 250 m with ≥ 15 m gain) and report HR drift.
- **Sprint / interval work** — count reps, validate recovery gaps, check that HR returns to baseline between reps.
- **Last km / cooldown** — distinguish finish-line surge from a true cool-down.
- **Mixed sessions** — any time the user wants to know "what really happened in section X of the run".

**Do NOT use this skill** when:
- The user wants the global session analysis only (use the standard `coach` workflow on `get_activity`).
- The data is incomplete (no FIT, no MCP access). In that case, fall back to split-level analysis and mention the limitation.

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
| `climb_grade_min_pct` | 4.0 | Min grade for climb |
| `climb_min_distance_m` | 250 | Min distance for climb |
| `climb_min_ascent_m` | 15 | Min ascent for climb |
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

1. Walk the records. Open a new climb window when `grade_pct >= climb_grade_min_pct`.
2. Close it when grade drops below threshold.
3. Validate window has `distance >= climb_min_distance_m` AND `ascent >= climb_min_ascent_m`.
4. Report HR before/after, average grade, max speed.

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
- **HR drift detection**: only `climb` and `cooldown` modes include HR drift; for full Pa:HR decoupling use the standard `coach` workflow on the activity detail.
- **No GPS-hole handling yet**: if the recording has long zero-speed gaps (tunnel, pause), the heuristic may mis-segment.

---

## Files

| Path | Role |
|:-----|:-----|
| `SKILL.md` | This file (load via the `skill` tool) |
| `scripts/analyze_session_parts.py` | Self-contained detector + reporter (CLI) |
| `examples/README.md` | _(to be filled)_ example outputs on real sessions |
