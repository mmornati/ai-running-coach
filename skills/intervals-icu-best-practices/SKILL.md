---
name: intervals-icu-best-practices
description: Use when creating, updating, or troubleshooting Intervals.icu events or workouts via the Intervals.icu MCP tools (add_or_update_event, get_events, delete_event). Covers the description-vs-workout_doc pitfall, start_date preservation, post-update verification, and tested JSON payload patterns.
---

# Intervals.icu MCP Tool — Best Practices

## Problem Identified

When creating events via `add_or_update_event`, the `description` field appears to be stored but NOT returned in the GET response (API returns `"description": null"`).

**However**, older events (pre-March 2026) do show descriptions — this suggests either:
1. API change between calls
2. Different parameter name required now
3. Need to use `workout_doc` for structured workouts

## Solution: Use workout_doc

According to the Intervals.icu forum, the preferred method is to use `workout_doc` with structured JSON steps:

```json
{
  "category": "WORKOUT",
  "start_date_local": "2026-03-10T10:00:00",
  "type": "Ride",
  "name": "Lactate Test",
  "workout_doc": {
    "steps": [
      {
        "duration": 300,
        "power": { "units": "%ftp", "value": 90 }
      }
    ]
  }
}
```

## MCP Tool Schema

The `add_or_update_event` tool DOES accept `workout_doc` as a parameter:

```
- athlete_id (optional)
- api_key (optional)
- event_id (optional)
- start_date (optional)
- name (optional)
- workout_doc (optional) ✅
- workout_type (optional)
- moving_time (optional)
- distance (optional)
```

## Recommended Approach

1. **For simple events**: Use `description` as text — it IS stored even if not returned in GET
2. **For structured workouts**: Use `workout_doc` with proper JSON structure

## Tested Working Pattern (verified 2026)

```json
{
  "event_id": "EXISTING_ID",
  "name": "Session Name",
  "start_date": "YYYY-MM-DD",
  "moving_time": 2400,
  "workout_type": "Other",
  "workout_doc": {"description": "Details..."},
  "description": "Short details..."
}
```

Note: Use `workout_doc.description` for detailed workout content, `description` for summary.

## Date Handling Rules

- **`start_date` is REQUIRED and SETS the event date.** Always verify the intended date before calling `add_or_update_event`.
- **Post-update verification:** After ANY create/update operation, ALWAYS call `get_events` to verify the date matches the intended date. If mismatched, update again with the correct date.
- **Batch operations:** Track each update and verify completion before reporting success.

## Example — Strength Session with workout_doc

```python
workout_doc = {
  "steps": [
    {"description": "Échauffement", "duration": 600},
    {"reps": 4, "steps": [
      {"text": "Goblet Squat", "duration": 45, "weight_kg": 12},
      {"text": "Fentes Bulgares", "duration": 45},
      {"text": "Step Up", "duration": 45}
    ]}
  ]
}
```

## Manual Workaround

Since the API seems inconsistent:
1. Create the event with `description`
2. Edit manually in the Intervals.icu UI if needed
