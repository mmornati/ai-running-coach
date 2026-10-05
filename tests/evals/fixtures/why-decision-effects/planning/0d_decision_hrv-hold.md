# Décision du {{DATE}} — allégement HRV

```arc
{"arc": 1, "kind": "decision", "date": "{{DATE}}", "created_at": "{{DATE}}T06:45:00+02:00", "trigger": "morning_check", "summary": "HRV sous la bande personnelle — VO2max allégée en footing endurance.", "outcome": "applied", "inputs": {"hrv_personal_status": "sous", "hrv_overnight_ms": 41, "hrv_personal_low_ms": 48, "hrv_personal_high_ms": 74}, "rule_ids": ["r5_quality_after_red"], "sources": ["medical/{{DATE}}_health.md"], "before": {"title": "VO2max 6 x 3 min", "intensity": "vo2max", "status": "planned"}, "after": {"title": "Footing endurance 45 min (remplace VO2max)", "intensity": "endurance", "status": "planned"}, "session_ref": {"week": "planning/{{TODAY}}_semaine.md", "date": "{{DATE}}"}}
```

HRV overnight sous la bande personnelle (41 ms, bande 48-74) : la séance
VO2max initialement prévue a été remplacée par un footing endurance.
