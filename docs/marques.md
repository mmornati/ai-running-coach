# Marques et métriques

ai-running-coach est un projet **indépendant**, sous licence MIT. Il n'est ni
affilié à Garmin, TrainingPeaks, Intervals.icu ou Strava, ni approuvé, parrainé ou
soutenu par eux.

## Marques citées

| Marque | Titulaire | Pourquoi elle apparaît |
|---|---|---|
| Garmin®, Garmin Connect™ | Garmin Ltd. ou ses filiales | Source des données (activités, sommeil, HRV) et calendrier des séances |
| Body Battery™, Firstbeat Analytics™, *Training Readiness* | Garmin Ltd. ou ses filiales | Scores lus tels que Garmin les fournit, jamais recalculés |
| TrainingPeaks®, TSS®, NP®, IF® | Peaksware LLC (groupe Garmin depuis juillet 2026) | Non utilisés par le projet ; « Pa:HR »/« Efficiency Factor » cités uniquement pour situer notre découplage aérobie/EF (formule publique, voir l'équivalence ci-dessous) |
| CTL, ATL, TSB | revendiqués par Peaksware LLC | Cités seulement pour l'équivalence ci-dessous |
| Intervals.icu, Strava | leurs éditeurs respectifs | Services tiers, facultatifs |
| Strava GAP, COROS Effort Pace, Suunto NGP | leurs éditeurs respectifs (Strava, Inc. ; COROS ; Suunto Oy) | Cités uniquement pour situer notre allure ajustée à la pente parmi des calculs équivalents du marché (voir l'équivalence ci-dessous) — non utilisés par le projet, calculs propriétaires non reproduits |

Ces noms sont cités uniquement pour désigner les services avec lesquels le projet
interagit ou pour expliquer une équivalence, conformément à l'usage loyal des
marques d'autrui (art. 14 du règlement (UE) 2017/1001, art. L.713-6 du code de la
propriété intellectuelle).

## Des formules publiques, des noms génériques

Une marque protège un nom, pas un calcul. Les modèles du tableau de bord sont
publiés dans la littérature scientifique et portent ici des noms génériques :

| Dans ai-running-coach | Origine | Équivalent dans d'autres outils |
|---|---|---|
| **Charge** d'une séance | TRIMP de Banister (1991) ; session-RPE de Foster (2001) sans FC | « TSS » chez TrainingPeaks — autre calcul, autre échelle |
| **Condition** (moyenne exponentielle 42 j) | Modèle impulsion-réponse de Banister (1975) | CTL · *Fitness* |
| **Fatigue** (moyenne exponentielle 7 j) | idem | ATL · *Fatigue* |
| **Forme** (condition − fatigue, la veille) | idem | TSB · *Form* |
| **ACWR** (fatigue / condition) | Hulin, Gabbett *et al.* (2014) | idem |
| **Zones FC** (5 zones) | Karvonen, Kentala & Mustala (1957) (réserve FC) ; Friel, *The Triathlete's Training Bible* (% de la FC au seuil/LTHR) ; %FC max (convention courante) | « Zones » telles qu'affichées par d'autres montres/applications — méthode et bornes différentes, non comparables terme à terme |
| **Polarisation 80/20** (facile / modérée / difficile) | Modèle à 3 zones de Seiler (Seiler & Kjerland, 2006 ; Seiler, 2010) | idem, terminologie usuelle en entraînement d'endurance |
| **Allure ajustée à la pente** (« GAP ») | Modèle quartique tiré de records de course de Kay A., « Pace and critical gradient for hill runners: an analysis of race records », *J Quant Anal Sports* 8(4) (2012), doi: 10.1515/1559-0410.1456 ; prolongement par tangente au-delà de ses bornes (proposé par l'article). Choix et validation : [Allure ajustée à la pente (GAP)](gap.md) | Strava GAP, COROS Effort Pace, Suunto NGP — même principe (ajuster l'allure à la pente), calculs propriétaires non documentés publiquement dans le détail ; voir la limite du modèle ci-dessous |
| **Découplage aérobie (Pa:HR)** et **facteur d'efficacité (EF)** | Formule publique : EF = allure ajustée à la pente (GAP) / FC ; découplage = variation d'EF entre les deux moitiés d'une séance | Terminologie « Pa:HR » (« Pace:HR ») et « Efficiency Factor » popularisée par la **marque** TrainingPeaks — même principe, calcul propriétaire non documenté publiquement ; notre calcul est indépendant, fondé sur notre propre GAP (ligne ci-dessus) |
| **VAM** (vitesse ascensionnelle, gain d'altitude / durée sur une montée détectée) | Formule publique et triviale (une division) : terminologie d'origine cycliste, souvent associée informellement au préparateur Michele Ferrari — **aucune publication vérifiable identifiée** pour cette attribution précise, mentionnée uniquement comme repère historique | Segments de montée de la **marque** Strava, ClimbPro de la **marque** Garmin — concepts comparables (détecter des montées, en mesurer la performance), aucun calcul propriétaire reproduit |
| **Efficacité en descente** (moyenne pondérée par le temps du ratio vitesse GAP par échantillon / allure GAP de référence de la séance, par classe de pente descendante) | **Approximation du projet**, construite à partir du même modèle de Kay (2012) que le GAP ci-dessus — aucune formule publiée équivalente identifiée ailleurs | Aucun équivalent documenté publiquement identifié ; voir l'avertissement ci-dessous sur la limite du modèle sous-jacent |
| **Modèle personnel pente → allure** (médiane pondérée par le temps et la récence, par classe de pente fine, sur l'historique de l'athlète ; repli sur le modèle de Kay ci-dessus quand l'historique manque) | **Approximation du projet**, statistique descriptive (médiane, quartiles) appliquée à l'historique de l'athlète — aucune formule publiée équivalente identifiée | COROS *Effort Pace* personnalise déjà l'allure à la pente sur ses propres montres, à partir d'un calcul propriétaire non documenté publiquement ; notre modèle est indépendant, construit à partir des fichiers FIT de l'athlète, quelle que soit la montre |
| **Vitesse critique** (CS) et **réserve anaérobie D′** (ajustement distance = CS × durée + D′ sur les meilleurs efforts GAP de 3 à 20 min) | Concept de puissance critique : Jones AM & Vanhatalo A (2017), *Sports Med* 47(Suppl 1):65–78, doi: 10.1007/s40279-017-0688-0 ; Poole DC *et al.* (2016), *Med Sci Sports Exerc* 48(11):2320–2334, doi: 10.1249/mss.0000000000000939 (vérifiés via Crossref). Transfert à la course (vitesse critique), fenêtre 3–20 min, seuils de validité et pourcentages des cibles d'intervalles : **approximation du projet** | Équivalent course à pied du couple puissance critique / W′ du cyclisme ; termes génériques de la physiologie de l'effort, pas des marques ; aucun calcul propriétaire reproduit |
| **Dépense énergétique** (course : équation RE3 ; marche : polynôme marche de Minetti ; arrêt : métabolisme debout) | Course : Looney DP, Hoogkamer W & Kram R (2025), « Metabolic energy expenditure during level, uphill, and downhill running », *bioRxiv*, doi: 10.1101/2025.06.05.658094 (Eq. 4) — publiée depuis dans *Eur J Appl Physiol* 126:1621–1633, doi: 10.1007/s00421-025-05999-5 (vérifié via Crossref) —, plage de pentes réellement étudiée −45 % à +82 %. Marche : Minetti AE *et al.*, *J Appl Physiol* 93:1039–1046 (2002) — polynôme MARCHE (le polynôme course du même article servait à l'ancien GAP, remplacé par Kay 2012), plage étudiée ±45 %. Métabolisme debout : Looney DP *et al.* (2019), « Metabolic Costs of Standing and Walking in Healthy Military-Age Adults: A Meta-regression », *Med Sci Sports Exerc* 51(2):346–351 (1,44 W/kg, valeur reprise telle quelle par l'article RE3 ci-dessus). Seuils marche/arrêt (1,8 m/s / 0,3 m/s) et bornage de pente COURSE (±30 %, plus conservateur que la plage étudiée par la RE3) : **approximation du projet**. Calibration personnelle (route/trail) : **approximation du projet**, statistique descriptive (médiane, écart interquartile) appliquée à l'écart Garmin/modèle mesuré de l'athlète — comme le modèle personnel pente → allure ci-dessus, aucune formule publiée équivalente identifiée, appliquée UNIQUEMENT aux prévisions de course, jamais aux séances déjà mesurées | `calories_kcal` de **Garmin Connect** reste la référence par défaut partout ; ce calcul est un CONTRÔLE INDÉPENDANT (seuil de signalement d'écart défini à 15 %, `DELTA_ALERT_PCT`) et un outil de PRÉVISION pour le plan de course, jamais un remplacement |

!!! warning "GAP : approximation du projet, pas un équivalent des GAP propriétaires"
    Notre allure ajustée à la pente applique tel quel le modèle de Kay (2012),
    tiré de records de courses de montée et de descente. Il remplace le modèle de
    laboratoire de Minetti *et al.* (2002), qui surestimait le coût des montées et
    surtout le gain des descentes (comparaison et validation sur données réelles :
    [Allure ajustée à la pente (GAP)](gap.md)). Tiré de coureurs entraînés, il reste
    **généreux en descente** pour la plupart des athlètes et ne voit pas la
    technicité du terrain ; aucun outil grand public ne documente publiquement le
    détail de son propre calcul propriétaire, donc aucune comparaison ne peut être
    vérifiée pour eux spécifiquement. Notre GAP reste une
    **approximation du projet**, jamais une reproduction de Strava GAP, COROS
    Effort Pace ou Suunto NGP : ne pas présenter ces valeurs comme équivalentes.

!!! warning "Efficacité en descente : un ratio à soi-même, pas une note absolue"
    Notre efficacité en descente hérite directement de la limite du GAP ci-dessus
    (même modèle de Kay sous-jacent) : 1,00× = descendre comme un coureur de
    montagne entraîné, un repère **généreux pour la plupart des athlètes**. Le
    modèle n'est pas monotone en descente : le gain prédit est maximal vers -10 %
    (rapport d'allure ≈ 0,81) puis DIMINUE, revient au plat vers -21 % et devient
    une pénalité au-delà (-25 % ≈ 1,16 ; -30 % ≈ 1,38 ; -45 %, la borne du
    modèle, ≈ 2,08) — d'où deux classes distinctes au-delà de
    -20 % (`-20 à -30 %` et `< -30 %`), plutôt qu'un panier unique qui
    mélangerait des pentes aux prédictions radicalement différentes. Une valeur
    sous 1,00× est donc **fréquente et normale** — prudence tactique, terrain
    technique, freinage excentrique, portions marchées —
    jamais la preuve d'une mauvaise descente. Cet indicateur compare l'athlète
    à lui-même (l'allure GAP mesurée sur les sections plates de LA MÊME séance,
    ou à défaut sur tout ce qui n'est pas une forte descente), jamais à un score
    universel ni à un autre athlète : seule sa **tendance dans le temps, à
    classe de pente égale**, est exploitable — jamais une comparaison entre
    classes de pente différentes, ni une moyenne toutes classes confondues.

!!! note "Valeurs non comparables"
    Notre condition, notre fatigue et notre forme sont calculées sur le **TRIMP**
    (fréquence cardiaque), pas sur une charge issue de la puissance ou de l'allure :
    leurs valeurs ne se comparent pas à celles de TrainingPeaks, d'Intervals.icu ou
    de Garmin.

!!! warning "ACWR"
    La zone 0,8 – 1,3 est un **repère indicatif**. Son lien avec le risque de
    blessure est discuté dans la littérature (Impellizzeri *et al.*, 2020) : le
    tableau de bord ne l'utilise jamais comme un seuil.

## Règle pour les contributions et les agents

- Ne pas écrire **TSS, NP, IF, rTSS, hrTSS, NGP** ni **CTL, ATL, TSB** dans
  l'interface, les fichiers du workspace ou la documentation. Seule exception : les
  tableaux d'équivalence de cette page et le texte des hypothèses du tableau de bord.
- Dire *charge* (TRIMP), *condition*, *fatigue*, *forme*.
- `tests/lint/test_trademarks.py` fait respecter cette règle.
