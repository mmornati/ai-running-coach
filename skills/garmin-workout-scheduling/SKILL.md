---
name: garmin-workout-scheduling
description: Use to push planned training sessions directly to the Garmin Connect calendar via leanproxy (server="garmin", tools schedule_workouts / schedule_week / upload_workout). Covers the exact Garmin DTO JSON schema, step/endCondition/targetType/sportType lookup tables, idempotency, strength-workout detail (exercises, reps, weight, rest, RepeatGroupDTO loops), and the verify-after-push pattern. Garmin calendar is the PRIMARY scheduling destination; Intervals.icu is secondary.
---

# Garmin Workout Scheduling — Garmin Calendar First

Push planned sessions straight onto the Garmin Connect calendar. **Garmin is the primary destination**; Intervals.icu is secondary (only if the user explicitly wants events there). All schemas below are TESTED on the live Garmin API via `garmin-mcp`.

## Tool Access

Everything via `leanproxy_invoke_tool` with `server: "garmin"`:

- `garmin_schedule_workouts(schedules)` — **preferred**: list of `{calendar_date, workout_id}` OR `{calendar_date, workout_data}` (upload + schedule in ONE call).
- `garmin_schedule_week(week)` — list of `{date, workout_id}` for an existing workout.
- `garmin_schedule_workout(workout_id, calendar_date)` — single schedule of an existing workout.
- `garmin_upload_workout(workout_data)` — create a library workout without scheduling.
- `garmin_get_workout_by_id(workout_id)` / `garmin_get_workouts` / `garmin_get_scheduled_workouts(start_date, end_date)` — verification.
- `garmin_delete_workout(s)` / `garmin_delete_scheduled_workout(s)` — cleanup stale calendar entries.

## Idempotency — CRITICAL CORRECTION (tested 11 Aug 2026)

- **Inline `workout_data` is NOT idempotent.** Each `schedule_workouts` call with inline `workout_data` UPLOADS A NEW workout and schedules it — re-pushing a date with new data leaves the OLD workout scheduled alongside it (observed duplicate on 2026-08-19).
- **`workout_id` path IS idempotent** per date (rescheduling same id overwrites without duplicating).
- **SAFE PATTERN — check before push:** BEFORE pushing a date, call `garmin_get_scheduled_workouts(start_date, end_date)`. If a workout already exists for that date:
  - Same session + same detail → reuse its `workout_id` via `schedule_workouts`/`schedule_week` (idempotent).
  - Session changed → `garmin_delete_workout(old_workout_id)` then push fresh `workout_data`.
- After ANY push, ALWAYS verify with `garmin_get_scheduled_workouts(start_date, end_date)` and (for detail) `garmin_get_workout_by_id(workout_id)`. Watch for duplicates on the same date.

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
- **Custom bpm range**: `targetValueOne` / `targetValueTwo` (low/high bpm) with `heart.rate.zone` target.

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

Alternative helper: `garmin_create_strength_workout(name, exercises)` — simpler but estimates 45s/set and loses structured reps/weight; prefer the structured JSON when detail matters.

## Workflow

1. Read the planned week from `planning/` (e.g. `Semaine_YYYY-MM-DD.md`) and the phase detail file for strength sessions.
2. Check `garmin_get_scheduled_workouts(start_date, end_date)` for the week — identify existing workout_ids per date and any stale entries (dedupe strategy per Idempotency section).
3. For each session, build `workout_data` with the schema above. Strength sessions come from the plan's circuit detail.
4. Push via `garmin_schedule_workouts` with one `{calendar_date, workout_data}` per NEW session (reuse `workout_id` for unchanged ones).
5. VERIFY: `garmin_get_scheduled_workouts(start_date, end_date)` for the week → confirm each date, duration, name, and NO duplicates; `garmin_get_workout_by_id` for any structured detail (loops/reps/weight).
6. Persist: note the pushed session (workout_id, date) in the week's `planning/` MD file.

## Reliability & Batching (tested 2026-08-11)

- **Keep batches small (≤ 4-5 schedules per call).** An 8-entry batch in ONE `schedule_workouts` call failed with a JSON parse error ("Expected ']'") on the live server. Split the week into chunks of 3-5 and push sequentially.
- **MCP timeouts happen** (observed: -32001 then -32000 connection closed, twice in a row). Retry once after a short pause; if it still fails, ask the user to restart the MCP server. Never assume a timeout = failure — ALWAYS re-verify with `garmin_get_scheduled_workouts` before re-pushing (avoids duplicate uploads).
- **Walking comes back as "mobility"** in `get_scheduled_workouts` responses (cosmetic; the watch handles it correctly). Don't treat it as a mismatch.
- **Race day / special events** (e.g. the 110km race on 13/09) are NOT pushed via workouts — flag in the planning MD file to create them manually on the watch.

## Stale-entry hygiene

Before pushing a new week, run `garmin_get_scheduled_workouts(start_date, end_date)` for the previous week and flag any `completed=false` entries that no longer match the plan (e.g. a 48km stale entry after the plan was cut to 38km). Delete with `garmin_delete_scheduled_workout` or overwrite by rescheduling the date.
