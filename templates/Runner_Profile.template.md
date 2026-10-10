# Profil de l'athlète

> Modèle installé par `/coach-setup`. Ce fichier vit dans votre workspace et
> n'est **jamais** versionné dans le dépôt public. Complétez ce que vous voulez :
> chaque champ laissé vide sera simplement ignoré par les agents.
>
> Les agents lisent ce fichier avant toute planification. L'objectif en cours,
> lui, reste dans `planning/active_objective.md`.

## Identité & contexte

- **Prénom / surnom** :
- **Année de naissance** :
- **Années de pratique** :
- **Disponibilité hebdomadaire** : <!-- ex. 4 séances, 6 h au total -->
- **Jours impossibles** : <!-- ex. mardi, dimanche matin -->
- **Contraintes de vie** : <!-- travail, famille, déplacements réguliers -->

## Physiologie

- **FC max** :
- **FC de repos de référence** : <!-- votre ligne de base, pas la valeur du jour -->
- **FC au seuil** : <!-- FC tenue ~1 h à fond (seuil lactique), ex. 172 -->
- **VO2max (Garmin)** : <!-- dernier relevé de la montre, en ml/kg/min ; informatif seulement, le tableau de bord calcule sa propre estimation à partir de vos séances -->
- **Sexe** : <!-- facultatif : F ou H, sert uniquement au calcul de charge (TRIMP) -->
- **Zones / seuils** :
- **Allures de référence** : <!-- 5 km, 10 km, semi, marathon -->
- **Poids de forme** :
- **Besoin de sommeil** : <!-- ex. 7h30 ; 7 h 30 par défaut si vide (dette de sommeil 7 j) -->

## Historique & blessures

- **Meilleures performances** :
- **Antécédents de blessure** :
- **Zones fragiles à surveiller** :
- **Arrêts récents** : <!-- maladie, coupure, reprise -->

## Indices de performance (ITRA / UTMB)

> Facultatif. Ces indices ne sont **jamais** récupérés automatiquement par un
> agent ou un script : seul vous pouvez les écrire ici, ou demander
> explicitement à l'agent `coach` de les chercher sur le web pour vous — il
> vous montrera alors la valeur trouvée et sa source, et vous demandera
> confirmation avant de l'écrire. Nomenclature UTMB (`20k`/`50k`/`100k`/`100m`)
> vérifiée ; celle de l'ITRA par catégorie n'a pas pu être vérifiée à
> l'écriture de ce modèle — la catégorie reste donc du texte libre.
>
> Une seule source de vérité : l'**historique** ci-dessous. La valeur
> « actuelle » d'un indice est simplement sa ligne la plus récente — inutile de
> la dupliquer ailleurs dans ce fichier.

### Historique des indices

<!--
  Une puce de PREMIER NIVEAU par relevé daté, au format :
    - AAAA-MM-JJ — itra [catégorie] : <valeur>
    - AAAA-MM-JJ — utmb [20k|50k|100k|100m] : <valeur>

  La catégorie est facultative (indice général si omise). Pour l'UTMB, seules
  les quatre catégories ci-dessus sont reconnues ; toute autre valeur, comme
  une ligne qui ne respecte pas ce format, est ignorée (avec un avertissement
  au tableau de bord/CLI) plutôt que de fausser silencieusement le calcul.

  Exemples (à adapter, effacer les lignes que vous ne remplissez pas) :
  - 2025-11-01 — itra : 610
  - 2025-11-01 — itra L : 600
  - 2026-02-15 — utmb 100k : 560
-->


## Matériel & lieux

- **Lieu par défaut** : <!-- ville utilisée pour la météo, ex. « Tournai » -->
- **Créneau habituel** : <!-- ex. pause de midi (12 h-14 h), tôt le matin, soir -->
- **Terrain accessible** : <!-- forêt, piste, dénivelé, salle -->
- **Équipement** : <!-- salle de sport, home trainer, haltères, tapis -->
- **Sports croisés pratiqués** : <!-- vélo, natation, renforcement -->

### Vélo & home trainer

<!--
  Facultatif — seulement si vous roulez sur home trainer. Sert à choisir un parcours
  virtuel à la durée d'une séance (skill mywhoosh-route, `[home_trainer]` dans la config)
  et à la carte « Home trainer » du tableau de bord. La puissance que vous tenez en
  zone 2 n'est PAS à écrire ici : elle est calculée sur vos séances (`arc_index.py power-hr`).
-->

- **Home trainer** : <!-- modèle, ex. « Wahoo KICKR » -->
- **Vélo sur home trainer** : <!-- ex. « Van Rysel EDR » -->
- **Masse du vélo** : <!-- en kg, ex. « 8,5 kg » ; vide = 8 kg par défaut -->
- **FTP déclarée** : <!-- en W, issue d'un vrai test (20 min, rampe), ex. « 230 W (test 2026-10-01) » -->

### Chaussures

<!--
  Une puce de PREMIER NIVEAU par paire (pas de puce indentée dessous, elle
  serait ignorée comme chaussure et repliée dans la ligne du dessus), tout est
  facultatif sauf le nom. Segments séparés par un tiret cadratin " — " (le plus
  lisible), ou par un simple tiret ENTOURÉ D'ESPACES " - " (jamais un tiret
  sans espaces, qui peut faire partie du nom, ex. « Ultra-Trail ») :
    - <nom> — depuis <AAAA-MM-JJ> — alerte <N> km — départ <N> km — usage: <rôle> — id: <identifiant> — garmin: <uuid> (par défaut)

  - "depuis" : date d'achat — AAAA-MM-JJ, ou juste "mars 2026"/"03/2026" (1er du
    mois). Depuis #40, filtre l'attribution automatique des séances SANS
    matériel précisé à la chaussure "(par défaut)" (une séance datée avant
    n'y est pas rattachée) — sans effet sur une séance qui cite cet id.
  - "alerte" : seuil d'usure propre à cette paire, en km (ou "N miles"/"N mi",
    converti), sinon 700 km par défaut.
  - "départ" : kilomètres déjà parcourus AVANT le suivi (paire d'occasion, usage
    antérieur à l'installation) — "départ 300 km" ou "départ 100 mi". Ajouté au
    cumul, donc à l'alerte et à la prévision de retraite. Vous pouvez aussi le
    corriger en discutant avec le coach ("mes Pegasus ont en fait ~300 km").
  - "usage:" (facultatif) : rôle de la paire — course, trail, route, récup — pour
    que le coach suggère quelle paire porter quand vous en avez deux ou plus.
  - "id:" : identifiant explicite (sinon dérivé automatiquement du nom).
    OBLIGATOIRE si vous rachetez le même modèle (deux puces au même nom sans
    id explicite se voient sinon attribuer un identifiant renommé -2, -3… et
    un avertissement au tableau de bord).
  - "garmin:" (facultatif) : identifiant (uuid) du matériel dans Garmin Connect, tel que
    listé par le coach (`get_gear`) — il permet de rattacher automatiquement le matériel
    que la montre attache à une séance. Le coach vous propose l'association une fois ;
    il ne la devine jamais.
  - "(par défaut)" : chaussure attribuée aux séances sans matériel précisé.
  - "(retirée)" : sortie de rotation — kilométrage conservé, jamais d'alerte.
  - "(ignorée)" : matériel Garmin que vous ne suivez pas — puce réduite à `garmin: <uuid>` ; le coach
    ne le repropose plus et ne le signale plus, et ses séances ne sont jamais créditées à la
    paire par défaut.

  Exemple (à adapter, effacer les lignes que vous ne remplissez pas) :
  - Hoka Speedgoat 5 (bleues) — depuis 2026-03-01 — alerte 700 km — id: speedgoat-bleues (par défaut)
  - Hoka Speedgoat 5 (grises) — depuis 2026-09-01 — id: speedgoat-grises
  - Salomon S/Lab Ultra — usage: course — départ 20 km — id: slab-ultra
  - Nike Pegasus — départ 300 km (retirée)
-->

### Matériel

<!--
  Tout le reste du matériel (bâtons, gilet, poche à eau, flasques, frontale, ceinture
  cardio, veste, semelles, lacets…). Même principe que « Chaussures » : une puce de
  PREMIER NIVEAU par objet, segments séparés par " — ", tout facultatif sauf le nom.
  Les chaussures restent dans « ### Chaussures » (rien à changer là-bas) :
    - <nom> — catégorie: <bâtons|gilet|poche|flasques|frontale|ceinture|veste|semelles|lacets|autre> — depuis <AAAA-MM-JJ> — alerte <déclencheurs> — entretien <AAAA-MM-JJ> — kit: <nom-du-kit> — id: <identifiant>

  - "catégorie:" : seule façon de classer un objet (jamais devinée du nom). Elle décide
    des sports qui comptent : bâtons = trail/randonnée/marche ; gilet, poche, flasques, veste,
    semelles, lacets = course/trail/randonnée ; frontale, ceinture = tout sport. Autre
    valeur : l'objet est suivi, sans alerte inventée.
  - "alerte" : déclencheurs typés, combinables, le premier atteint déclenche —
    "alerte 800 km", "alerte 100 h", "alerte 40 séances", "alerte 30 jours",
    "alerte 30 jours ou 40 h", "alerte 1h30", "alerte 6 mois", "alerte 2 ans".
    Aucun seuil par défaut : sans "alerte", jamais d'alerte.
    Une unité est obligatoire (un nombre seul est ignoré).
  - "depuis" : date d'achat ; les jours se comptent depuis cette date.
  - "entretien" : dernier entretien (nettoyage, réimperméabilisation, changement de
    pile…) — remet à zéro les compteurs ; mettez la date de la dernière séance faite
    AVANT l'entretien (celles d'après comptent). Dites simplement au coach « j'ai nettoyé
    la poche » : il met ce segment à jour.
  - "départ" : usage avant le suivi — "départ 12 h", "départ 300 km", "départ 8 séances".
  - "kit:" : regroupe les objets portés ensemble ("kit: trail-long"). Dire « kit trail
    long » au coach pour une séance les attribue tous d'un coup.
  - "id:" et "(retirée)" : comme pour les chaussures.

  Exemple (à adapter, effacer les lignes que vous ne remplissez pas) :
  - Poche à eau 2 L — catégorie: poche — depuis 2026-03-01 — alerte 30 jours — kit: trail-long
  - Frontale Petzl — catégorie: frontale — alerte 100 h — id: frontale-nuit — kit: trail-long
  - Bâtons Leki — catégorie: bâtons — alerte 800 km — kit: trail-long
  - Ceinture cardio — catégorie: ceinture — depuis 2026-01-10 — alerte 365 jours
-->


## Préférences de coaching

> Ce que la configuration (`config/workspace.user.toml` → `[coaching]`) ne peut
> pas exprimer. Écrivez librement.

- **Ce qui me motive** :
- **Ce qui ne marche pas avec moi** :
- **Sujets à ne pas commenter spontanément** : <!-- ex. le poids -->
- **Tolérance au risque** : <!-- prudent | équilibré | agressif, et pourquoi -->
- **Quand me poser une question plutôt que supposer** :

## Objectif actif

Voir `planning/active_objective.md` — source de vérité de l'objectif en cours.
