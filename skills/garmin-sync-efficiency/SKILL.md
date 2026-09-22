---
name: garmin-sync-efficiency
description: Use when fetching Garmin data (activities, sleep, HRV, training readiness, health metrics) via the garmin MCP server. Prevents context-window bloat — fetch specific dates only, persist to Markdown immediately, never dump raw JSON into the conversation.
---

# Garmin Sync Efficiency

Garmin MCP responses are verbose JSON. Pulling wide date ranges or raw payloads into the conversation causes rapid context-window exhaustion (observed: 5 context compressions in a single coaching session). Follow these rules strictly.

## Tool Access

All Garmin tools are exposed by the `garmin` MCP server (direct mode) or via `leanproxy_invoke_tool(server="garmin", ...)` (power-user mode). Useful tools include `get_sleep_data`, `get_hrv_data`, `get_rhr_day`, `get_training_readiness`, `get_activities`, `upload_course`, `upload_workout`, `get_courses`.

> **Resting HR:** use `get_rhr_day(date)`. It returns the value directly. `get_sleep_data` also contains it, but that payload can exceed 400 KB — never pull it just to read resting HR.

## Rules

1. **Check local files first.** Before invoking any Garmin tool, look for today's file in `activities/` (`YYYY-MM-DD_type.md`) or `medical/` (`YYYY-MM-DD_health.md`). If it exists and is fresh, work from the file — do NOT re-fetch.
2. **Fetch specific dates only.** Query one date (today or yesterday) per call. Never pull multi-week ranges into the conversation.
3. **Persist immediately.** After each fetch, write the structured French Markdown file to `activities/` or `medical/` FIRST, then analyze from the written file.
4. **Never paste raw JSON** into the conversation or reasoning. Extract the fields you need into the MD file; discard the rest.
5. **One sync per day.** Garmin data for a past date does not change — if a file for that date exists, trust it.
6. **Batch writes, not fetches.** When multiple days are missing, fetch day-by-day and write each file as you go, rather than accumulating responses in context.

## Minimal Extraction Pattern

For each day, extract only what the MD file needs:
- **Sleep**: duration, deep/light/REM split, sleep score
- **HRV**: overnight average, status vs baseline
- **Resting HR**: value of the day and delta vs the athlete's recent baseline — **always**, never "if relevant". Safety rules depend on it, and it is what separates autonomic stress from systemic overload.
- **Readiness**: score, contributing factors
- **Activity**: type, duration, distance, D+, avg/max HR, training effect, calories
- **Body**: weight, stress, body battery (if relevant)

Everything else in the response is noise — drop it.
