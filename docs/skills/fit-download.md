# Skill : Téléchargement FIT

> **Description** : Téléchargement de fichiers FIT (et leurs records GPS en JSON) en **bypassant le canal MCP** — depuis Garmin Connect ou Intervals.icu, selon `[data].source`.

<!-- arc-video:analyse-seance -->
<div class="arc-video-card" markdown>

[![Disséquer une sortie](../video/analyse-seance/poster.jpg)](../video/analyse-seance/index.html)

<div markdown>

<span class="arc-video__meta">En vidéo · Étape 07 · 1 min 39</span>

**[Disséquer une sortie](../video/analyse-seance/index.html)** — Une sortie trail passée au scalpel : FIT, zones, allure ajustée, dérive, montées, durabilité, HRR, énergie, comparaison.

[Regarder](../video/analyse-seance/index.html) · [English](../video/analyse-seance/index.html?lang=en) · [Toutes les vidéos](../videos.md)

</div>

</div>
<!-- /arc-video -->


## Pourquoi ce skill existe

- Le MCP Garmin (`get_activity_fit_data`) **timeoute** sur les téléchargements FIT (payloads de plusieurs Mo)
- **Garmin** : le script `download_fit.py` utilise la lib `garminconnect` installée dans l'environnement `garmin-mcp` + les **tokens locaux** `~/.garminconnect` → **aucun mot de passe** nécessaire
- **Intervals.icu** : le script appelle l'API REST avec la **clé API déjà configurée pour le serveur MCP** → aucune nouvelle configuration. Fonctionne pour toutes les montres qu'Intervals.icu synchronise (Garmin, COROS, Suunto, Polar, Apple Watch via HealthFit…), **sauf les activités importées depuis Strava**, que l'API Strava interdit de redistribuer (signalées `INDISPONIBLE`, jamais inventées). Voir [Intervals.icu — Fichiers FIT](../intervals-setup.md#fichiers-fit)

- **Strava** (#164) : pas de fichier FIT — le script appelle l'API REST (`/activities/<id>/streams`, bibliothèque standard) avec les **jetons du serveur MCP communautaire** (rafraîchis et réécrits atomiquement, jamais affichés) et normalise les flux par seconde directement en `activities/fit/s<chiffres>.json` : mêmes KPI que le FIT. Voir [Configuration Strava](../strava-setup.md#flux-par-seconde-et-kpi)

## Quand l'utiliser

- Télécharger un **fichier FIT** d'une activité Garmin ou Intervals.icu
- Récupérer les **records GPS** en JSON
- Analyser une activité en détail hors du canal MCP

## Fonctionnalités

- Téléchargement de fichiers FIT via la lib `garminconnect` (Garmin) ou l'API REST (Intervals.icu, bibliothèque standard)
- Récupération des records GPS en JSON
- Utilisation des tokens locaux (pas de mot de passe)
- **Auto-relaunch** : le script se relance dans l'environnement `garmin-mcp` (ou `intervals-icu-mcp`) si les dépendances manquent

## Script

`skills/fit-download/scripts/download_fit.py` — nécessite `garminconnect` + `fitparse` pour Garmin (environnement `garmin-mcp`), `fitparse` seul pour Intervals.icu avec `--json` (environnement `intervals-icu-mcp`, installé par `./install.sh --source intervals`).

Avec `--json`, écrit aussi une copie **normalisée** au chemin canonique
`activities/fit/<id>.json` — `<id>` = `garmin_activity_id`, `intervals_activity_id` ou `strava_activity_id` (`s<chiffres>`) (unités SI, mapping documenté dans
`scripts/arc_samples.py`) — c'est ce fichier que `scripts/arc_index.py` ingère dans la
table dérivée `activity_sample` (voir [Mode headless](../dashboard/headless.md)).
Donnée brute et jetable, jamais versionnée.

## Rattraper la dynamique de course

Depuis #151, l'extraction normalisée reprend aussi la **dynamique de course** Garmin :
temps de contact au sol (`stance_time`, ms → `ground_contact_s`, s), balance du temps de
contact (`stance_time_balance`, % → `stance_balance_pct`), oscillation verticale
(`vertical_oscillation`, mm → `vertical_oscillation_m`, m), ratio vertical (`vertical_ratio`, %
→ `vertical_ratio_pct`) et longueur de pas (`step_length`, mm → `step_length_m`, m). Une mesure
absente reste absente — **jamais 0, jamais 50 % de balance** (certains capteurs ne fournissent pas
la balance). Les nouveaux téléchargements `--json` l'embarquent d'office ; les
`activities/fit/<id>.json` déjà écrits **n'ont pas ces champs**. Pour les rattraper **sans rien
re-télécharger**, depuis les `.fit` déjà présents dans `activities/` :

```bash
python3 skills/fit-download/scripts/download_fit.py --refresh-dynamics --dry-run   # liste id par id, n'écrit rien
python3 skills/fit-download/scripts/download_fit.py --refresh-dynamics             # réécrit les JSON dérivés
python3 scripts/arc_index.py gait-summary                                          # réindexe et rend la synthèse
```

Le compte rendu distingue les JSON **à créer** (un `.fit` téléchargé sans `--json` n'avait pas de copie
normalisée : elle est créée) de ceux **à réécrire** (copie existante sans dynamique), liste les id concernés
(`-v` ajoute ceux déjà à jour) et compte les échecs.

Il traite aussi bien les `.fit` Garmin (`<entier>.fit`) que ceux de la source Intervals.icu
(`i<chiffres>.fit`, même dossier `activities/`, copie `fit/i<chiffres>.json`) : la synthèse Foulée
rattache les échantillons à la séance par `garmin_activity_id`, sinon `intervals_activity_id`. Attention : un
FIT Intervals.icu n'embarque la dynamique que si la montre l'enregistre et que l'activité n'a pas été
importée depuis Strava (alors aucun FIT n'est disponible).

`--refresh-dynamics` ne nécessite que `fitparse` (présent dans l'environnement `garmin-mcp` comme dans
celui d'`intervals-icu-mcp` — le script essaie de se relancer dans l'un puis l'autre :
`garmin-mcp` ou `intervals-icu-mcp`) — **aucune connexion Garmin, aucun token**. Il n'écrit que les copies normalisées
`activities/fit/<id>.json` (jetables, jamais versionnées) — jamais un Markdown de séance, jamais un
`.fit`. Il est **idempotent** : un JSON déjà à jour est laissé tel quel. Seuls les `.fit`
présents sont traités ; pour ceux que vous avez supprimés, relancez un téléchargement
(`--from-dir activities/ --json --overwrite` sur les séances concernées). Voir la carte
[Foulée](../dashboard/views.md#foulee) du tableau de bord.

## Rattraper l'historique pour la dépense énergétique modèle

Le [modèle de dépense énergétique](../energie.md) (`scripts/arc_energy.py`,
table dérivée `activity_energy`) se calcule automatiquement pour toute séance
dont le FIT est déjà ingéré — il ne manque donc **que** pour les séances plus
anciennes dont le FIT n'a jamais été téléchargé. Pour le rattraper :

1. **Télécharger les FIT manquants**, avec `--from-dir` (qui scanne tous les
   `garmin_activity_id` des `activities/*.md`) ET `--json` (indispensable :
   sans lui, seul le `.fit` brut est écrit, jamais la copie normalisée que
   `scripts/arc_index.py` ingère) :

   ```bash
   python3 skills/fit-download/scripts/download_fit.py --from-dir activities/ --json
   ```

   Une séance déjà rattrapée (sa copie normalisée
   `activities/fit/<id>.json` existe déjà) est sautée
   automatiquement, même avec `--json` — relancer cette commande sur un
   historique déjà (partiellement) rattrapé ne re-télécharge donc que ce qui
   manque encore, jamais tout l'historique à chaque fois. `--overwrite` force
   quand même un nouveau téléchargement.
2. **Réindexer** : `python3 scripts/arc_index.py energy` (ou toute autre
   sous-commande — chacune réindexe le workspace au passage) recalcule alors
   `activity_energy` pour chaque séance dont le FIT vient d'être ingéré,
   automatiquement, sans étape dédiée.

**Optionnel — compléter `calories_bmr_kcal` des anciennes séances** : ce champ
(part de métabolisme de base côté Garmin) permet le calcul du NET (voir
[Dépense énergétique — brut vs net](../energie.md#brut-vs-net)) mais n'est
disponible qu'à la synchronisation — une séance ancienne peut donc avoir son
FIT rattrapé sans jamais avoir ce champ. Pour le compléter, un agent peut lire
`bmr_calories` d'une activité Garmin **une séance à la fois** (jamais une
plage) et l'ajouter au bloc ```` ```arc ```` existant du fichier
`activities/*.md` concerné. Ce n'est qu'un complément : le rattrapage du FIT
(étapes 1-2 ci-dessus) suffit déjà à obtenir le kcal BRUT du modèle, comparable
tel quel à `calories_kcal` Garmin.

**Ce n'est pas ce que fait le backfill du contrat de données** (skill
[Backfill du contrat](../skills/arc-backfill.md), CLI `scripts/arc_index.py
backfill-plan`) : celui-ci complète les fichiers Markdown dont le bloc
```` ```arc ```` est absent ou incomplet (par exemple sans
`garmin_activity_id` ou sans `calories_kcal` du tout) — un problème
DIFFÉRENT d'un FIT manquant. Une séance peut très bien avoir un bloc
```` ```arc ```` complet et valide, mais toujours pas de FIT téléchargé (donc
pas de dépense énergétique modèle) : c'est cette page-ci, pas le backfill du
contrat, qui s'applique dans ce cas.

## Fichier source

`skills/fit-download/SKILL.md`
