---
name: shoe-specs
description: Saisie assistée de la fiche de caractéristiques d'une paire de chaussures (gear/specs/<gear_id>.md, bloc arc shoe_spec) — questions (marque, modèle exact, version/année, pointure, date d'achat, photo d'étiquette facultative), identification de la version par la date de lancement face à la date d'achat (ambigu = on demande), recherche web à la demande (laboratoire RunRepeat/RTINGS d'abord, puis marque, puis 1 à 2 revendeurs), tableau de validation valeur/source/type/écart avec aberrations signalées, validation ligne par ligne par l'athlète, jamais d'écriture sans cette validation, jamais en headless, une valeur introuvable reste absente. Charger quand une paire est ajoutée au profil et que l'athlète veut sa fiche, quand il demande drop/stack/poids/amorti d'une paire, ou pour compléter les paires sans fiche (python3 scripts/arc_index.py shoe-specs).
---

# Fiche de caractéristiques d'une paire (#298)

Choisir une paire (épopée #297) exige de connaître celles que l'athlète a déjà portées : drop, hauteur
de pile, poids, mousse, plaque, crampons. Ces chiffres ne sont **nulle part** dans le workspace — le
profil (`### Chaussures`) ne porte que nom, dates, seuil et usage. Ce skill les cherche en ligne **avec
l'athlète**, montre d'où vient chaque chiffre, et n'écrit que ce qu'il a validé.

**La marque n'est pas le laboratoire.** Une Kipride Max annoncée à 6 mm de drop en mesure 8,7 mm
(RTINGS) ; une Ultra Glide 4 annoncée à 6 mm en mesure 7,5 mm (RunRepeat). La règle de continuité du
drop (#301) dépend de ce chiffre : chaque valeur porte donc sa source et son type (`measured` |
`manufacturer` | `athlete`), et la mesure prime sur la marque.

## Garde-fous (à tenir sans exception)

- **Aucune écriture sans validation.** Rien n'est écrit dans `gear/specs/` avant que l'athlète ait
  validé ou corrigé le tableau ligne par ligne ; un « ok » global sur un tableau non lu n'est pas une
  validation : relire les lignes ambiguës ou aberrantes une par une.
- **Jamais en headless.** `/garmin-daily-sync` et tout run sans athlète ne lancent ni recherche, ni
  question, ni écriture de fiche. Interactif uniquement.
- **Aucune valeur inventée.** Chaque chiffre a une URL consultée et une date (`retrieved`) ; sans
  source, la valeur est **absente** (clé omise), jamais estimée, jamais arrondie « au plausible ».
- **Jamais reprise d'un modèle voisin.** Une valeur d'un autre modèle ou d'une autre version (ex. la
  mesure de la version suivante) peut être montrée comme **indice** — étiquetée « indice, autre modèle,
  non retenu » — mais n'est **jamais persistée**.
- **Pas de scraping automatisé ni de copie éditoriale.** Recherche web **à la demande**, pour cette
  paire, une page à la fois ; on relève des valeurs factuelles et l'URL, jamais le texte d'un test. Les
  conditions d'utilisation de RunRepeat n'ont pas été vérifiées : pas d'aspiration, pas de boucle sur un
  catalogue.
- Ce n'est ni un avis médical ni une recommandation d'achat : aucun lien d'affiliation, aucun prix.

## 1. Quand

- Une paire vient d'être ajoutée à `### Chaussures` et l'athlète veut sa fiche, ou le coach la lui
  **propose** (une fois par conversation, jamais imposée).
- Premier passage : `python3 scripts/arc_index.py shoe-specs` liste `gear_without_spec` — les paires du
  profil sans fiche ; en proposer **une** à la fois, par ordre de pertinence (la plus portée d'abord).
- À la demande (« quel est le drop de mes Speedgoat ? »), ou pour corriger une valeur d'une fiche existante.

## 2. Questions (dans cet ordre, en une fois)

1. **Marque** et **modèle exact** (« Salomon Ultra Glide », « Kiprun Kipride Max »).
2. **Version ou année** (UG 3, v1, 2025…) — si l'athlète ne sait pas : date d'achat, puis étiquette.
3. **Pointure** et son système (EU, US_M, US_W, UK, JP ou CM) — jamais convertie d'un système à l'autre.
4. **Date d'achat** (approximative suffit).
5. Facultatif : une **photo de l'étiquette de languette** (version, année, pointure, poids de
   référence), à lire comme n'importe quelle image fournie par l'athlète.
6. Le `gear_id` : celui de la puce du profil (jamais un nouveau slug si la paire y figure déjà).

## 3. Identifier la version

Le nom commercial ne suffit pas : « Ultra Glide » peut être la 1, la 2, la 3, la 4 ou une S/Lab, aux
caractéristiques différentes.

- Comparer la **date de lancement** de chaque version candidate (page marque ou labo) à la **date
  d'achat** : si une seule version existait à cette date, c'est elle — par exemple une Kipride Max
  achetée en mars 2026 alors que la v1 est sortie en janvier 2026 est une **v1**, sans poser de question.
- Si plusieurs versions étaient en vente à la date d'achat, ou si la date est inconnue : **demander**
  (version, étiquette, photo). **Jamais de devinette.**
- Écrire la version retenue et la raison dans le texte libre de la fiche (« v1 : seule version sortie à
  la date d'achat »).

## 4. Chercher

Ordre fixe, en s'arrêtant quand les champs utiles sont couverts :

1. **Laboratoire** : RunRepeat, RTINGS — valeurs `measured` (drop, pile talon/avant, poids, dureté de
   mousse, largeur d'avant-pied…). Aucune source ne couvre tout : RunRepeat n'a pas toutes les
   paires, RTINGS non plus.
2. **Page de la marque** — valeurs `manufacturer`.
3. **1 à 2 revendeurs** (pas plus) — `manufacturer` aussi (ils recopient la marque), utiles pour
   départager.

Pour chaque valeur : relever le chiffre, l'**URL exacte**, la date du jour (`retrieved`), la
pointure de référence du poids (`reference_size`) quand la page la donne. Champs visés : `category`,
`drop_mm`, `stack_heel_mm`, `stack_forefoot_mm`, `weight_g`, `midsole_foam`, `midsole_softness`
(avec son échelle), `plate`, `lug_depth_mm`, `toe_box`. Un champ qu'aucune page ne donne reste **absent**.

## 5. Proposer le tableau de validation

Un tableau, une ligne par caractéristique, avant toute écriture :

| Caractéristique | Valeur proposée | Source (URL) | Type | Écart entre sources |
|---|---|---|---|---|
| Drop | 8,7 mm | rtings.com/… | measured | marque : 6 mm (écart labo - marque : +2,7 mm) |
| Pile talon / avant | 42 / 36 mm | runnerslab.com/… | manufacturer | autre revendeur : 44 / 38 mm |
| Poids | … | … | … | … |

Règles du tableau :

- **Valeur proposée** = la valeur retenue selon la priorité `athlete` > `measured` > `manufacturer`
  (`arc_shoes.select_value`) ; **la mesure prime sur la marque**, et l'**écart marque/labo** est affiché
  en toutes lettres (surtout sur le drop : c'est lui que la règle de continuité lit).
- **Écart entre sources** : toutes les autres valeurs trouvées, avec leur URL — elles iront dans
  `alternatives`.
- **Aberrations signalées**, pas retenues : une valeur très éloignée des autres (un poids de 580 g face à
  des 240-285 g) est marquée « aberration probable » ; si l'athlète la confirme, elle est conservée pour
  mémoire avec `outlier: true`, jamais retenue.
- Valeur introuvable : la ligne dit « introuvable — restera absente ». Un **indice d'un modèle voisin**
  éventuel apparaît dans une ligne distincte « indice (autre modèle, non retenu) », hors du tableau
  à valider.

## 6. Validation ligne par ligne, puis écriture

1. L'athlète **valide, corrige ou supprime chaque ligne**. Une correction par l'athlète devient
   `source_type: "athlete"` (il a le dernier mot) ; l'ancienne valeur peut rester en `alternatives`.
2. **Seulement alors**, charger `workspace-data-contract` et écrire `gear/specs/<gear_id>.md` : bloc
   `arc` `kind: "shoe_spec"` (provenance de chaque valeur : `value`, `source_type`, `url`, `retrieved`,
   `alternatives`), puis le texte libre (version et raison, journal des validations : date, lignes
   corrigées par l'athlète). Un fichier existant est **réécrit en place**, jamais dupliqué.
3. Valider : `python3 scripts/arc_index.py --validate gear/specs/<gear_id>.md`. Une erreur (valeur hors
   bornes, `measured` écarté au profit de `manufacturer`, `url`/`retrieved` manquants) se corrige avec
   l'athlète ; un avertissement d'aberration se résout en marquant `outlier: true` ou en retirant la valeur.
4. Relire avec `python3 scripts/arc_index.py shoe-specs --gear <gear_id> --text` et montrer le résultat.

## 7. Index minimaliste (facultatif)

L'index minimaliste d'Esculier et al. 2015 (J Foot Ankle Res 8:42) note cinq sous-échelles de 0 à 5 :
poids, hauteur de talon, drop, flexibilité, dispositifs de stabilité. Les trois premières viennent de la
fiche. **Flexibilité et stabilité n'ont pas de valeur « fabricant »** : seul l'athlète peut les évaluer,
en tenant la chaussure :

- `flexibility_longitudinal` et `flexibility_torsional` : chacune de 0 (résistance extrême) à 2,5 (résistance
  minimale), par pas de 0,5 — l'échelle illustrée est le fichier additionnel 1 de l'article ;
- `stability_devices` : nombre (0 à 6) de dispositifs observés — semelle intermédiaire multi-densité,
  ponton médial thermoplastique, contrefort de talon rigide, voûte médiale surélevée, tige médiale tendue,
  évasement médial.

Les demander **sans insister**, les enregistrer en `source_type: "athlete"`. Sans elles — ou si le poids,
le talon ou le drop manque — l'index est **indisponible, et la commande le dit** (jamais une valeur
partielle). C'est un repère pour mesurer un **changement** entre deux paires, pas un verdict.

## 8. Lire les fiches

```bash
python3 scripts/arc_index.py shoe-specs                 # toutes les fiches + paires sans fiche
python3 scripts/arc_index.py shoe-specs --gear ID --text
```

Lecture seule. Par fiche : chaque champ avec sa valeur retenue, son type, son URL, ses `alternatives` et
l'écart (`spread`, dont `measured_minus_manufacturer`), les champs `absent`, et `minimalist_index`
(`available`, `index_pct`, sous-notes, ou `reason`).
