# Skill : `shoe-specs` — fiche de caractéristiques d'une paire

> **Description** : Drop, pile, poids, mousse, plaque et crampons d'une paire de chaussures, cherchés en ligne source par source et écrits dans `gear/specs/<gear_id>.md` **seulement après votre validation ligne par ligne** — jamais en headless, jamais une valeur inventée.

## Quand l'utiliser

- Vous ajoutez une paire à `### Chaussures` et vous voulez sa fiche (le coach peut vous la proposer, une fois par conversation)
- Vous demandez le drop, la pile, le poids ou la mousse d'une paire
- `python3 scripts/arc_index.py shoe-specs` liste des paires **sans fiche** et vous voulez les compléter

## Le déroulé

1. **Questions** : marque, modèle exact, version ou année, pointure, date d'achat, et facultativement une photo de l'étiquette de languette.
2. **Version** : la date de lancement comparée à la date d'achat tranche souvent (une Kipride Max achetée en mars 2026 est une v1, la v1 étant sortie en janvier 2026). Si plusieurs versions existaient, le coach **demande** — jamais de devinette.
3. **Recherche** à la demande : laboratoire d'abord (RunRepeat, RTINGS), puis la page de la marque, puis un ou deux revendeurs. Jamais de scraping automatisé.
4. **Tableau de validation** : une ligne par caractéristique, avec la valeur proposée, l'URL, le type de source (`measured` laboratoire, `manufacturer` marque, `athlete` vous) et l'écart entre sources. Les aberrations sont signalées.
5. **Votre validation** ligne par ligne. Rien n'est écrit avant. Une valeur introuvable reste absente ; la valeur d'un modèle voisin peut être montrée comme indice, jamais enregistrée.

Rien n'est proposé pendant la synchronisation automatique (`garmin-daily-sync`) : c'est une conversation.

## Pourquoi chaque valeur a sa source

La marque n'est pas le laboratoire. Pour le drop, une Kipride Max annoncée à 6 mm mesure 8,7 mm chez RTINGS ; une Ultra Glide 4 annoncée à 6 mm mesure 7,5 mm chez RunRepeat. La valeur retenue est la **mesure** quand elle existe, et l'écart reste visible dans la fiche.

```bash
python3 scripts/arc_index.py shoe-specs [--gear ID] [--text]   # lecture seule
```

Le détail du fichier, de la provenance et de l'index minimaliste est dans [Choisir ses chaussures](../shoes.md).

## Fichier source

`skills/shoe-specs/SKILL.md`
