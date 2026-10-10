#!/usr/bin/env python3
"""Source des données de santé du bilan matinal (#218, épopée #216 Open Wearables).

Ce module est le SEUL endroit qui résout `[health].source` et qui dit à quelle source
appartient une ligne `health_day`. Stdlib seule, AUCUN appel réseau.

`[health].source` :
- `"primary"` (défaut, ou clé absente/vide/invalide) : la santé vient de `[data].source`
  (comportement historique, inchangé) ;
- `"openwearables"` : instance Open Wearables auto-hébergée, opt-in, lecture seule
  (`[health.openwearables].provider` nomme l'UN fabricant lu). Jamais pour des données Garmin.

Une valeur invalide vaut `"primary"` avec un avertissement sur stderr, jamais une exception
(la fonction est appelée par chaque commande de l'index). Indépendant de `[health].cycle_tracking`.

Source EFFECTIVE d'une ligne santé : son `health_source` ; à défaut (fichier antérieur à #218),
le `[data].source` configuré (`ASSUMPTIONS["default_source"]`). Pour `openwearables`, la clé de
comparaison est le couple (source, `health_provider`) : deux fabricants ne se mélangent pas non plus.
"""

import sys
from typing import Dict, Optional, Tuple

SOURCES = ("primary", "openwearables")
DEFAULT_SOURCE = "primary"
# Valeurs de `health.health_source` dans le bloc `arc` (contrat) : d'où viennent HRV, FC de repos, sommeil.
FILE_SOURCES = ("garmin", "intervals", "openwearables")
DATA_SOURCES = ("garmin", "intervals", "strava")
DEFAULT_DATA_SOURCE = "garmin"
# Fournisseurs santé acceptés derrière Open Wearables (UN seul). `garmin` (donnée directe, décision de
# l'épopée) et `strava` (aucune donnée santé) sont refusés.
PROVIDERS = ("oura", "whoop", "polar", "ultrahuman", "withings", "google_health", "apple",
             "health_connect", "samsung", "suunto")
REFUSED_PROVIDERS = ("garmin", "strava")

ASSUMPTIONS = {
    "default_source": "Un fichier santé sans `health_source` (antérieur à #218) est réputé venir du "
                      "`[data].source` configuré (garmin par défaut) : hypothèse du projet, il n'y a aucun moyen "
                      "de le vérifier après coup. Conséquence : changer `[data].source` ré-étiquette d'un coup tous "
                      "les anciens fichiers sans provenance avec la nouvelle source ; avant de changer, poser "
                      "`health_source` sur l'historique (skill `arc-backfill`).",
    "no_cross_source": "Aucune comparaison inter-sources : lignes de base HRV/FC de repos, effets de décision et "
                       "bande personnelle du tableau de bord ne portent que sur UNE source effective (pour "
                       "`openwearables`, un seul fabricant). La ligne de base ne porte que sur les nuits de la "
                       "source courante (« en_construction » tant que les seuils habituels de "
                       "`arc_metrics.hrv_baseline_series` ne sont pas atteints) ; revenir à une source précédente "
                       "réutilise ses anciennes nuits.",
    "measurement_rows": "Seule une ligne portant une mesure (HRV, FC de repos, sommeil ou readiness) définit une "
                        "source : un fichier santé sans mesure (douleur seule via /log ou Telegram) n'a pas de clé "
                        "de source et ne déclenche jamais un « changement de source ».",
    "sleep_debt_pooled": "La dette de sommeil (`sleep_total_s`) reste calculée sur toutes les sources confondues : "
                         "elle n'est pas séparée par source (approximation du projet).",
    "hrv_methods": "`hrv_overnight_ms` est un RMSSD nocturne quelle que soit la source ; la HRV en SDNN (Apple "
                   "Health) va dans `hrv_sdnn_ms`, jamais dans `hrv_overnight_ms`, et n'entre dans aucune ligne de base.",
    "native_scores": "Un score natif d'un fabricant (`provider_scores`) garde son nom, son échelle et son fabricant : "
                     "jamais remis sur 100, jamais présenté comme le Training Readiness Garmin.",
}


def _warn(message: str) -> None:
    print(f"avertissement : {message}", file=sys.stderr)


def data_source(config: Dict[str, dict]) -> str:
    """`[data].source` normalisé (garmin par défaut) ; inconnu → défaut, sans exception."""
    raw = (config.get("data") or {}).get("source")
    value = str(raw).strip().lower() if isinstance(raw, str) else ""
    return value if value in DATA_SOURCES else DEFAULT_DATA_SOURCE


def openwearables_section(config: Dict[str, dict]) -> dict:
    """`[health.openwearables]` : `tomllib` l'imbrique dans `health`, le repli TOML < 3.11
    (`coach_config._read_toml_fallback`) en fait une section plate `"health.openwearables"` — les deux
    formes sont lues. Rend toujours un dict (vide si absente)."""
    nested = (config.get("health") or {}).get("openwearables")
    flat = config.get("health.openwearables")
    merged: Dict[str, object] = {}
    for part in (flat, nested):
        if isinstance(part, dict):
            merged.update(part)
    return merged


def effective_health_source(config: Dict[str, dict], warn: bool = True) -> Tuple[str, str]:
    """Résout `[health].source` en `(source, provider)`, jamais en levant.

    Absent, vide, `"primary"` ou invalide → `("primary", "")`. `"openwearables"` → `("openwearables",
    provider)` où `provider` est `[health.openwearables].provider` (vide si non renseigné : la configuration
    est alors incomplète, avertissement « configuration incomplète »). Un fournisseur refusé (`garmin`,
    `strava`) replie sur `("primary", "")` avec avertissement : la donnée Garmin passe en direct. Un fournisseur
    INCONNU (faute de frappe) reste sur `("openwearables", "")` avec avertissement, jamais un repli silencieux."""
    health = config.get("health") or {}
    raw = health.get("source")
    if raw in (None, ""):
        return DEFAULT_SOURCE, ""
    if not isinstance(raw, str) or raw.strip().lower() not in SOURCES:
        if warn:
            _warn(f"[health].source = {raw!r} hors de {SOURCES} — traité comme « {DEFAULT_SOURCE} » "
                  "(santé lue depuis [data].source).")
        return DEFAULT_SOURCE, ""
    source = raw.strip().lower()
    if source == DEFAULT_SOURCE:
        return DEFAULT_SOURCE, ""
    ow = openwearables_section(config)
    provider_raw = ow.get("provider")
    provider = provider_raw.strip().lower() if isinstance(provider_raw, str) else ""
    if provider in REFUSED_PROVIDERS:
        if warn:
            why = ("la donnée Garmin passe en direct, jamais par Open Wearables" if provider == "garmin"
                   else "Strava n'a aucune donnée de santé")
            _warn(f"[health.openwearables].provider = {provider!r} refusé ({why}) — "
                  f"[health].source traité comme « {DEFAULT_SOURCE} ».")
        return DEFAULT_SOURCE, ""
    if provider and provider not in PROVIDERS:
        # Faute de frappe probable : l'athlète a demandé Open Wearables, on n'y renonce pas en silence —
        # on reste sur `openwearables` sans fabricant et on le dit (jamais de repli sur Garmin).
        if warn:
            _warn(f"[health.openwearables].provider = {provider_raw!r} hors de {PROVIDERS} — configuration "
                  "incomplète, [health].source reste « openwearables » sans fabricant.")
        return source, ""
    if not provider and warn:
        _warn("configuration incomplète : [health.openwearables].provider vide.")
    return source, provider


# Colonnes dont au moins une non nulle fait d'une ligne santé une ligne « avec mesure » (#218).
MEASUREMENT_FIELDS = ("hrv_overnight_ms", "hrv_sdnn_ms", "resting_hr_bpm", "sleep_total_s", "readiness_score")


def has_measurement(row) -> bool:
    """Vrai si la ligne santé (dict ou `sqlite3.Row`) porte une mesure ; une colonne absente compte pour nulle."""
    for field in MEASUREMENT_FIELDS:
        try:
            if row[field] is not None:
                return True
        except (KeyError, IndexError):
            continue
    return False


def row_key(row, default_data_source: str) -> Optional[str]:
    """Clé de source d'une ligne santé, ou `None` si elle ne porte aucune mesure (douleur seule…)."""
    if not has_measurement(row):
        return None
    return source_key(row["health_source"], row["health_provider"], default_data_source)


def current_key(rows, today_iso: str, default_data_source: str) -> Optional[str]:
    """Clé de la dernière ligne AVEC mesure datée au plus de `today_iso` (les lignes sont triées par date
    croissante ou non : on prend la plus récente). `None` si aucune."""
    best_date, best = "", None
    for row in rows:
        key = row_key(row, default_data_source)
        if key is not None and best_date <= row["date"] <= today_iso:
            best_date, best = row["date"], key
    return best


def source_key(health_source: Optional[str], health_provider: Optional[str], default_data_source: str) -> str:
    """Clé de source EFFECTIVE d'une ligne santé : `health_source` (sinon `[data].source` configuré) ;
    `openwearables/<fabricant>` pour Open Wearables. Deux lignes se comparent seulement à clé égale."""
    source = (health_source or "").strip().lower() or default_data_source or DEFAULT_DATA_SOURCE
    if source == "openwearables":
        return "openwearables/" + ((health_provider or "").strip().lower() or "inconnu")
    return source


def split_key(key: str) -> Tuple[str, Optional[str]]:
    """Inverse de `source_key` : `(source, fabricant ou None)`."""
    if key.startswith("openwearables/"):
        provider = key.split("/", 1)[1]
        return "openwearables", (None if provider == "inconnu" else provider)
    return key, None


def label(key: str) -> str:
    """Libellé lisible d'une clé de source (ligne « Source : … » du tableau de bord)."""
    source, provider = split_key(key)
    if source == "openwearables":
        return "Open Wearables" + (f" ({provider})" if provider else "")
    # Strava n'a aucune donnée de santé : jamais « Strava » comme source santé.
    return {"garmin": "Garmin", "intervals": "intervals.icu", "strava": "source principale"}.get(source, source)
