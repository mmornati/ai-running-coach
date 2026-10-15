---
name: vanoor-export
description: Use ONLY when `[vanoor].export = "on"` — writes the week's running sessions (structured steps, HR/pace targets, repeats) and the race plan (one step per pacing segment, aid-station reminders) as `.vanoor` files the athlete imports into the Vanoor app on iPhone, which sends them to the Apple Watch. Runs scripts/arc_vanoor.py (week: structure composed by the coach from the week's instructions and personal targets, read on stdin, validated against the published Vanoor limits; race: deterministic from the race plan segments; validate). Nothing is pushed anywhere — the file goes to `[vanoor].output_dir`. Never changes whether a session happens or its intensity.
---

# Skill: vanoor-export

Écrit les séances de course de la semaine et le plan de course au format **Vanoor**
(schéma « vanoor.workout/1 »), l'application de course pour Apple Watch. Vanoor n'a ni serveur ni
API : l'athlète importe le fichier dans l'app iPhone (*Mes séances → + → Importer des
séances*), qui l'envoie à la montre. C'est l'équivalent, pour une Apple Watch, du push au
calendrier Garmin — sans date (les séances sont rangées par dossier) et sans rien envoyer
nulle part.

## Quand l'utiliser

- **Uniquement si `[vanoor].export = "on"`** (règle de résolution habituelle :
  `config/workspace.user.toml` prime). À `off` (défaut, absent ou valeur inconnue) : ne
  jamais parler de Vanoor ni de fichier `.vanoor`.
- **Coach** : à chaque validation de semaine (et à chaque modification d'une séance de course
  déjà exportée : le fichier de la semaine est réécrit en entier).
- **Course-strategist** : après l'écriture du plan de course (`race_plan` avec `segments`).
- **Jamais** pour décider *si* une séance a lieu ni à quelle intensité : le bilan matinal
  (`[health].morning_check`), `medical`, les garde-fous et la semaine planifiée priment. Une
  séance annulée ou remplacée sort du fichier à la réécriture suivante.
- Utilisable en headless : le script n'écrit que dans le dossier choisi par l'athlète et ne
  contacte aucun service.

## Séances de la semaine

1. **Lire la semaine** : `planning/Semaine_<lundi>.md` (bloc `arc` `week`, consignes du tableau).
   Seules les séances `running` / `trail` vont dans Vanoor (pas le renforcement, le vélo, la
   randonnée) ; les séances déjà `done` ou `cancelled` n'y vont pas.
2. **Cibles personnelles** : pour chaque séance, `python3 scripts/arc_workout_targets.py targets
   --session planning/Semaine_<lundi>.md#AAAA-MM-JJ` — mêmes règles que pour Garmin (#60) :
   - FC : `hr_target.bounds_bpm` → étape `"target": "hr_range"` avec `minBpm`/`maxBpm`. Toujours
     la plage en bpm de l'athlète, **jamais** `hr_zone` (les zones de Vanoor sont réglées dans
     l'app, rien ne garantit qu'elles soient celles du profil).
   - Allure : seulement là où la séance donne une allure (repère sur le plat, cible d'intervalle
     en % de vitesse critique si l'ajustement est valide) → `"target": "pace"` avec
     `"paceRange": [allure lente, allure rapide]` en s/km (le script en tire le milieu et la
     marge). Une valeur `null` = pas de cible d'allure, jamais une allure devinée.
   - Chaleur (`--heat`) : mêmes cibles ajustées que pour Garmin.
3. **Composer la structure** à partir des consignes de la séance, sans rien ajouter :
   - une étape `split` par partie (échauffement, blocs, récupérations, retour au calme), à la
     **durée** quand la consigne est en minutes, à la **distance** quand elle est en mètres ;
   - un répétitif → `"type": "repeat"` avec `count` et ses étapes (`split` uniquement) ;
   - effort au ressenti (lignes droites, marche active en côte, descente à 7/10) →
     `"conversational"` avec la consigne dans le `label` (Vanoor l'affiche « Conversation » :
     le libellé porte l'intention) ; récupération ou marche → `"open"` ;
   - montée raide d'une séance trail : cible FC ou ressenti, jamais une allure (pas d'allure
     ajustée à la pente dans Vanoor) ;
   - ravitaillement prévu par la séance (sortie longue : gel, eau) →
     `{"type": "nutrition", "trigger": "elapsed", "seconds": …, "items": [{"name": "gel",
     "quantity": 1, "unit": "pcs"}]}` — seulement ce que la séance prévoit ;
   - `label` court, dans la langue des documents.
4. **Écrire** (JSON sur l'entrée standard, heredoc à délimiteur entre apostrophes) :
   ```bash
   python3 scripts/arc_vanoor.py week --week planning/Semaine_2026-10-12.md << 'EOF'
   {"sessions": [
     {"session": "2026-10-15", "steps": [
       {"type": "split", "label": "Endurance", "duration": 2400, "target": "hr_range", "minBpm": 137, "maxBpm": 149},
       {"type": "repeat", "count": 4, "steps": [
         {"type": "split", "label": "Ligne droite ~90 %", "distance": 100, "target": "conversational"},
         {"type": "split", "label": "Retour marche", "duration": 60, "target": "open"}]}]}
   ]}
   EOF
   ```
   `session` suit la grammaire de `arc_workout_targets.py` : `AAAA-MM-JJ`, `AAAA-MM-JJ@index`
   ou `AAAA-MM-JJ:titre` quand plusieurs séances tombent le même jour. Le nom de chaque séance
   (« Jeu 15/10 · <titre> ») et le dossier (« Semaine du 12/10 ») viennent du fichier semaine.
   `--dry-run` montre le document sans l'écrire.
5. **Lire la sortie** (JSON) : `status` `written` + `path` ; `missing` liste les séances de course
   encore planifiées que tu n'as pas fournies — en oublier une est une faute, sauf choix
   explicite (le dire). `error` : l'étape fautive est nommée, corriger et relancer, jamais
   contourner. `disabled` (code 2) : `[vanoor].export` n'est pas `on`, ne rien dire de plus.

## Plan de course

Après l'écriture du plan (`planning/…` au contrat `race_plan`, avec `segments`) :

```bash
python3 scripts/arc_vanoor.py race --plan planning/2026-10-20_plan_course_feodieres.md
```

Une séance par scénario du plan (`--scenario realistic --scenario ambitious` pour en choisir),
une étape par segment, à la distance du segment, cible d'allure du scénario (marge ±30 s/km en
montée, ±20 s/km ailleurs — approximation du projet), et un rappel « Ravito <nom> » au
kilomètre de chaque `aid_stations[]` du plan. Une allure hors des bornes de Vanoor
(120–1200 s/km, montée marchée d'ultra) devient une étape au ressenti, signalée dans
`warnings`. Aucune nutrition inventée : seuls les ravitos du plan.

Dire à l'athlète d'**attacher le GPX de la course** à la séance dans l'éditeur de Vanoor
(onglet *Parcours*, puis *Parcours* de la séance) pour avoir le tracé hors ligne.

## Ce que l'athlète doit savoir (le dire une fois, pas à chaque export)

- **Import** : le fichier est dans `[vanoor].output_dir` (dossier iCloud Drive si l'athlète l'a
  choisi, sinon `exports/vanoor/` du workspace) ; dans l'app iPhone, *Mes séances → + →
  Importer des séances*. Réimporter une semaine réécrite remplace à la main l'ancienne version
  dans l'app (le format n'a pas d'identifiant de séance).
- **Pas de date** : Vanoor range par dossier, il n'y a pas de calendrier.
- **Le retour ne garde pas la structure** : la séance faite revient par Apple Santé (puis
  intervals.icu, via Intervals.icu Companion ou HealthFit) avec un seul tour ; les étapes
  se retrouvent à la vitesse (`session-parts-analyzer`), pas dans le FIT.
- **Distance GPS** : en trail, les étapes à la distance peuvent se décaler de quelques
  pourcents sur le terrain ; c'est la montre qui mesure, pas le GPX.
- Les estimations de distance/durée affichées par l'app pour une étape sans cible d'allure
  ne viennent pas du projet.

## Limites du format (vérifiées par le script)

50 séances par fichier, 100 étapes par séance, 20 étapes par répétition (1 à 30 fois),
distance 1–100 000 m, durée 1–86 400 s, allure 120–1200 s/km, zone FC 1–5. Format relevé dans
les instructions d'import de l'app (schéma « vanoor.workout/1 ») ; `python3 scripts/arc_vanoor.py
validate <fichier>` vérifie un fichier existant.
