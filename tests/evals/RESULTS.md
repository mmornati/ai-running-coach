# Résultats du palier C

Dernier relevé des évals d'exécution. **Versionné volontairement** : une
régression de comportement se lit alors dans un diff de PR, pas dans la couleur
d'un job qui a déjà défilé.

Régénérer :

```bash
ARC_LLM_TESTS=1 python3 tests/run_tests.py --tier c --repeat 3
```

## Dernier relevé

| | |
|---|---|
| **Date** | 2026-09-25 01:47 UTC |
| **Modèle** | `claude-haiku-4-5-20251001` |
| **Runner** | `claude -p` |
| **Répétitions** | 3 par scénario |
| **Seuil de réussite** | 2/3 |

| Scénario | Réussites | Verdict |
|---|---|---|
| `daily-sync-resume-block` | — | — |
| `doctor-token-expiring` | — | — |
| `health-full-triad` | — | — |
| `health-minimal-readiness-only` | — | — |
| `health-off-no-health-file` | — | — |
| `health-off-no-hrv` | — | — |
| `health-own-baseline` | — | — |
| `health-token-expired` | — | — |
| `no-medical-no-delegation` | — | — |
| `setup-first-run` | — | — |
| `setup-idempotent` | — | — |
| `sleep-debt` | — | — |
| `sport-road-no-elevation` | — | — |
| `sport-trail-elevation` | — | — |
| `style-exigeant-names-the-miss` | — | — |
| `style-factuel-quiet` | — | — |
| `sync-activity-arc-fields` | — | — |
| `sync-writes-arc-block` | — | — |

> **Pas encore de relevé.** Le harnais est complet et validé — scénarios,
> fixtures, serveur MCP factice, journal des appels d'outils — mais aucune
> exécution réelle n'a encore eu lieu : cela demande un runner authentifié.
> Lancez la commande ci-dessus, ou le workflow `Évals` depuis l'onglet Actions,
> puis remplacez ce tableau par le relevé obtenu.

