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
| **Date** | _jamais exécuté_ |
| **Modèle** | `claude-haiku-4-5-20251001` (défaut) |
| **Runner** | `claude -p` |
| **Répétitions** | 3 par scénario |
| **Seuil de réussite** | 2/3 |

| Scénario | Réussites | Verdict |
|---|---|---|
| `health-off-no-hrv` | — | — |
| `health-full-triad` | — | — |
| `health-minimal-readiness-only` | — | — |
| `no-medical-no-delegation` | — | — |
| `sport-road-no-elevation` | — | — |
| `sport-trail-elevation` | — | — |
| `style-factuel-quiet` | — | — |
| `style-exigeant-names-the-miss` | — | — |
| `setup-first-run` | — | — |
| `setup-idempotent` | — | — |
| `daily-sync-resume-block` | — | — |
| `health-token-expired` | — | — |
| `sync-writes-arc-block` | — | — |
| `sync-activity-arc-fields` | — | — |

> **Pas encore de relevé.** Le harnais est complet et validé — scénarios,
> fixtures, serveur MCP factice, journal des appels d'outils — mais aucune
> exécution réelle n'a encore eu lieu : cela demande un runner authentifié.
> Lancez la commande ci-dessus, ou le workflow `Évals` depuis l'onglet Actions,
> puis remplacez ce tableau par le relevé obtenu.
