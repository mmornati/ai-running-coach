# Comparaison de parcours — Exemple anonymisé

> **Exemple fictif** — les valeurs ci-dessous sont génériques et ne correspondent
> à aucune séance réelle. Elles illustrent le format de rapport produit par
> `compare_course.py`.

**Séance de référence :** 2026-05-10 — Sortie longue 30 km
**Séances comparées :** 2026-03-15, 2026-04-20

_Alignement : boucle 10.0 km · tolérance 50 m · montée ≥ 40 m D+/km_

## 1. Comparaison globale

| Séance | Distance | Durée | Allure moy | D+ | D- | FC moy | FC max | HRR | TE |
|:--------|---------:|------:|:----------:|----:|----:|-------:|-------:|----:|---:|
| 2026-05-10 | 30.9 km | 3h37:57 | 7:03/km | 1017 | 1016 | 134 | 154 | 29 | 4.7 |
| 2026-04-20 | 20.3 km | 2h23:53 | 7:06/km | 695 | 683 | 146 | 165 | — | 5.0 |
| 2026-03-15 | 11.6 km | 1h23:26 | 7:11/km | 461 | 457 | 127 | 151 | 32 | 3.6 |

## 2. Alignement des tours (segments comparables)

| Tour | Séance | Km | Durée | Allure moy | D+ | FC moy |
|:-----|:-------|:--:|------:|:----------:|:--:|-------:|
| **T1** | **2026-05-10** | 1-10 | 1h05:39 | 6:34/km | 267 | 130 |
| | 2026-04-20 | 1-10 | 1h03:06 | 6:19/km | 286 | 142 |
| | 2026-03-15 | 1-10 | 1h08:48 | 6:53/km | 313 | 129 |
| **T2** | **2026-05-10** | 11-20 | 1h10:57 | 7:06/km | 374 | 134 |
| | 2026-04-20 | 11-20 | 1h18:09 | 7:49/km | 390 | 150 |
| | 2026-03-15 | 11-12 | 17:42 | 8:51/km | 147 | 120 |
| **T3** | **2026-05-10** | 21-30 | 1h13:07 | 7:19/km | 330 | 138 |
| | 2026-04-20 | 21-21 | 9:14 | 9:14/km | 22 | 150 |

## 3. Montées comparables (≥ 40 m D+/km)

| Séance | Montée (km) | D+ | Durée | Allure | FC moy |
|:-------|:-----------:|:--:|------:|:------:|-------:|
| 2026-05-10 | km 5 | 101 m | 8:21 | 8:21/km | 140 |
| 2026-05-10 | km 8 | 55 m | 7:33 | 7:33/km | 135 |
| 2026-04-20 | km 5 | 98 m | 8:02 | 8:02/km | 145 |
| 2026-03-15 | km 5 | 95 m | 8:40 | 8:40/km | 138 |

## 4. Verdict automatique

- **2026-05-10 vs 2026-04-20 :** allure plus lente de 0.7 % (7:03/km vs 7:06/km) — FC inférieure de 12 bpm (meilleure gestion).
- **2026-05-10 vs 2026-03-15 :** allure plus rapide de 1.9 % (7:03/km vs 7:11/km) — FC supérieure de 7 bpm.

> ⚠️ Verdict indicatif : à confirmer par l'analyse coach (contexte, fatigue,
> dénivelé réel, conditions météo, blessure).