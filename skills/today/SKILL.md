---
name: today
description: Short daily command — invoked as /today. Reports today's session from the current week file (kind "week" in planning/), the morning check at the configured [health].morning_check level, and the weather slot when the session is outdoor. One-line verdict first. Never writes a plan/week/decision/race-plan file and never pushes to Garmin — but DOES persist the day's health/weather files the freshness rules already require. Load when the user runs /today or asks "what's today's session".
gemini_command: "true"
---

# `/today` — thin daily status command

This skill adds **no new coaching logic**: it is a short, predictable wrapper
that asks the `coach` agent (or does the equivalent work itself, see below)
for exactly today's status, in a fixed short format suitable for a phone
screen. It never asks a question.

## What "no write" means here

This command never writes or edits a **plan, week, decision, or race-plan**
file, and never calls a Garmin/calendar write tool
(`schedule_workouts`/`schedule_week`/`upload_workout`/`unschedule_workout`/
`upload_course`, or any equivalent). It is **not** a promise that no file is
ever touched: the day's health check (`medical/YYYY-MM-DD_health.md`) and
weather (`medical/YYYY-MM-DD_meteo.md`) files that the usual freshness rules
already require are fetched and persisted exactly as any other command would
— that data does not otherwise exist, and skipping the write would just mean
re-fetching it on every future call, which is what the freshness rules exist
to prevent.

## Configuration read first

`config/workspace.toml` then `config/workspace.user.toml` (its values win,
key by key) — `[language].responses` (output language; when it is `auto` and
the command is invoked bare, with no natural-language text to infer a
language from, fall back to `[language].documents`), `[coaching].verbosity`
(`brief`/`standard`/`detailed`, see `config/coaching-styles.md`),
`[health].morning_check` (`full`/`minimal`/`off`), `[agents].enabled`,
`[athlete].units`.

## Delegation

If `coach` is in `[agents].enabled` (or the key is absent, meaning every
agent is reachable) **and** a `task`/subagent tool is available, delegate to
the agent **`coach`**, prompt in English plus **"Respond in <language of
`[language].responses`, falling back to `[language].documents` if `auto` and
the request is bare>"**:

> Status check, NOT a full validation: report today's session from the
> current week file — find it by `kind: "week"` inside `planning/*.md`
> (never by filename pattern: a multi-week plan, #113, may name the file
> after its first Monday while covering later weeks too) — and the morning
> check at the configured `[health].morning_check` level (see
> `agents/coach.md`'s morning-check section for the exact triad/single-metric
> rules). If today's session is outdoor, load the `weather-forecast` skill
> and report the recommended time slot; if no location resolves, report
> "lieu inconnu" (or its translation) instead of asking a question — this
> command never blocks on a question. Do **not** validate, adjust, cancel, or
> propose changing anything, do **not** write or edit any plan/week/decision/
> race-plan file, do **not** call `schedule_workouts`/`schedule_week`/
> `upload_workout`/`unschedule_workout`/`upload_course`/any Garmin write tool
> — persisting today's health/weather files under the usual freshness rules
> (skip the fetch if the file already exists) is the only writing this
> command does. Reply using the exact output contract below.

If `coach` is not enabled, **or if you cannot delegate at all (no `task`/
subagent tool available, e.g. running as a bare Gemini CLI command)**, do
this yourself, within your own competence, without naming a missing agent:
read `planning/active_objective.md` and the current week file for today's
session, apply the morning-check rules directly (see below), and load
`weather-forecast` yourself for an outdoor session (never asking a question
if the location does not resolve — see above).

## Morning check — exact behaviour per level

- `full` (default): the triad is indivisible — HRV (`get_hrv_data`), resting
  heart rate (`get_rhr_day`) and training readiness (`get_training_readiness`),
  all three, never two. Skip the fetch and reuse the value if today's
  `medical/YYYY-MM-DD_health.md` already exists (freshness rule).
- `minimal`: `get_training_readiness` only, one line. Never call
  `get_hrv_data` or `get_rhr_day`, never mention HRV or resting heart rate,
  never cancel or flag a session on health data alone at this level.
- `off`: no health tool is called at all (`get_hrv_data`, `get_rhr_day`,
  `get_training_readiness` all absent from the trace) — plan on load, history
  and declared feeling only.

Never silently upgrade to a stricter level than configured.

**`[data].source = "coros"` (#168).** Same levels, COROS tools (table « Garmin ↔ COROS » of
`AGENTS.md`): HRV → `querySleepHrv`, resting HR → `queryRestingHeartRate`, readiness →
**COROS recovery** (`queryRecoveryStatus`), dates = wake-up day (last night = today). Say « récupération
COROS N % », never « Training Readiness », never against Garmin's thresholds; at `minimal` that is the
one line. Night not published yet (`Sleep Score: 0`, HRV « No data found », resting HR `No data` for
today): say it in one line (« sommeil COROS pas encore synchronisé ») and plan on load, history and
declared feeling — recovery alone never stands in for the night, never « tout va bien ».

**`[health].source` (#221, opt-in).** Resolve it (`primary` default; absent, empty or
unknown = `primary`). At `primary` nothing above changes and you never mention Open
Wearables. At `openwearables` (and `morning_check` not `off`), the health data comes from
ONE call, `python3 scripts/arc_openwearables.py health-day --json`, instead of the three
Garmin tools (none of them is called): `full` = HRV (RMSSD) + resting HR + the maker's native
score named as such (« Readiness Oura 82/100 », « Nightly Recharge Polar 4/6 », never
« Training Readiness », never rescaled), or « readiness indisponible — <maker> via Open
Wearables »; `minimal` = that one line only. An unreachable instance, a missing night or stale
data is said in one line (never « tout va bien »), and the session is planned on load, history
and declared feeling. Details: `agents/coach.md`, section HEALTH SOURCE.

## Output contract

**First line, fixed shape, one-line verdict** — start the line with the
translated word for "Today" (French default: "Aujourd'hui"), optionally
wrapped in Markdown emphasis or preceded by a heading marker, then an em
dash/en dash/hyphen, then the verdict:

```
Aujourd'hui — <verdict court : séance prévue / repos / à ajuster + le motif en quelques mots>
```

(`# Aujourd'hui —`, `**Aujourd'hui** —`, or a plain `Aujourd'hui -` are all
acceptable renderings of the same fixed shape — the wording "Aujourd'hui",
the dash, and the verdict after it are what is fixed, not the exact
punctuation around them.)

Then, respecting `[coaching].verbosity` (`brief` = 3-5 lines total,
`standard` = a short paragraph plus the key figures, `detailed` = adds the
reasoning) and `[health].morning_check`:

- the session itself (type, duration/distance, intensity) or "repos" if none
  is planned;
- the morning-check line(s) at the configured level (nothing at `off`);
- a weather + time-slot line **only** when the session is outdoor (skip this
  line entirely for an indoor/rest day — never invent a slot for a session
  that has none; "lieu inconnu" if the location itself does not resolve).

No question, no proposal to act, no mention of `/coach-setup` here even on a
fresh install (this command answers a factual question, it does not onboard
— see AGENTS.md's "Premier démarrage" section for this exception). If no
`active_objective.md`/week file exists yet, say so in one line rather than
inventing a session.
