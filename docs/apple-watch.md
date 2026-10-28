# Apple Watch

Le coach sait lire [intervals.icu](intervals-setup.md) (`[data].source = "intervals"`).
**Aucune nouvelle source n'est à coder pour une Apple Watch** : il suffit d'amener les
données d'Apple Santé jusqu'à intervals.icu. C'est la recette du membre de la famille sans
montre Garmin ([Mode famille](family.md)) : un workspace peut être en source `garmin`, le
suivant en source `intervals`.

!!! info "intervals.icu n'importe pas Apple Santé nativement"
    Ce sont des applications iOS tierces qui y poussent les données. Les noms d'applications
    ci-dessous sont ceux retenus pour le projet ; vérifiez leur état et leurs conditions
    avant de vous y engager (voir « À vérifier »).

## La chaîne

```
Apple Watch → Santé ─┬─ HealthFit (payant, achat unique) ─ séances en FIT (FC, GPS, splits) ─► intervals.icu
                     └─ Intervals.icu Companion (gratuit / soutien) ou IntervalsWellnessSync (bêta)
                        ─ FC de repos, HRV (SDNN, rMSSD nocturne en option), phases de sommeil, poids ─► intervals.icu
intervals.icu ─ intervals-icu-mcp (clé API du membre) ─► son workspace (sync en mode `schedule`)
```

- **Séances** : HealthFit exporte les entraînements en fichiers FIT (fréquence cardiaque, GPS,
  splits) vers intervals.icu.
- **Bien-être** : Intervals.icu Companion (ou IntervalsWellnessSync, en bêta) pousse la
  fréquence cardiaque de repos, la HRV, les phases de sommeil et le poids.
- **Côté coach** : le serveur MCP intervals.icu lit ces données avec **la clé API du membre**
  ([Configuration Intervals.icu](intervals-setup.md)).

## Mise en route

```bash
./install.sh --workspace ~/coachs/coach-alice --source intervals
```

Puis, dans `config/workspace.user.toml` du membre :

```toml
[data]
source = "intervals"

[sync]
mode = "schedule"      # le mode « watch » est réservé à Garmin
```

Prévoyez **une semaine d'observation** avant de se fier aux données : vérifiez dans
intervals.icu que les séances et le bien-être arrivent bien, puis qu'un FIT HealthFit se
télécharge avec `download_fit.py <id intervals>` (voir
[Téléchargement FIT](skills/fit-download.md)).

## Ce que cela change pour le coach

Toutes ces conséquences sont déjà couvertes par les règles du projet
(`skills/data-source-mapping/SKILL.md`, table de correspondance Garmin ↔ intervals.icu) :

| Sujet | Avec une Apple Watch via intervals.icu |
|---|---|
| **Readiness** | Pas d'équivalent au Training Readiness Garmin. À `morning_check = "full"`, le bilan matinal est HRV + FC de repos, et « readiness indisponible » est dit explicitement. Le score de Companion arrive dans `subjective.readiness` et n'est **jamais** présenté comme équivalent. |
| **HRV** | Apple fournit du SDNN (mesures ponctuelles), pas du rMSSD nocturne. Les valeurs ne sont pas comparables entre membres ; chaque workspace a ses propres références. |
| **FC de récupération et splits** | Pas de HRR (`recovery_hr_bpm`) ni de `splits` Garmin : champs omis, jamais inventés. `course-comparison` est indisponible pour ce membre. |
| **Synchronisation** | `[sync].mode = "schedule"`, jamais `watch`. |
| **Séances planifiées** | Le coach les crée côté intervals.icu avec `create_event` (skill [Intervals.icu](skills/intervals-icu-best-practices.md)) ; Companion peut les pousser vers la montre. |

## Ne jamais passer par Strava

!!! danger "Strava est exclu"
    Les activités venues de Strava sont refusées par l'API intervals.icu, et les conditions
    d'utilisation de Strava (novembre 2024, juin 2026) interdisent l'usage par une IA et par
    des intermédiaires. N'envoyez pas vos séances Apple Watch vers intervals.icu *via* Strava.
    Voir aussi [Configuration Strava](strava-setup.md).

## À vérifier

Le projet ne garantit pas le comportement des passerelles tierces ; à contrôler pendant la
semaine d'observation :

- que les séances HealthFit arrivent complètes dans intervals.icu (FC, GPS, splits) ;
- que Companion ou IntervalsWellnessSync poussent bien FC de repos, HRV, sommeil et poids, et à
  quelle fréquence ;
- que `download_fit.py <id intervals>` récupère le FIT d'une séance HealthFit ;
- que le premier `medical/*_health.md` indique « readiness indisponible » plutôt qu'un score.

## Plan B : Health Auto Export

Si les passerelles ci-dessus déçoivent, **Health Auto Export** (version Premium) peut envoyer
les données par webhook REST vers la machine maison. La couverture est plus large et aucun
cloud tiers n'intervient, mais il faudrait une **nouvelle source**
`[data].source = "applehealth"`, **qui n'est pas implémentée**. Elle toucherait l'installeur, la
table de correspondance de `skills/data-source-mapping/SKILL.md`, le contrat de données, la synchronisation quotidienne,
`coach_doctor`, la politique du chat et `download_fit.py`.

À surveiller : Open Wearables, auto-hébergeable avec un MCP intégré, mais pré-1.0
(voir [Open Wearables](open-wearables.md)).

## Autres appareils

Tout ce qui se synchronise nativement vers intervals.icu (Polar, COROS, Suunto, Wahoo, données
bien-être d'Oura) réutilise la source `intervals` sans code supplémentaire.
