---
name: garmin-workout-scheduling
description: Use to push planned training sessions directly to the Garmin Connect calendar via the garmin MCP tools (schedule_workouts / schedule_week / upload_workout). Covers the exact Garmin DTO JSON schema, step/endCondition/targetType/sportType lookup tables, idempotency, strength-workout detail (exercises, reps, weight, rest, RepeatGroupDTO loops), and the verify-after-push pattern. Garmin calendar is the PRIMARY scheduling destination; Intervals.icu is secondary.
---

# Garmin Workout Scheduling — Garmin Calendar First

Push planned sessions straight onto the Garmin Connect calendar. **Garmin is the primary destination when `[data].source = "garmin"` (default)**; Intervals.icu is secondary (only if the user explicitly wants events there). All schemas below are TESTED on the live Garmin API via `garmin-mcp`.

**`[data].source = "intervals"` (#68):** none of this applies — this whole
skill, and every tool below, is Garmin-only. Load `intervals-icu-best-practices`
instead and push via `icu_create_event`/`icu_bulk_create_events` on the `intervals`
MCP server. **`[data].source = "strava"` (#164):** nothing to push to either — Strava has no
training calendar and no write tool for workouts; keep the plan in `planning/` and say so.

## Tool Access

Everything via the `garmin` MCP server tools (direct mode) or via `leanproxy_invoke_tool(server="garmin", ...)` (power-user mode):

- `schedule_workouts(schedules)` — **preferred**: list of `{calendar_date, workout_id}` OR `{calendar_date, workout_data}` (upload + schedule in ONE call).
- `schedule_week(week)` — list of `{date, workout_id}` for an existing workout.
- `schedule_workout(workout_id, calendar_date)` — single schedule of an existing workout.
- `upload_workout(workout_data)` — create a library workout without scheduling.
- `get_workout_by_id(workout_id)` / `get_workouts` / `get_scheduled_workouts(start_date, end_date)` — verification.
- `delete_workout(s)` / `delete_scheduled_workout(s)` — cleanup stale calendar entries.

## Idempotency — CRITICAL CORRECTION (tested 11 Aug 2026)

- **Inline `workout_data` is NOT idempotent.** Each `schedule_workouts` call with inline `workout_data` UPLOADS A NEW workout and schedules it — re-pushing a date with new data leaves the OLD workout scheduled alongside it (observed duplicate on 2026-08-19).
- **`workout_id` path IS idempotent** per date (rescheduling same id overwrites without duplicating).
- **SAFE PATTERN — check before push:** BEFORE pushing a date, call `get_scheduled_workouts(start_date, end_date)`. If a workout already exists for that date:
  - Same session + same detail → reuse its `workout_id` via `schedule_workouts`/`schedule_week` (idempotent).
  - Session changed → `delete_workout(old_workout_id)` then push fresh `workout_data`.
- After ANY push, ALWAYS verify with `get_scheduled_workouts(start_date, end_date)` and (for detail) `get_workout_by_id(workout_id)`. Watch for duplicates on the same date.

## EXACT JSON SCHEMA (Garmin internal DTO — do NOT invent keys)

A 400 error happens if you use `steps` or `conditionValue`. Use the exact structure below.

```json
{
  "workoutName": "Footing Z1 40min - Mer 12",
  "description": "Footing récupération en zone 1",
  "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
  "workoutSegments": [{
    "segmentOrder": 1,
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSteps": [
      {
        "type": "ExecutableStepDTO",
        "stepOrder": 1,
        "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
        "description": "40 min en Z1",
        "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
        "endConditionValue": 2400,
        "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
        "zoneNumber": 1
      }
    ]
  }]
}
```

## Lookup Tables (from garmin-mcp `workout_templates.py`)

| stepType | id | key |
|---|---|---|
| Warmup | 1 | warmup |
| Cooldown | 2 | cooldown |
| Interval | 3 | interval |
| Recovery | 4 | recovery |
| Rest | 5 | rest |
| Repeat | 6 | repeat |

| endCondition | id | key | value unit |
|---|---|---|---|
| Lap button | 1 | lap.button | — |
| Time | 2 | time | seconds |
| Distance | 3 | distance | meters |
| Iterations (RepeatGroupDTO only) | 7 | iterations | repeat count |
| Reps | 10 | reps | rep count |

| targetType | id | key |
|---|---|---|
| No target | 1 | no.target |
| HR zone (named) | 4 | heart.rate.zone |
| Pace zone | 6 | pace.zone |

| sportType (workouts) | id | key |
|---|---|---|
| Running | 1 | running |
| Cycling | 2 | cycling |
| Other | 3 | other |
| Lap swimming | 4 | lap_swimming |
| Strength | 5 | strength_training |
| Cardio | 6 | cardio |
| Yoga | 7 | yoga |
| Walking | 11 | walking |

### HR targeting rules

- **Named zone**: `targetType` `heart.rate.zone` + `zoneNumber` 1–5 (do NOT use `targetValueOne`).
- **Custom bpm range**: `targetValueOne` / `targetValueTwo` (low/high bpm) with `heart.rate.zone` target. **Prefer this over a named zone whenever a personal `bounds_bpm` is available** (#60, below) — it's the athlete's own bpm from their own profile, a named `zoneNumber` is a generic 5-way split that doesn't know this athlete's LTHR/Karvonen/%max.

### Pace targeting rules (`pace.zone`, id 6)

- `targetValueOne` / `targetValueTwo` — **meters per second, NOT s/km or min/km.** Cross-checked against the reverse-engineered schema used by the (open, unmerged as of writing — "Add support for targeted workouts", tested live by its author against the real Garmin API) `python-garminconnect` PR #440: `PaceTarget`, "upper and lower limits in m/s". `targetValueOne` = `lower_limit` = the **slower** pace (smaller m/s), `targetValueTwo` = `upper_limit` = the **faster** pace (larger m/s) — same low-then-high convention as the HR custom range above. This project has not yet independently verified the m/s convention against a live push of its own; **the first real `pace.zone` push should be followed by `get_workout_by_id` and a manual eyeball of the resulting pace range on the Garmin Connect app/website** before trusting it unattended.
- Never target pace on a graded step (hill repeat): a flat-equivalent pace target on a climb is physically meaningless without GAP-aware guidance, which Garmin steps don't support. Use an HR target (or no target) plus the expected D+ in the step `description` instead — see below.

## Personal targets — zones, GAP pace, hill D+ (#60)

Never invent a bpm bound, a pace, or a climb dénivelé: compute them from the athlete's own profile and personal slope model with `scripts/arc_workout_targets.py`, a pure helper reused by #43 (HR zones), #44/#58 (GAP / personal slope model) — never a second copy of that logic.

```bash
python3 scripts/arc_workout_targets.py targets --session planning/Semaine_2026-09-28.md#2026-09-30
# une date qui identifie PLUSIEURS séances du même fichier : précisez, jamais "la première" :
python3 scripts/arc_workout_targets.py targets --session planning/Semaine_2026-09-28.md#2026-09-30@1
python3 scripts/arc_workout_targets.py targets --session "planning/Semaine_2026-09-28.md#2026-09-30:Footing endurance 45 min"
# répétitif de côte SANS clé `structure` (le contrat `arc` n'en a pas) — parse le titre, ou --structure-text :
python3 scripts/arc_workout_targets.py targets --session planning/Semaine.md#2026-10-02 --structure-text "6x3 min côte 8%"
# ou une séance inline :
python3 scripts/arc_workout_targets.py targets --session '{"date":"2026-09-30","sport":"trail","title":"Footing endurance","intensity":"endurance"}'
```

Renders `{"intensity", "sport", "hr_target", "pace_target", "hill_repeats", "cs_target"}` (`cs_target`: see the critical-speed bullet below). **The drop-the-target rule keys on the VALUE being `null`, never on `reason`/`reason_code` alone** — a target can carry both a usable value and an informational `reason_code` (e.g. `"extrapolated"`, see below); only a `null` value means "leave this target out of the DTO":

- **`hr_target`** — `bounds_bpm: [low, high]` (already rounded to int, DTO-ready) from the athlete's own zones (`arc_metrics.hr_zone_resolution`, method LTHR → Karvonen → %HRmax by precedence), mapped from the session's planned `intensity`: `recovery`→Z1, `endurance`→Z2, `tempo`→Z3, `threshold`→Z4, `vo2max`→Z5. `race`/`rest`/`strength` have no mapping. `reason`/`reason_code` explains a `null` bound: `unmapped_intensity`, `no_zone_data` (profile missing HRmax/rest/threshold), or — for the LTHR/%max methods only, whose Z1/Z5 are open-ended sentinels (0 bpm / 150 % of LTHR-or-FCmax, never real bounds — Karvonen's Z1/Z5 are already real) — `open_zone_floor_unknown` (Z1 needs `hr_rest_bpm` to have a real floor) / `open_zone_ceiling_unknown` (Z5 needs `hr_max_bpm` to cap the sentinel ceiling). **Never fabricate a bound when `bounds_bpm` is `null`; drop the HR target from that step (`no.target`) instead.**
- **`pace_target`** — `speed_low_ms`/`speed_high_ms` (m/s, already DTO-ready for `pace.zone` — do NOT convert) for a flat road step, ONLY for `recovery`/`endurance` (the only band #58's personal slope model validates confidently). `tempo`/`threshold`/`vo2max`/`race` come back `null` with `reason_code: "no_personal_pace_scaling_for_intensity"` — the project has no validated way yet to scale the endurance flat reference to a harder training effort; pilot those steps by HR zone instead, never a guessed pace. `source` says `personal`/`generic`/`mixed` (same provenance semantics as #58/#59); a non-`null` `reason_code` of `"extrapolated"` (pente beyond the fitted range) is informational only — the speed is still usable, mention it in passing.
- **`hill_repeats`** — for a session whose `structure` was recognized (`{"reps", "rep_duration_s", "grade_pct", "recovery_s"?}`, explicit or parsed from free text — see the CLI examples above): `per_rep.elevation_gain_m` is the **expected** D+ (a forecast from the slope-model speed at that grade × the rep duration, never a measurement) and `total_elevation_gain_m` is `reps ×` that. **`basis` says how to phrase it**: `"endurance_pace_lower_bound"` (the default `--band endurance`) means the underlying speed is the athlete's ENDURANCE-effort pace on that grade — a real hill repeat is usually run harder, so this D+ is a plausible **floor**, not a centered estimate: phrase the step description as "≥ X m D+", never "≈ X m D+". `"mixed_effort_estimate"` (`--band all`) mixes in harder historical efforts at that grade and is less systematically biased low, but still not guaranteed representative of THIS repeat's effort. Garmin's DTO has **no D+ target field** either way — put it in the step `description` for the athlete, never as a bogus numeric target. A non-positive `grade_pct` refuses to compute a D+ (`reason_code: "grade_not_positive"`) rather than emit a negative "gain".

- **`cs_target`** (#169, `tempo`/`threshold`/`vo2max` only) — a speed range as a % of the athlete's **critical speed** (`speed_low_ms`/`speed_high_ms`, m/s, GAP "flat-equivalent", DTO-ready for `pace.zone`; `d_prime_budget_s` for `vo2max` = cumulative time above CS that D′ allows at the upper bound). Present only when the CS fit is valid (≥ 2 sessions, ≥ 3 efforts of 3–20 min, R² ≥ 0.95); otherwise `speed_low_ms` is `null` with `reason_code` (`insufficient_points`, `single_source`, `poor_fit`…) → keep the HR-zone target only, never assume a CS. It complements `hr_target`: a pace target on a hilly step is GAP, so the real pace on a slope is slower — keep the HR zone as the arbiter. `--lt-speed-ms <m/s>` (Garmin lactate-threshold speed, converted by the caller) adds `cs_target.threshold_check`: a >5 % divergence is reported to the athlete with both numbers, never silently resolved.

`scripts/arc_workout_targets.py` also exposes `dto_hr_step`/`dto_pace_step` (build a ready `ExecutableStepDTO` from a target, low bound rejected if it exceeds the high bound) and `validate_workout_step_dto` (shape-checks a step against the tables above, including HR/pace range ordering) — use them instead of hand-rolling the JSON when the step carries a personal target.

## Heat-adjusted targets (#171)

On a hot (> 25 °C) or 🔴 forecast day, add `--heat` to the same command (`python3 scripts/arc_workout_targets.py targets --heat --session … [--slot morning|midday|evening] [--pace-s-km N]`; weather read from that day's indexed `medical/*_meteo.md`, or `--temp-c`). The result gains `heat_adjustment`, `pace_target.adjusted` and `trace`. Same pure function and coefficients as the race pacing (`scripts/arc_heat.py`, single source) — never compute the factor by hand.

- **HR target unchanged** (`hr_target` — HR is the reference). Only the pace is slowed: build the `pace.zone` step from `pace_target.adjusted.speed_low_ms`/`speed_high_ms` (still m/s, still low-then-high; already divided by the factor) instead of `pace_target` (for a critical-speed step, `cs_target.adjusted` instead of `cs_target`: same factor, #169; `d_prime_budget_s` is not recomputed), and append `heat_adjustment.step_note` to the step `description` (e.g. "chaleur 27 °C : allure × 1.1, FC inchangée") so the pushed workout carries the reason. Duration is kept.
- `action` `reschedule_or_lighten` / `reschedule_or_indoor` (🔴): do NOT push the original session; propose the move (or the endurance-at-HR / indoor alternative) and push only after the athlete confirms. For `reschedule_or_lighten` (quality, `intensity_maintained` false) there is no adjusted pace to push; for `reschedule_or_indoor` (easy/long), if the athlete explicitly keeps it outdoors, push `pace_target.adjusted` with the HR target unchanged.
- `action` `prefer_cool_slot`: propose the cool slot first; if the athlete takes it, re-run the command with `--slot morning|evening` and push THAT output; if they keep the hot one, push with the lowered pace targets.
- Persist `trace.heat_adjustment` on the session in the week file's `arc` block, then validate (`python3 scripts/arc_index.py --validate <file>`).

## Templates

### Simple Z1 run (TESTED — workout_id 1661521722)

```json
{
  "workoutName": "Footing Z1 40min",
  "description": "Footing récupération, strictement en Z1",
  "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
  "workoutSegments": [{
    "segmentOrder": 1,
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSteps": [{
      "type": "ExecutableStepDTO", "stepOrder": 1,
      "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
      "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
      "endConditionValue": 2400,
      "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
      "zoneNumber": 1
    }]
  }]
}
```

### Interval session (warmup + repeats + cooldown)

Use stepType 1/3/4/2 in order; distance steps use endCondition 3 with meters; repeats are plain consecutive steps (Garmin runs them in order, no group needed for simple ladders).

### Strength circuit WITH FULL DETAIL (TESTED — workout_id 1661524725)

Loop = `RepeatGroupDTO` with `numberOfIterations` + `endCondition` iterations(7). Exercise steps: `category`, `exerciseName`, reps via endCondition(10), optional `weightValue` + `weightUnit` `{"unitId": 8, "unitKey": "kilogram", "factor": 1000}`. Rest between exercises: stepType 5.

```json
{
  "workoutName": "Circuit Force Phase 3",
  "description": "Circuit complet: 2 series, repos 30s entre exercices, 1 min entre series",
  "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
  "workoutSegments": [{
    "segmentOrder": 1,
    "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
    "workoutSteps": [{
      "type": "RepeatGroupDTO",
      "stepOrder": 1,
      "numberOfIterations": 2,
      "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
      "workoutSteps": [
        {
          "type": "ExecutableStepDTO", "stepOrder": 1,
          "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
          "description": "Goblet Squat 12 reps",
          "endCondition": {"conditionTypeId": 10, "conditionTypeKey": "reps"},
          "endConditionValue": 12,
          "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
          "category": "SQUAT", "exerciseName": "BARBELL_SQUAT",
          "weightValue": 15,
          "weightUnit": {"unitId": 8, "unitKey": "kilogram", "factor": 1000}
        },
        {
          "type": "ExecutableStepDTO", "stepOrder": 2,
          "stepType": {"stepTypeId": 5, "stepTypeKey": "rest"},
          "description": "Repos 30s",
          "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
          "endConditionValue": 30,
          "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
        }
      ]
    }]
  }]
}
```

Known-good strength `category` values: `SQUAT`, `LUNGE`, `CARDIO`, `PLANK`, `BENCH_PRESS`, `PULL_UP`, `CURL`, `SHOULDER_PRESS`, `ROW`, `DEADLIFT`, `TRICEPS_EXTENSION`. `exerciseName` is free-text; unsupported names fall back to category `CARDIO`/`Other` on the watch. Timed core work (e.g. gainage): use endCondition time(2) with a `PLANK` category instead of reps.

**Library source (#191):** do not invent strength exercises — `python3 scripts/arc_index.py strength --phase <p> [--use <u>] [--equipment …] --garmin-json` returns this exact DTO (`workout_data`) with `category`/`exerciseName` only for pairs verified in Garmin's public catalogue (`GARMIN_VERIFIED` in `scripts/arc_strength.py`; 47 categories, checked 2026-10-04), plus the `create_strength_workout` arguments. An exercise without a verified pair is emitted WITHOUT `category`/`exerciseName` (French name in `description`) — never guess a key. Confirmation rules below are unchanged.

Alternative helper: `create_strength_workout(name, exercises)` — simpler but estimates 45s/set and loses structured reps/weight; prefer the structured JSON when detail matters.

## Workflow

1. Read the planned week from `planning/` (e.g. `Semaine_YYYY-MM-DD.md`) and the phase detail file for strength sessions.
2. **Guardrails (MANDATORY, #52/#53) — never skip, style/intensity never override it:** run `python3 scripts/arc_guardrails.py check --week <path|->` on the week about to be pushed (pipe its `week` JSON via `-` if it isn't written to disk yet). **Multi-week file (#69, `weeks[]`):** always pass `--week-start <monday of the week being pushed>` explicitly — without it, `check` defaults to the first week whose Monday is on `--today` or after, which on a Sunday is still the week that's ENDING, not the one you're about to push next.
   - **Exit 1 (block), interactive session:** push every OTHER session in the week normally — a block on one session never blocks the whole week. Do NOT push the flagged session as proposed; instead PROPOSE a safe alternative (easy/rest) in one sentence citing the violation's `message`, and write a `decision` file for it now (`workspace-data-contract` skill: `trigger: "guardrail"`, `rule_ids`, `before`/`after`, `session_ref`, `outcome: "proposed"`), validated (`python3 scripts/arc_index.py --validate <decision-file>`). Push the alternative only AFTER the athlete confirms it — never before. On confirmation: push it, write a NEW `decision` (`outcome: "applied"`, `supersedes: <path of the proposed decision>`), and set the proposed one's own `outcome` to `"superseded"`.
   - **Exit 1 (block), headless (`/garmin-daily-sync`):** never push nor apply the alternative on your own — record the proposal (`outcome: "proposed"`) and stop there; see that skill.
   - **Exit 0 with `warn`/`info`:** push proceeds; mention the warning briefly.
   - **Exit 2:** invalid input — report it, do not push.
3. Check `get_scheduled_workouts(start_date, end_date)` for the week — identify existing workout_ids per date and any stale entries (dedupe strategy per Idempotency section).
4. For each session, run `scripts/arc_workout_targets.py targets` (see "Personal targets" above) then build `workout_data` with the schema above, using its `hr_target`/`pace_target`/`hill_repeats` for the step targets. Strength sessions come from the plan's circuit detail.
5. Push via `schedule_workouts` with one `{calendar_date, workout_data}` per NEW session (reuse `workout_id` for unchanged ones).
6. VERIFY: `get_scheduled_workouts(start_date, end_date)` for the week → confirm each date, duration, name, and NO duplicates; `get_workout_by_id` for any structured detail (loops/reps/weight).
7. Persist: note the pushed session (workout_id, date) in the week's `planning/` MD file.

## Home trainer route (MyWhoosh)

Only when `[home_trainer].platform = "mywhoosh"` (skill `mywhoosh-route`): a `home_trainer`/`indoor_cycling`
session is pushed as `sportType` cycling (id 2) with the step target still the athlete's HR range
(`hr_target.bounds_bpm`, custom `heart.rate.zone`) — the route does not change the target. The chosen route goes in
the text the athlete sees on the watch and in Garmin Connect:

- `workoutName` = the suggestion's `garmin_workout_name` (e.g. `HT Z2 70min - Limmat Loop x2`) — short, so the watch
  shows the route;
- `description` = route, world, laps, predicted time with its ±10 % band, target power (a cue only) and
  « la FC commande ».

A Garmin power target (`power.zone`) is NOT used: its DTO has not been verified by this project, and HR stays the
reference. Idempotency is unchanged: a changed route = a changed session (delete the old `workout_id`, re-push).

## Reliability & Batching (tested 2026-08-11)

- **Keep batches small (≤ 4-5 schedules per call).** An 8-entry batch in ONE `schedule_workouts` call failed with a JSON parse error ("Expected ']'") on the live server. Split the week into chunks of 3-5 and push sequentially.
- **MCP timeouts happen** (observed: -32001 then -32000 connection closed, twice in a row). Retry once after a short pause; if it still fails, ask the user to restart the MCP server. Never assume a timeout = failure — ALWAYS re-verify with `get_scheduled_workouts` before re-pushing (avoids duplicate uploads).
- **Walking comes back as "mobility"** in `get_scheduled_workouts` responses (cosmetic; the watch handles it correctly). Don't treat it as a mismatch.
- **Race day / special events** (e.g. the 110km race on 13/09) are NOT pushed via workouts — flag in the planning MD file to create them manually on the watch.

## Stale-entry hygiene

Before pushing a new week, run `get_scheduled_workouts(start_date, end_date)` for the previous week and flag any `completed=false` entries that no longer match the plan (e.g. a 48km stale entry after the plan was cut to 38km). Delete with `unschedule_workout` or overwrite by rescheduling the date.
