# Backfill (`arc-backfill`)

Met au [contrat de données](workspace-data-contract.md) les fichiers écrits
avant lui.

## Lancer

```bash
/arc-backfill
```

Le skill demande d'abord la liste des fichiers incomplets :

```bash
python3 scripts/arc_index.py backfill-plan
```

puis en traite **au plus dix** par passe, les plus récents d'abord — ce sont eux
qui comptent dans la courbe de forme.

## Ce qu'il fait, et ce qu'il ne fait pas

- Il ajoute le bloc de données sous le titre de chaque fichier, à partir de ce
  que le fichier dit déjà. **Tout le texte existant est conservé.**
- Il n'invente aucune valeur : ce qui n'est pas écrit reste absent.
- Il ne rappelle Garmin que si vous le demandez, une date à la fois.
- Il s'arrête après chaque lot et vous dit combien il en reste.

!!! tip "Versionnez avant"
    Si votre workspace est un dépôt git ([workspace privé](../workspace.md)),
    committez avant un lot : vous pourrez relire chaque modification.

La liste tient compte de votre configuration : avec
`[health].morning_check = "off"`, un fichier santé sans HRV n'est pas une dette.
