---
name: garmin-sync-efficiency
description: Use when fetching Garmin data (activities, sleep, HRV, training readiness, health metrics) via the garmin MCP server. Prevents context-window bloat — fetch specific dates only, persist to Markdown immediately, never dump raw JSON into the conversation.
---

# Garmin Sync Efficiency

Garmin MCP responses are verbose JSON. Pulling wide date ranges or raw payloads into the conversation causes rapid context-window exhaustion (observed: 5 context compressions in a single coaching session). Follow these rules strictly.

## Tool Access

All Garmin tools are exposed by the `garmin` MCP server (direct mode) or via `leanproxy_invoke_tool(server="garmin", ...)` (power-user mode). Useful tools include `get_sleep_data`, `get_hrv_data`, `get_rhr_day`, `get_training_readiness`, `get_activities`, `upload_course`, `upload_workout`, `get_courses`.

**`[data].source = "intervals"` (#68):** this whole skill still applies (check
local files first, one date per call, persist immediately, no raw JSON) —
against the `intervals` MCP server instead, whose tools cover the same needs
with fewer calls: `icu_get_wellness_for_date` alone returns sleep + HRV + resting
HR (rules 3 above still apply, one call is still "one fetch"), `icu_get_recent_activities`
replaces `get_activities` (all tools of the `intervals` server are prefixed `icu_`). No equivalent for `get_training_readiness`, `upload_course`
or `upload_workout` — see the correspondence table in `AGENTS.md`.

> **Resting HR:** use `get_rhr_day(date)`. It returns the value directly. `get_sleep_data` also contains it, but that payload can exceed 400 KB — never pull it just to read resting HR.

## Rules

1. **Check local files first — but "exists" is not "synced".** Before invoking any Garmin
   tool, look for today's file in `activities/` (`YYYY-MM-DD_type.md`) or `medical/`
   (`YYYY-MM-DD_health.md`). If it exists AND carries the "synced" marker below, work from
   the file — do NOT re-fetch. If it exists but does NOT carry that marker, it is **not yet
   synced** — go fetch it like a missing date, then MERGE (rule 1a) rather than skip.
1a. **"Not yet synced" marker (#67).** The `/log` skill may create a minimal `activities/`
   or `medical/` file, before any sync ran that day, holding only athlete-declared
   fields. That file is "not yet synced": an `activities/*.md` file with **no activity id
   for the configured source** — `garmin_activity_id` at `[data].source = "garmin"` (default),
   `intervals_activity_id` at `"intervals"` (#68 — check the field matching the CONFIGURED
   source, never both, never the wrong one: an intervals-mode file with no
   `intervals_activity_id` is not yet synced even if it happens to carry an unrelated
   `garmin_activity_id` from before a source switch) — or a `medical/*.md` file with **none of**
   `hrv_overnight_ms`, `resting_hr_bpm`, `readiness_score`, `sleep_total_s` (health keys are
   the SAME regardless of source — see the correspondence table in `AGENTS.md`; no
   source-specific health marker exists). Its presence must never suppress
   that day's fetch. Once fetched, MERGE the fetched fields into that SAME file — never write
   a second file for the same date/session — and **never overwrite an athlete-declared key**:
   `carbs_g`, `fluid_intake_ml`, `rpe`, `gear_id`, `gear_ids`, `weight_pre_kg`, `weight_post_kg`
   (activity) and `pain` (health) come from the athlete, so the merge is a plain union — add the
   new keys, keep the declared ones byte-for-byte. Exception to "neither source has such a field"
   (#133): Garmin can attach gear to an activity (`get_activity_gear`, see rule 7) — but a
   `gear_id` already in the file always stays, the Garmin gear never overrides it.
   A file that already carries the marker (a real prior sync) is fresh and final — merge
   never applies to it, only to a not-yet-synced one. A synced health file that genuinely has
   no HRV/RHR that day (the source returned nothing, e.g. watch not worn overnight), or a manual
   activity with no watch involved at all, will keep matching this marker and so gets
   re-fetched on every run within `lookback_days` — harmless (an idempotent no-op merge, at
   most a wasted API call), never a data-corruption risk, so don't special-case it.
2. **Fetch specific dates only.** Query one date (today or yesterday) per call. Never pull multi-week ranges into the conversation.
3. **Persist immediately.** After each fetch, write the file to `activities/` or `medical/` FIRST — ```arc block on top (see `workspace-data-contract`), prose in the document language below — then analyze from the written file.
4. **Never paste raw JSON** into the conversation or reasoning. Extract the fields you need into the MD file; discard the rest.
5. **One sync per day.** Garmin data for a past date does not change — if a file for that date exists AND is already synced (rule 1a's marker present), trust it.
6. **Batch writes, not fetches.** When multiple days are missing or not-yet-synced, fetch day-by-day and write/merge each file as you go, rather than accumulating responses in context.

7. **Gear (#133): one `get_activity_gear(activity_id)` call per NEW activity, never more.**
   Only for an activity being synced for the first time in this run (rule 1a marker absent
   before the fetch) — an already-synced activity's gear is in its file, trust it (rule 5).
   `get_gear` (the inventory) is called only for the one-time mapping proposal in
   `agents/coach.md`, with `include_stats=False` (`True` costs one extra Garmin API call per
   piece of gear) unless lifetime totals are needed to seed `départ`. Both are read-only;
   `add_gear_to_activity` is a WRITE on Garmin: never in a headless run, only after the athlete
   confirmed in the conversation. `get_activity_gear` answers with a plain text
   ("No gear data found for activity with ID N") when nothing is attached — that is "no gear",
   not an error. The attribution rule itself (athlete's declaration > Garmin > default) lives in
   `python3 scripts/arc_index.py gear-attribution`, never re-derived by hand.

## Minimal Extraction Pattern

For each day, extract only what the file's ```arc block needs (schema: the
`workspace-data-contract` skill — SI units, an unmeasured value is omitted, never 0):

- **Sleep** → `sleep_total_s`, `sleep_deep_s` / `sleep_light_s` / `sleep_rem_s` / `sleep_awake_s`, `sleep_score`, `sleep_start` / `sleep_end`
- **HRV** → `hrv_overnight_ms`, `hrv_baseline_low_ms` / `hrv_baseline_high_ms`, `hrv_status`
- **Resting HR** → `resting_hr_bpm` — **always** when `[health].morning_check = "full"`, never "if relevant". Safety rules depend on it, and it is what separates autonomic stress from systemic overload.
- **Readiness** → `readiness_score`, `readiness_factors`
- **Activity** → `garmin_activity_id`, `sport`, `duration_s`, `moving_duration_s` (`[data].source = "intervals"` : `elapsed_time_seconds` / `moving_time_seconds` of `icu_get_activity_details` — never `duration_s` from `icu_get_recent_activities`, which only returns the moving time, see `AGENTS.md`), `distance_m`, `elevation_gain_m` / `elevation_loss_m`, `avg_hr_bpm` / `max_hr_bpm`, `recovery_hr_bpm`, `training_effect_aerobic` / `training_effect_anaerobic`, `calories_kcal` (`[data].source = "intervals"` : `nutrition.calories_burned` of `icu_get_activity_details`, #165), `calories_bmr_kcal` (copy `get_activity`'s `bmr_calories` field verbatim, never recomputed; `[data].source = "intervals"` has no known equivalent field, see the correspondence table in `AGENTS.md` — omit the key rather than guess), and the per-km `splits`
- **Gear** (#133, garmin source, new activities only) → `gear_id` + `gear_source`, taken from `arc_index.py gear-attribution`'s output, never from your own reading of `get_activity_gear`
- **Body** → `weight_kg`, `stress_avg`, `body_battery_high` / `body_battery_low` (if relevant)

Which health keys are expected follows `[health].morning_check`: `minimal` → readiness
only; `off` → no health file at all.

Everything else in the response is noise — drop it.
