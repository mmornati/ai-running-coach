---
name: weather-forecast
description: Use when fetching weather forecasts (wttr.in via webfetch) for the user's training location, persisting per-day MD files, resolving the effective location (week-file override → active_objective → profile → ask), and producing optimal time-of-day (matin tôt / midi / soir) recommendations for outdoor sessions. Used by the coach subagent on every weekly/daily plan validation.
---

# Weather Forecast — Skill

Fetch prévisions météo pour le lieu d'entraînement de l'athlète, persister un MD par jour, et recommander le créneau optimal (matin tôt / midi / soir) pour chaque séance outdoor.

## Tool d'accès

**Unique tool :** `webfetch` sur `https://wttr.in/{ville}?format=j1` (et `?format=j2` pour 2 jours supplémentaires si horizon 7 jours).

- `j1` = prévisions du jour + J+1 (max 3 jours détaillés par appel)
- `j2` = J+2 (utiliser en complément si horizon > 3 jours)
- Format JSON structuré, déjà éprouvé par l'agent `course-strategist`.

Alternative gratuite et sans clé : Open-Meteo (`https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...&daily=...`) si wttr.in est down — fallback optionnel.

## Résolution du lieu — ordre STRICT (ne jamais deviner)

```
1. planning/Semaine_*.md → champ "Lieu d'entraînement :" du fichier semaine actif
2. planning/active_objective.md → "Lieu d'entraînement par défaut"
3. planning/Runner_Profile.md → "Lieu par défaut"
4. Si aucun des trois → question() à l'utilisateur (ne JAMAIS inventer)
```

Format du lieu accepté par wttr.in : `Ville` ou `Ville, Pays` (ex: `Lille`, `Palma, Mallorca`, `Wimereux`).

Cas spéciaux :
- **Voyage / vacances** détecté dans le plan → vérifier que le fichier semaine a un override `Lieu` ; sinon demander.
- **Lieu imprécis** (ex: "Côte d'Opale") → utiliser la ville la plus proche du domicile / lieu de départ habituel des footings.

## Champs à extraire (par jour)

| Champ | Usage |
|---|---|
| `temp_C` (min/max) | Catégorie météo |
| `FeelsLikeC` | Ressenti pour l'athlète |
| `humidity` | Impact récupération |
| `windspeedKmph` | Vent moyen — décision créneau |
| `winddirDegree` | Adapter parcours (face/dos au vent) |
| `precipMM` + `chanceofrain` | Pluie — report ou créneau |
| `chanceofwindy` | Confirme vent fort |
| `uvIndex` | Crème / casquette si > 6 |
| `astronomy[0].sunrise / sunset` | Fenêtre créneaux matin/soir |

Garder les autres champs en mémoire seulement si utile (visibilité, pression).

## Catégories & seuils

| Catégorie | Critère (n'importe lequel) |
|:---|:---|
| 🟢 **Optimal** | T 12-22 °C · vent < 20 km/h · pluie < 1 mm · UV < 6 |
| 🟡 **Acceptable vigilance** | T 22-28 °C **OU** vent 20-35 km/h **OU** pluie 1-5 mm **OU** UV 6-8 |
| 🟠 **Difficile** | T 28-32 °C **OU** vent 35-50 km/h **OU** pluie 5-15 mm **OU** UV 8-10 |
| 🔴 **Dangereux** | T > 32 °C **OU** vent > 50 km/h **OU** pluie > 15 mm **OU** orage |

## Règle créneau optimal (par séance outdoor)

| Condition | Créneau | Rationale |
|---|---|---|
| Chaleur 🟠/🔴 | 🌅 **Matin tôt** (avant 8h, idéalement 5h-7h) | Température basse, UV nul |
| Vent > 30 km/h | 🌅 Matin OU 🌇 Soir | Vent souvent plus faible aux extrêmes |
| Pluie > 5 mm | 🌇 Soir OU reporter | Front orageux souvent passé en fin de journée |
| UV > 8 | 🌅 Matin tôt OU 🌇 Soir | Éviter 11h-16h |
| Cas standard | ☀️ **Midi / pause déjeuner** | Défaut user (AT/FR lunch break) |
| Indoor / récup | Aucun créneau | N/A |

## Règles d'ajustement auto

- 🟠 Difficile → suggérer **réduction 10-20 % durée/intensité** + hydratation × 1.2.
- 🔴 Dangereux → **reporter** la séance outdoor OU **basculer indoor** (home trainer, tapis, force à la salle).
- Pluie modérée (🟡) → OK si matériel imperméable ; vent fort → allure GPS compromise, courir **au cardio** (pas au GPS).
- Chaleur 🟠 + séance longue (> 90 min) → emporter ≥ 1L/h + électrolytes + casquette.

## Persistance — `medical/YYYY-MM-DD_meteo.md`

**Une fois par jour, par lieu.** Format dans la langue des documents (`config/workspace.toml` → `[language].documents`, défaut FRENCH) :

```markdown
# Météo — {lieu} — {YYYY-MM-DD}

## Données brutes
- **Température :** min {T_min}°C / max {T_max}°C (ressenti {feels}°C)
- **Vent :** {vent} km/h (rafales {rafales} km/h) — direction {dir}
- **Pluie :** {pluie} mm ({chance}%)
- **UV :** {uv}
- **Lever / coucher soleil :** {sunrise} / {sunset}
- **Humidité :** {h}%

## Catégorie
{category_emoji} **{catégorie}**

## Créneau recommandé pour séance outdoor
{créneau_emoji} **{créneau}** — {rationale}

## Ajustements
- {liste des ajustements si seuils dépassés}

## Source
- wttr.in/{ville}?format=j1 — fetched {timestamp}
```

**Ne PAS refetcher** un jour qui a déjà son fichier < 24 h (règle d'idempotence).

## Workflow coach (référence)

1. **Trigger** : demande "valide la semaine" OU "valide aujourd'hui/demain".
2. **Résoudre le lieu** via les 4 niveaux (cf. ci-dessus).
3. **Fetch prévisions** : 7 jours (hebdo) ou 24-48 h (journalier).
4. **Persister** un MD par jour dans `medical/`.
5. **Pour chaque séance outdoor** :
   - Catégorie météo
   - Créneau optimal 🌅/☀️/🌇 avec rationale
   - Ajustements si 🟠/🔴
6. **Intégrer au rapport** : tableau "Météo + créneau recommandé par jour".
7. **Cross-check récupération** : si météo 🟠/🔴 **ET** HRV bas / FC repos haut → biaiser vers repos.

## Reliability notes

- `wttr.in` rate-limite à ~1000 req/jour/IP — plus que suffisant pour ce use case (1-2 fetches/semaine max).
- Si 429/timeout → retry 1× après 5 s ; si toujours KO → fallback Open-Meteo.
- Toujours garder une trace (timestamp + lieu) dans le MD persisté.
