# Correction altimétrique par MNT

> **Fonction optionnelle, désactivée par défaut (#176).** Aucune coordonnée ne quitte votre machine tant que vous ne l'avez pas demandé.

<!-- arc-video:ultra -->
<div class="arc-video-card" markdown>

[![La nuit, la roche et le roadbook](video/ultra/poster.jpg)](video/ultra/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 14 · 1 min 49</span>

**[La nuit, la roche et le roadbook](video/ultra/index.html)** — Préparer un ultra : la nuit calculée sur place (crépuscule, frontale, heure d'hiver), le dénivelé corrigé par un modèle de terrain, la technicité du sentier, puis le roadbook imprimable avec passages, barrières et matériel obligatoire.

[Regarder](video/ultra/index.html) · [English](video/ultra/index.html?lang=en) · [Toutes les vidéos](videos.md)

</div>

</div>
<!-- /arc-video -->

Le D+ alimente presque tout : GAP, modèle pente → allure, VAM, descente, durabilité, énergie, pacing de course, évaluation de parcours. Or l'altitude d'un GPX est bruitée (GPS seul) et celle d'un FIT dérive (baromètre) ; `scripts/arc_elevation.py` lisse le signal mais ne peut pas corriger un biais. La correction rééchantillonne la trace sur un **modèle numérique de terrain** (MNT) public.

## Sources de données

| Zone | Service | Données | Licence / attribution |
|---|---|---|---|
| France métropolitaine (boîte englobante approchée, Corse incluse) | [API d'altimétrie de la Géoplateforme](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/calcul-altimetrique/) — `data.geopf.fr`, ressource `ign_rge_alti_wld`, sans clé | RGE ALTI®, pas de 1 m là où il est disponible | Licence Ouverte Etalab 2.0 — « Altitudes : IGN, RGE ALTI® via la Géoplateforme » |
| Ailleurs, et points que l'IGN ne couvre pas (`z = -99999`) | [Open-Meteo Elevation API](https://open-meteo.com/en/docs/elevation-api) — `api.open-meteo.com` | Copernicus DEM GLO-90 (pas de 90 m, altitudes entières ; `0` en mer) | Données sous CC BY 4.0 ; attribution obligatoire à Copernicus (DOI 10.5270/ESA-c5d3d65) et à Open-Meteo |

Limites : IGN 5 requêtes/s par IP et 5000 points par requête (documentés) — le module envoie des lots de 200 points et espace ses appels de 0,25 s. Open-Meteo : 100 coordonnées par requête (au-delà, HTTP 400) et, pour l'API gratuite, moins de 10 000 appels par jour, 5 000 par heure et 600 par minute ([conditions d'utilisation](https://open-meteo.com/en/terms)) ; un parcours de 3000 nœuds coûte 30 appels. Les deux services ont été interrogés avec de vraies requêtes sur des sommets publics (développement puis relecture #176) ; les formes de réponse ci-dessus sont celles observées, y compris `-99999` au milieu d'un lot IGN pour un point hors de France.

### Usage commercial : Open-Meteo payant

L'API gratuite d'Open-Meteo est réservée à un **usage non commercial** : ses conditions citent les sites ou applications privés ou à but non lucratif sans abonnement ni publicité, et la domotique personnelle. Selon notre lecture (non validée par Open-Meteo), un athlète qui fait tourner ce projet libre pour son propre entraînement relève de cet usage. En revanche, un **coach ou une structure qui l'utilise dans une activité rémunérée** (suivi d'athlètes payant, service avec abonnement ou publicité) doit souscrire une offre Open-Meteo (clé d'API, autre point d'accès) — ce que le module ne gère pas : dans ce cas, gardez `[elevation].dem = "off"`, ou n'utilisez `--dem` que sur des parcours entièrement couverts par l'IGN (Licence Ouverte, réutilisation commerciale autorisée) — attention, le repli automatique vers Open-Meteo s'applique toujours aux points que l'IGN ne couvre pas (mer, au-delà de la frontière).

Les lignes d'attribution sont rendues avec chaque rapport (`analyze_gpx.py`, `arc_race_pacing.py`, `dem-check`) et doivent être reprises dans les fiches persistées.

## Vie privée — ce qui est envoyé

- **Uniquement des coordonnées** (latitude/longitude arrondies : 5 décimales IGN ≈ 1 m, 4 décimales Open-Meteo ≈ 11 m), par lots, **amincies** (un point tous les 50 m par défaut). Jamais d'identifiant, de date, de fréquence cardiaque, de nom de fichier ni de contenu du workspace. L'adresse IP de votre machine reste visible du fournisseur.
- **Parcours de course (GPX publiés)** : itinéraires publics, correction possible sur demande (`--dem`) ou en permanence avec `[elevation].dem = "auto"`.
- **Séances personnelles** : une trace d'activité révèle votre domicile. Elles ne sont interrogées qu'avec `[privacy].dem_for_activities = true`, et seulement par `arc_index.py dem-check`. Les **premiers et derniers mètres** de la trace (`[privacy].dem_trim_m`, **500 m** par défaut, 200 à 5000 m) ne sont jamais envoyés.
- **Ce rognage ne protège qu'en partie.** Une sortie qui part de chez vous suit ensuite votre rue et votre quartier : la trace envoyée commence à quelques centaines de mètres de votre porte, et plusieurs séances superposées désignent le même point de départ. Il ne masque pas non plus un lieu fréquent au milieu de la trace (travail, club). Si votre domicile doit rester inconnu du fournisseur, laissez `dem_for_activities = false` — c'est le défaut — ou augmentez nettement `dem_trim_m` (au prix des premiers et derniers kilomètres, qui ne sont alors pas comparés).
- Un GPX qui est l'enregistrement d'une de vos sorties n'est pas un « parcours public » : ne le passez pas à `--dem` sans y avoir réfléchi (le rognage ne s'applique qu'à `dem-check`).
- Aucun envoi tant que les réglages sont à leur défaut.

## Réglages

```toml
[elevation]
dem = "off"        # "off" (défaut) | "auto" : corrige d'office les GPX de course
step_m = 50        # pas d'amincissement des coordonnées envoyées (5 à 500 m)
cache = true       # cache local <workspace>/.arc/dem-cache.json

[privacy]
dem_for_activities = false   # true = autorise `arc_index.py dem-check` sur une séance
dem_trim_m = 500             # mètres jamais envoyés en début ET fin de séance (200 à 5000)
```

À poser dans `config/workspace.user.toml` (voir [la configuration](configuration.md)). Une valeur invalide retombe sur le défaut prudent avec un avertissement.

## Utilisation

```bash
# Évaluation de parcours : le D+ MNT devient la référence, le D+ du fichier reste affiché
python3 skills/gpx-analysis/scripts/analyze_gpx.py --gpx course.gpx --dem

# Plan de course : les segments, les allures et l'énergie reposent sur l'altitude MNT
python3 scripts/arc_race_pacing.py plan --gpx course.gpx --dem ...

# Séance (opt-in [privacy].dem_for_activities) : comparaison seulement, rien n'est remplacé
python3 scripts/arc_index.py dem-check <garmin_activity_id | i<id intervals>>
```

`--no-dem` annule `[elevation].dem = "auto"` pour un appel. Exemple de rapport :

```text
## Correction altimétrique (MNT)
| | D+ fichier | D+ MNT (référence) | Écart |
| D+ | 1840 m | **1620 m** | -220 m (-12 %) |
```

### Pour une séance : proposer sans imposer

Le baromètre d'un FIT récent est souvent meilleur qu'un MNT (tunnels, ponts, galeries, arbres, maille de 90 m). `dem-check` rend donc **une comparaison** — D+ enregistré, D+ MNT, biais moyen (MNT − enregistré) — et **ne remplace ni n'écrit jamais** l'altitude enregistrée, ni dans l'index ni dans le Markdown. Un biais moyen persistant de plusieurs mètres signale un baromètre à recaler (calibration de la montre), pas un D+ à corriger après coup.

## Hors ligne et robustesse

- Réseau coupé, quota dépassé (HTTP 429/5xx : 3 essais, attente 1 s puis 2 s), réponse inattendue ou couverture < 80 % des points : **le comportement antérieur est conservé** (altitude du fichier), avec un avertissement explicite (`status = "unavailable"` dans `--json`). Jamais de valeur inventée.
- Cache local par fournisseur et coordonnée arrondie : un parcours déjà analysé ne refait aucun appel. Supprimez `.arc/dem-cache.json` pour le vider.

## Hypothèses et limites

Voir `scripts/arc_dem.py::ASSUMPTIONS` et `scripts/arc_elevation.py::ASSUMPTIONS["dem_series"]` :

- **Résolution** : un MNT donne l'altitude du terrain (RGE ALTI) ou de la surface (GLO-90 : cime des arbres et toits peuvent y entrer, erreur verticale de quelques mètres, pire en relief abrupt). Une crête étroite ou un fond de gorge plus fins que la maille sont lissés.
- **Erreur horizontale du GPS** : 5 à 10 m de décalage valent 1,5 à 3 m d'altitude sur 30 % de pente avec un MNT de 1 m.
- **Amincissement** : une ondulation plus courte que `step_m` n'est pas comptée ; le D+ MNT est une référence de terrain, pas un cumul brut de capteur. Il est calculé sans lissage ni seuil (série interpolée sans bruit), contrairement au D+ d'un GPX brut (lissage 3 points, seuil de 1 m). L'interpolation linéaire entre altitudes vraies ne peut que **sous-estimer** le D+ du terrain : simulation du projet, écart inférieur à 2,5 % pour des ondulations de 300 m de long et plus, mais −24 % pour des bosses de 3 m tous les 100 m au pas de 50 m.
- **Surestimation possible en traversée** : sans seuil, l'erreur horizontale du GPS sur un sentier à flanc de pente (balcon, lacets) ajoute du faux D+ — simulation du projet sur 10 km et 500 m de vrai D+ : de +0 à +4 % avec une erreur GPS corrélée sur environ 200 m (cas habituel), jusqu'à +30 % si l'erreur varie d'un nœud à l'autre (trace très bruitée). Un seuil anti-bruit n'y change presque rien et effacerait les vraies petites bosses : il n'est donc pas appliqué.
- **Changement de fournisseur** : une trace qui passe de l'IGN à Open-Meteo (frontière, trou de couverture) peut montrer une marche de quelques mètres à la transition (MNT de terrain contre MNT de surface).
- **Ponts, tunnels, galeries** : absents du MNT ; le parcours suit alors le sol.
