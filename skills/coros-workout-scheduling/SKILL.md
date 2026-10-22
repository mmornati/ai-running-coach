---
name: coros-workout-scheduling
description: COROS watch scheduling. With `[data].source = "intervals"` (the recommended setup) sessions are pushed to Intervals.icu, which uploads the next 7 days to COROS — this skill then only checks arrival read-only with queryTrainingSchedule. Otherwise (e.g. Strava as source, or on explicit request) it pushes running / trail / cycling sessions through the official COROS MCP server (`coros`, OAuth, added by the athlete in an interactive session): verified tools (queryTrainingSchedule, createScheduledWorkout, queryScheduledWorkoutDetails, updateScheduledWorkout), course schema and per-sport limits (trail has no time target; strength cannot be created, only scheduled from the athlete's own COROS library templates with scheduleWorkout), personal targets converted and validated by scripts/arc_coros_workout.py, check-before-push idempotency (there is NO delete or move tool), verify-after-push. Interactive only, explicit "yes" per push, never headless.
---

# COROS Workout Scheduling

Push planned sessions onto the athlete's COROS calendar; the COROS app syncs them to
the watch. Tool names, parameters and behaviour below were **verified on 2026-10-22**
on an authenticated session (live tool list, one real push read back identically and
shown on a COROS PACE 4 Pro). Details and history: `docs/coros.md`.

## Intervals.icu first — the recommended path

**When `[data].source = "intervals"`, do NOT push with this skill.** Push to
Intervals.icu as usual (`intervals-icu-best-practices`): with the COROS connection
enabled in Intervals.icu (Settings → COROS → upload planned workouts), Intervals.icu
uploads the **next 7 days** of planned workouts to the COROS calendar itself. That path
already has everything this project built (personal targets in the native syntax,
check-before-push, verification, deletions and moves made in Intervals.icu follow on
COROS inside the 7-day window — as reported on the Intervals.icu forum), and it runs in
the headless sync, where this skill never does. Pushing the same session through both
paths creates a duplicate on the watch that only the COROS app can remove.

With that setup, the `coros` tools are used read-only, to check that a session arrived:
`queryTrainingSchedule` for the date. If it did not (upload disabled, date beyond 7 days,
HR zones not set or a syntax error on the Intervals.icu side, a connection filter), say
so and point to `docs/coros.md` — never re-push it through `createScheduledWorkout`
unless the athlete explicitly asks for it in this conversation.

Keep **one intensity metric per workout** (HR, as `intervals-icu-best-practices`
already does): Intervals.icu sends COROS a single metric per workout, and blocks written
in the other one arrive without target (reported on the forum, unfixed for COROS as of
August 2026).

Observed on 2026-10-22 (first week uploaded, read back with the `coros` tools):

- Sessions arrive inside a COROS training plan ("Plan d'entr. Intervals.icu"), listed by
  `queryTrainingSchedule`; `queryScheduledWorkoutDetails` does not find them, and the plan is
  "Editable via MCP: no". Fix sessions in Intervals.icu, never through the COROS tools.
- Steps, durations and repeats arrive. **HR targets arrive only as `% LTHR`**: `137-149bpm`
  reached the watch with no target, `80.6-87.7% LTHR` as exactly 137-149 bpm. Write them as
  `intervals-icu-best-practices` says (`arc_workout_targets.py --icu-lthr-bpm`).
- A session deleted in Intervals.icu disappears from the COROS calendar (verified).
- COROS keeps only the **first paragraph** of the description, cut around 250 characters:
  put what matters for the run (main HR range, key instruction) there.
- Strength (`WeightTraining`) sessions do arrive, as name + description only (no exercises).
  For a structured strength session on the watch, see "Strength sessions" below.

This skill's push path is for an athlete whose `[data].source` is NOT `intervals` (e.g.
`strava`), or who explicitly asks for a direct COROS push. Exception, whatever the source:
structured strength from the athlete's COROS templates ("Strength sessions" below).

## When this applies

- The `coros` MCP server is connected **in this interactive session** (its tools are
  callable): installed by `./install.sh --coros` (local relay `scripts/arc_coros_mcp.py`,
  one login for every AI client) or added by hand. COROS is **not** a `[data].source`
  value. If the tools are not exposed, say so and point to `docs/coros.md` — never guess a
  tool name. If a call answers "COROS non connecté" or "relancez … login", tell the athlete
  to run `python3 scripts/arc_coros_auth.py login` in a terminal (never run it yourself:
  it opens a browser).
- **Never headless** (`/garmin-daily-sync`, cron, Telegram): COROS writes cannot be
  undone through the MCP. Every push needs an explicit "oui" in the conversation, after
  you have shown the athlete what will be pushed (date, name, steps, targets).
- The planning rules are unchanged: morning check, medical decisions and guardrails
  (`python3 scripts/arc_guardrails.py check --week …`, see `garmin-workout-scheduling`
  → Workflow step 2) come first. A blocked or medically cancelled session is never
  pushed. This skill only decides HOW a validated session reaches the watch.

## Tools (server `coros`)

| Need | Tool | Notes |
|---|---|---|
| What is on the calendar | `queryTrainingSchedule(startDate?, endDate?)` | yyyyMMdd; default = current Mon–Sun week. Text: per date, name, source, `idInPlan`, distance, estimated time, load. Empty = "No training schedule found." |
| Push a new session on a date | `createScheduledWorkout(date, course)` | One call per session. `date` from today to today + 90 days (COROS profile timezone). Returns `idInPlan`. |
| Read a pushed session | `queryScheduledWorkoutDetails(date, idInPlan)` | Summary + `Course JSON` + `Editable via MCP: yes/no` (+ reasons). |
| Change a pushed session | `updateScheduledWorkout(date, idInPlan, course)` | **Full replacement** of that date's copy; always start from the Course JSON just read. Cannot move it to another date. Verified 2026-10-22: read back identical, same `idInPlan`, no duplicate. |
| The athlete's strength templates | `queryWorkoutLibrary(sportType=4)` | Name, estimated time, step count, Workout ID (never shown). See "Strength sessions". |
| Put a strength template on a date | `scheduleWorkout(workoutId, date)` | `workoutId` as a decimal **string**. Any sport of the athlete's library, strength included. Verified 2026-10-23. |

Not used by this project: `createTrainingPlan` / `updateTrainingPlan` /
`queryTrainingPlan*` (the plan lives in `planning/`, never duplicated as a COROS plan),
and the library tools `createSingleWorkout` / `updateWorkoutDetails` (a library template
is not needed to put a running/trail/cycling session on a date). `scheduleWorkout` and
`queryWorkoutLibrary` / `queryWorkoutDetails` serve strength only. **There is no delete, unschedule or move tool**: a wrong or stale
session can only be removed in the COROS app — tell the athlete exactly which one.

`idInPlan` is a small counter ("1", "2"; it does not always start at 1), not a global id: on
2026-10-23 a scheduled template and an Intervals.icu session on two other dates both had
`4`. Always designate a session by **date + `idInPlan`** together. Never show it to the
athlete; re-read it from `queryTrainingSchedule` when needed rather than storing it.

## Course schema

```json
{
  "sportType": 1,
  "courseName": "Endurance fondamentale 40 min + 4 lignes droites",
  "courseDescription": "40 min en aisance respiratoire, FC 137-149 bpm. Puis 4 lignes droites de 80-100 m à la sensation, retour en marchant.",
  "sections": [
    {"sectionType": 2, "targetType": 2, "targetValue": 2400,
     "intensityType": 1, "intensityValueStart": 137, "intensityValueEnd": 149},
    {"intervalGroup": true, "repeats": 4, "sets": [
      {"sectionType": 2, "targetType": 1, "targetValue": 100},
      {"sectionType": 3, "targetType": 2, "targetValue": 60}
    ]}
  ]
}
```

(The session actually pushed and read back on 2026-10-22.)

| Field | Values |
|---|---|
| `sportType` (session) | 1 running · 2 cycling · 5 trail running. **No strength (see "Strength sessions"), no other sport.** Not the activity codes (100 run, 102 trail…) seen in recorded activities. |
| `sectionType` | 1 warm-up · 2 training · 3 recovery · 4 cool-down (inside a group: 2 or 3 only) |
| `targetType` | 1 distance (m) · 2 time (s) · 3 climb (m) · 4 free (lap button, no `targetValue`) |
| per sport | running / cycling: 1, 2, 4 · **trail: 1, 3, 4 — no time target** |
| `intensityType` | 1 HR · 2 pace (s/km, ground pace) · 3 % effort threshold pace (trail only, zone or % only) · 4 power (W) |
| intensity format | exactly ONE of `sectionIntensity` (zone) / `intensityPercentStart`+`End` / `intensityValueStart`+`End` (absolute), on each plain section, never on the course or on a group |
| group | `{"intervalGroup": true, "repeats": 1-20, "sets": [...]}`, no target or intensity on the container, no nesting |

`courseName` (≤ 100 chars) and `courseDescription` are shown on the watch exactly as
written: plain coaching French (documents language), never field names or enum numbers.

## Personal targets — never COROS's own zones

Compute targets with `scripts/arc_workout_targets.py targets --session <week file>#<date>`
exactly as in `garmin-workout-scheduling` → "Personal targets (#60)" (including
`--heat` on a hot or 🔴 day: HR unchanged, pace slowed, `heat_adjustment.step_note`
appended to the description). Then build each section with the helper — never convert
units by hand:

```bash
python3 scripts/arc_coros_workout.py section --duration-s 2400 --hr 137 149
python3 scripts/arc_coros_workout.py section --distance-m 1000 --speed-ms 2.38 2.63   # m/s -> s/km
python3 scripts/arc_coros_workout.py section --type recovery --duration-s 60           # no target
```

- Use **absolute bpm** (`hr_target.bounds_bpm`) and absolute pace. Never COROS zones
  (`sectionIntensity`) nor `%LTHR` / % threshold pace: they are computed from COROS's own
  thresholds, not from the athlete's profile, and a new watch has not calibrated them.
- A `null` target in `arc_workout_targets.py` → leave that section without intensity
  (and say why in the description), never a guessed value. Same for a step the plan
  prescribes "à la sensation" (strides).
- Pace only on flat steps, as for Garmin; never on a climb.

### Trail sessions (no time target)

A trail session prescribed in minutes cannot carry a time target. Never turn minutes into
a guessed distance. Ask the athlete once which they prefer, then keep it:

- **trail + free sections** (`targetType 4`, lap button): the watch records a trail
  activity; the planned duration goes in the description ("6 min — appuie sur Tour"); or
- **running** (`sportType 1`) with time targets, if the session is mostly runnable.

Verified 2026-10-22: free sections show as "Manuel" in the COROS app and keep their HR
target; a climb rep shows as "30 m" with the climb icon. With free sections COROS gives no
time, distance or load estimate — do not report one.

A climb target (`targetType 3`) is used only when the plan states a D+ per repetition
(e.g. "≥ 27 m D+ par répétition", from `hill_repeats`): the rep ends at that D+.

## Strength sessions — the athlete's own templates (verified 2026-10-23)

The MCP cannot create, read or edit a strength workout ("COROS sport type 4 (Strength)
cannot be expressed by MCP"). It can **schedule** one the athlete built in the COROS app:

1. **Templates, once, by the athlete.** In the COROS app, one template per strength session
   the coach prescribes; usually 1-3, redone at a phase change. Give them the sheet copied
   from the week file (exercises, rounds, reps or holds, per side), never invented; a rest the plan does not state is their choice — say so.
   App facts seen 2026-10-23: a side = a separate exercise entry (or one entry "par côté"),
   reps "N fois", holds "00:30", rounds as a "Répéter N fois" block, an exercise can sit
   outside the block. French catalogue names: « Crunch », « Chien d'oiseau » (bird-dog),
   « Couché sur le dos Pont des fessiers », « Extension mollets debout », « Gainage
   latéral », « Étirement du chat et de la vache ». A McGill curl-up has no exact entry
   (« Crunch » + a note: hold 10 s, one knee bent, hands under the lower back).
2. **Find it**: `queryWorkoutLibrary(sportType=4)`. `queryWorkoutDetails` returns only
   name and sport (empty Course JSON, `Editable via MCP: no`): **you cannot check the
   exercises** — say so; the app or the watch is the only proof. A step count or an
   estimated time far from the prescription is worth one line ("30 min estimées pour une
   séance de 15 min : vérifie les séries dans l'app").
3. **Match** the week's strength session to a template by name. None or ambiguous → ask,
   never guess. If the day's prescription differs from the template (e.g. a 1-round
   "activation" vs the 3-round template), say it in one line and let the athlete choose.
4. Explicit "oui", then `scheduleWorkout(workoutId, date)`. Same date window as above; the
   same template already on that date is not copied again.
5. **Frozen copy**: the date gets a copy of the template as it is now. Editing the
   template later does not change it, and the MCP cannot edit the copy: template edits
   first, schedule after. No delete or move: the COROS app.
6. **Verify**: `queryTrainingSchedule` lists it as "Standalone workout (scheduled from the
   workout library)" with COROS's estimated time (verified 2026-10-23, then seen on the
   watch with its exercises).

**One channel per session.** With `[data].source = "intervals"`, a strength session
scheduled this way is **not** pushed to Intervals.icu (its text version would reach the
watch as a second session). If `queryTrainingSchedule` already shows the Intervals.icu copy
on that date, do not schedule over it: offer to delete that Intervals.icu event first
(`icu_delete_event`, its own explicit "oui"; it then leaves COROS), or keep the text version.

## Threshold pace (critical-speed check)

`queryFitnessAssessmentOverview` returns COROS's `Threshold Pace` (text, e.g. `4:12 /km`, read on
2026-10-22). For the `--lt-speed-ms` check of `arc_workout_targets.py` / `arc_index.py pace-curve`,
convert it with `python3 scripts/arc_coros_workout.py threshold --pace 4:12` (→ `lt_speed_ms`), never
by hand, and name it « allure seuil COROS ». It is never a target in itself.

## Workflow

1. Read the session(s) from `planning/Semaine_<monday>.md`; apply guardrails/morning
   check as above. Rest and race-day sessions are not pushed: say so in one line.
   Strength goes through "Strength sessions" above (a template, never a created course).
2. `queryTrainingSchedule(<first date>, <last date>)` for the range to push.
3. Per session, build the course (targets above), then validate it:
   `python3 scripts/arc_coros_workout.py validate --file <course.json>` (or JSON on
   stdin). Exit 1 = fix it, never push an invalid course.
4. Show the athlete what will be pushed and get an explicit "oui".
5. Idempotency, per date, against step 2:
   - no session with that name on that date → `createScheduledWorkout`;
   - same name, same content → nothing to do;
   - same name, content changed → `queryScheduledWorkoutDetails`; if `Editable via MCP: yes`,
     `updateScheduledWorkout` with the full new course; if not (past date, already done),
     tell the athlete the reason, never create a second copy;
   - a session that no longer matches the plan → ask the athlete to delete it in the app.
6. Verify: `queryScheduledWorkoutDetails` for each pushed session — its Course JSON must
   equal what was sent (it did on 2026-10-22) — and `queryTrainingSchedule` for the range
   (no duplicate on any date). Report the COROS estimate (time, distance, load) as COROS's
   estimate, never as a project figure.
7. One line in the week file's free text: "Poussée vers le calendrier COROS le <date>."
   (No `arc` field yet: the calendar itself is the idempotency source.)
