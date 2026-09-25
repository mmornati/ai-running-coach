# Marques et métriques

ai-running-coach est un projet **indépendant**, sous licence MIT. Il n'est ni
affilié à Garmin, TrainingPeaks, Intervals.icu ou Strava, ni approuvé, parrainé ou
soutenu par eux.

## Marques citées

| Marque | Titulaire | Pourquoi elle apparaît |
|---|---|---|
| Garmin®, Garmin Connect™ | Garmin Ltd. ou ses filiales | Source des données (activités, sommeil, HRV) et calendrier des séances |
| Body Battery™, Firstbeat Analytics™, *Training Readiness* | Garmin Ltd. ou ses filiales | Scores lus tels que Garmin les fournit, jamais recalculés |
| TrainingPeaks®, TSS®, NP®, IF® | Peaksware LLC (groupe Garmin depuis juillet 2026) | Non utilisés par le projet |
| CTL, ATL, TSB | revendiqués par Peaksware LLC | Cités seulement pour l'équivalence ci-dessous |
| Intervals.icu, Strava | leurs éditeurs respectifs | Services tiers, facultatifs |

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
