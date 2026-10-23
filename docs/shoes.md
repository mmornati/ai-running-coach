# Choisir ses chaussures

Épopée #297. Le suivi des chaussures (kilométrage, inspection photo, bilan de carrière) dit **ce que
vous avez porté** ; choisir la prochaine paire demande de savoir **ce qu'elle est**. Cette page décrit la
première brique : la fiche de caractéristiques d'une paire (#298). Les retours de chaussant, le profil
d'usage et le moteur de règles viennent ensuite.

## La fiche de caractéristiques : `gear/specs/<gear_id>.md`

Un fichier par paire, lié au profil par le `gear_id` (le profil `### Chaussures` reste inchangé et édité
par vous). Il s'ouvre par un bloc `arc` de type `shoe_spec`, comme les autres fichiers du workspace ;
le texte libre dessous garde la version retenue et le journal des validations.

| Champ | Contenu |
|---|---|
| `brand`, `model`, `version`, `release_year` | identité exacte de la paire |
| `size`, `purchase_date` | pointure (valeur + système) et date d'achat |
| `category` | `road`, `trail` ou `hybrid` |
| `drop_mm`, `stack_heel_mm`, `stack_forefoot_mm` | géométrie en millimètres |
| `weight_g` | poids en grammes (+ `reference_size`, la pointure du poids annoncé) |
| `midsole_foam`, `midsole_softness` | mousse (EVA, PEBA, TPU…) et dureté (valeur + échelle, ex. Asker C) |
| `plate` | `none`, `carbon`, `nylon`, `rock_plate` |
| `lug_depth_mm`, `toe_box` | crampons et largeur d'avant-pied (`narrow`, `standard`, `wide`) |
| `flexibility_longitudinal`, `flexibility_torsional`, `stability_devices` | évaluations manuelles pour l'index minimaliste |

Une caractéristique introuvable est **absente** du fichier : jamais estimée, jamais reprise d'un modèle
voisin (une valeur d'un modèle voisin peut être montrée en séance comme indice, jamais enregistrée).

### La provenance de chaque valeur

Chaque champ est un objet, pas un nombre nu :

```json
"drop_mm": {
  "value": 8.7, "source_type": "measured",
  "url": "https://www.rtings.com/running-shoes/reviews/kiprun/kipride-max", "retrieved": "2026-10-12",
  "alternatives": [{"value": 6, "source_type": "manufacturer", "url": "…", "retrieved": "2026-10-12"}]
}
```

- `source_type` : `measured` (laboratoire), `manufacturer` (marque ou revendeur qui la recopie) ou `athlete` (vous).
- `value` est la valeur **retenue** : **une mesure prime sur la marque** ; votre propre correction, validée
  ligne par ligne, prime sur les deux. Les autres sources vont dans `alternatives`.
- `url` et `retrieved` (date de consultation) sont obligatoires pour `measured` et `manufacturer`.
- Valeurs plausibles, sinon la fiche est refusée : drop de -5 à 20 mm, piles de 0 à 60 mm, poids de 100 à
  600 g, crampons de 0 à 12 mm. Une source **alternative** qui s'éloigne trop de la valeur retenue (poids
  de plus de 25 %, cotes de plus de 4 à 6 mm) déclenche un avertissement d'**aberration probable** (par
  exemple un poids de 580 g face à des 240-285 g) ; confirmée, elle est conservée pour mémoire avec
  `outlier: true` et n'est jamais retenue. L'écart marque/laboratoire sur le drop, lui, n'est pas une
  aberration : c'est une information, et il reste visible.

### La saisie assistée

Voir le skill [`shoe-specs`](skills/shoe-specs.md) : questions, identification de la version
(date de lancement face à date d'achat, sinon on demande), recherche web **à la demande** (laboratoire,
puis marque, puis un ou deux revendeurs ; pas de scraping), tableau de validation, et écriture
seulement après votre validation ligne par ligne. Jamais en headless.

### Lire les fiches

```bash
python3 scripts/arc_index.py shoe-specs                       # JSON : toutes les fiches + paires sans fiche
python3 scripts/arc_index.py shoe-specs --gear kipride-max-1 --text
```

Lecture seule. Par champ : la valeur retenue et sa source, les alternatives, l'écart entre sources
(`spread`, dont `measured_minus_manufacturer`, l'écart laboratoire - marque) et, pour une valeur que vous avez
choisie, `basis` (la source sur laquelle vous vous êtes fondé) ; par fiche : les champs absents, `in_profile`
(`false` si la paire n'est pas dans `### Chaussures`) et l'index minimaliste. **Une seule fiche par paire** :
le fichier s'appelle exactement `<gear_id>.md`, sinon il n'est pas indexé.

Si vous préférez la valeur de la marque à la mesure d'un laboratoire, la fiche la garde sans contredire la
règle « la mesure prime » : valeur retenue en `athlete` avec `basis: manufacturer` et l'URL de la marque, la
mesure et la valeur de la marque restant en `alternatives`.

## L'index minimaliste (Esculier et al. 2015)

Source : Esculier et al. 2015, *J Foot Ankle Res* 8:42
([article](https://jfootankleres.biomedcentral.com/articles/10.1186/s13047-015-0094-5), PMC4543477 ; la
grille de notation est le fichier additionnel 1 de l'article). Cinq sous-échelles de 0 à 5 (5 = plus
minimaliste) ; l'index est la somme multipliée par 4, soit un pourcentage sur 25 points.

| Sous-échelle | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|
| Poids | < 125 g | 125 à < 175 g | 175 à < 225 g | 225 à < 275 g | 275 à < 325 g | ≥ 325 g |
| Hauteur de talon (pile) | < 8 mm | 8 à < 14 mm | 14 à < 20 mm | 20 à < 26 mm | 26 à < 32 mm | ≥ 32 mm |
| Drop | < 1 mm | 1 à < 4 mm | 4 à < 7 mm | 7 à < 10 mm | 10 à < 13 mm | ≥ 13 mm |
| Dispositifs de stabilité / contrôle du mouvement | aucun | 1 | 2 | 3 | 4 | 5 ou 6 |
| Flexibilité | somme de deux notes : longitudinale (0 à 2,5) + torsionnelle (0 à 2,5), par pas de 0,5 | | | | | |

Dispositifs comptés : semelle intermédiaire multi-densité, ponton médial thermoplastique, contrefort de
talon rigide, voûte médiale surélevée, tige médiale tendue, évasement médial.

Ce qui vient de la fiche : poids, pile du talon et drop (le drop vient de `drop_mm`, sinon de la pile du
talon moins la pile de l'avant-pied). La flexibilité et les dispositifs de stabilité **n'existent chez
aucune source en ligne** : ce sont des évaluations manuelles de votre part, saisies en
`flexibility_longitudinal`, `flexibility_torsional` et `stability_devices` avec la source `athlete`.
Si une entrée manque, l'index est **indisponible et la commande en donne la raison** — jamais une valeur
partielle. L'index n'est pas enregistré dans la fiche : il est recalculé à chaque lecture.

Limites, dites plutôt que cachées : l'article mesure le poids de la chaussure et la pile au pied à
coulisse sous le talon et les têtes métatarsiennes ; une valeur de marque ou de laboratoire en est une
**approximation du projet** (pointure de référence, point de mesure). Le poids dépend de la pointure : les
comparatifs l'annoncent en général en US M9 (convention, le fichier additionnel de l'article ne la précise
pas) ; la commande ajoute un avertissement `warnings` quand `reference_size` manque ou diffère, et rend
toujours les `assumptions` de la méthode. L'index sert à situer un
**changement** entre deux paires, pas à juger une chaussure, et ce n'est pas un avis médical.

## Ce que disent les preuves

*À compléter par la story #301 (moteur de règles fondé sur les preuves : confort, continuité, drop,
amorti, rotation, plaque et super-mousses, avec le niveau de preuve de chaque règle).*
