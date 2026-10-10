#!/usr/bin/env python3
"""Client REST Open Wearables (OW) : santé du jour et état des connexions (#219, épopée #216).

Stdlib seule (`urllib`), LECTURE SEULE : aucun appel d'écriture chez OW, aucun fichier écrit dans le
workspace (c'est l'agent qui persiste). Le serveur MCP d'OW ne suffit pas au bilan matinal (sommeil réduit
à la durée, aucun score, séries brutes volumineuses) : on lit l'API REST, comme `download_fit.py` contourne
un MCP inadapté. La sortie est du JSON déterministe, le modèle n'a rien à calculer.

    python3 scripts/arc_openwearables.py check [--json] [--timeout S]
    python3 scripts/arc_openwearables.py health-day [--date AAAA-MM-JJ] [--json] [--timeout S]
    (option commune : --workspace DIR ; `--timeout S` = délai d'UNE requête, défaut 10 s, ou $ARC_OW_TIMEOUT)

Codes de sortie : 0 = appel réussi (même si des mesures manquent) ; 2 = configuration incomplète ou
invalide (y compris fournisseur absent : le client REFUSE de lire sans fournisseur) ; 3 = OW injoignable,
clé refusée ou réponse inexploitable. Jamais de traceback. Un délai dépassé n'est jamais rejoué (seule une
erreur de connexion immédiate l'est, une fois) : l'attente maximale d'une commande qui échoue sur un délai
est donc ≈ `--timeout` (le diagnostic de #220 passe 3 s).

Version vérifiée : OW `0.9.0` = commit `ff8527a52ad8a96cd1ebe8c19344295c934ae9dc` (dernier tag publié à la
date de rédaction ; `OW_TAG`/`OW_REF`/`TESTED_VERSION` ci-dessous). Tous les endpoints, paramètres, en-têtes
et champs cités ont été relus dans les sources à ce commit (`backend/app/...`). OW n'expose pas sa version
(`FastAPI(title=…)` sans `version`, `backend/app/main.py`) : la compatibilité se juge à la forme de la
réponse sommeil (`shape_ok`).

Authentification : en-tête `X-Open-Wearables-API-Key: <clé>` (`backend/app/services/api_key_service.py`,
alias `Header`). La clé est lue dans un fichier hors dépôt (`[health.openwearables].api_key_file`, surcharge
`ARC_OW_API_KEY_FILE`), JAMAIS affichée, jamais dans l'URL, jamais dans argv, jamais dans un message d'erreur.
Les redirections HTTP sont refusées (un en-tête d'authentification ne doit pas suivre une redirection).

Configuration : `[health].source = "openwearables"` + `[health.openwearables]` (`base_url`, `provider`,
`user_id`, `api_key_file`, `stale_after_h`), résolus par `arc_health_source.effective_health_source` (#218).
Surcharges pour les tests : `ARC_OW_BASE_URL`, `ARC_OW_API_KEY_FILE`.

Appels (préfixe `/api/v1`), dans cet ordre :
1. `GET /users?limit=100[&search=<uuid>]` → `{items:[UserRead], total, page, limit}`
   (`api/routes/v1/users.py`, `OldPaginatedResponse` ; `search` UUID = correspondance exacte de l'id ;
   `limit` ≤ 100). Champs lus : `items[].id`, `total`. Aucun nom ni courriel n'est jamais restitué.
2. `GET /users/{user_id}/connections` → liste de `UserConnectionWithCapabilities`
   (`api/routes/v1/connections.py`). Champs lus : `provider`, `status` (`active|revoked|expired`,
   `schemas/auth/connection_status.py`), `last_synced_at`.
3. `GET /users/{user_id}/summaries/sleep?start_date=&end_date=&limit=` → `{data:[SleepSummary], pagination,
   metadata}` (`api/routes/v1/summaries.py`, `schemas/responses/activity/summaries.py`). Champs lus : `date`,
   `source.provider`, `source.device_name`/`source.device`, `start_time`, `end_time`, `zone_offset`,
   `duration_minutes`, `stages.{deep,light,rem,awake}_minutes`, `avg_hrv_rmssd_ms`, `avg_hrv_sdnn_ms`.
4. `GET /users/{user_id}/timeseries?start_time=&end_time=&types=…&provider=&resolution=raw&limit=1000[&cursor=]`
   → `{data:[TimeSeriesSample], pagination.next_cursor}` (`api/routes/v1/timeseries.py`, `types` = paramètre
   liste FastAPI, répété ; `Resolution.RAW = "raw"`, `SeriesType.resting_heart_rate` /
   `heart_rate_variability_rmssd`). Champs lus : `timestamp`, `zone_offset`, `type`, `value`.
5. `GET /users/{user_id}/health-scores?start_date=&end_date=&provider=&limit=&offset=` → `{data:
   [HealthScoreResponse], pagination.has_more}` (`api/routes/v1/health_scores.py`). Champs lus : `category`,
   `value`, `qualifier`, `recorded_at`, `zone_offset`, `provider`. Remplace `/summaries/recovery` (jamais
   appelé : au tag 0.9.0 il ne renvoie que WHOOP, « This is a bug », et `recovery_score` est déprécié).

Bornes : `start_date`/`end_date` acceptent une date seule (toute la journée, bornes incluses,
`utils/dates.py`) ; on élargit à D−1…D+1 et on filtre côté client, ce qui rend le script indépendant des
conventions de fuseau du serveur. `limit` maximal : 1000 (`MAX_PAGE_SIZE`, `utils/pagination.py`) ; les
utilisateurs sont plafonnés à 100 par page.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import ipaddress
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Version d'Open Wearables contre laquelle ce client a été vérifié (lue par le test de lint et par la doc).
OW_TAG = "0.9.0"
OW_REF = "ff8527a52ad8a96cd1ebe8c19344295c934ae9dc"
TESTED_VERSION = OW_TAG

API_PREFIX = "/api/v1"
API_KEY_HEADER = "X-Open-Wearables-API-Key"
TIMEOUT_S = 10            # délai par défaut d'UNE requête (secondes), surchargé par --timeout / ARC_OW_TIMEOUT
MAX_TIMEOUT_S = 120
RHR_LEAD = timedelta(minutes=5)       # marge avant le début de la nuit (voir ASSUMPTIONS["resting_hr"])
SCORE_MARGIN = timedelta(hours=1)     # marge autour de la nuit pour un score de sommeil (idem « score_date »)
MAX_BODY_BYTES = 8 * 1024 * 1024
PAGE_LIMIT = 1000
USERS_LIMIT = 100
MAX_PAGES = 10
DEFAULT_STALE_AFTER_H = 36.0
# Fournisseurs « SDK » (application mobile OW) : leur présence dans la liste des connexions n'a pas été
# vérifiée sur une instance ; absents de la liste, leur fraîcheur est dite inconnue.
SDK_PROVIDERS = ("apple", "health_connect", "samsung")

EXIT_OK, EXIT_CONFIG, EXIT_UNREACHABLE = 0, 2, 3

# Échelles NATIVES des scores de fabricant, recopiées de `backend/app/constants/health_scores.py`
# (`HEALTH_SCORE_RANGES`) au commit épinglé. `strain` volontairement absent (une charge, et la strain Polar
# n'a pas de borne haute) ; `internal` volontairement absent (scores calculés par OW, pas par le fabricant).
# Samsung (sommeil 0–100) n'existe que sur `main` après 0.9.0 : absent de cette table.
SCORE_RANGES: Dict[Tuple[str, str], Tuple[float, float]] = {
    ("sleep", "oura"): (1, 100),
    ("sleep", "garmin"): (1, 100),
    ("sleep", "whoop"): (0, 100),
    ("sleep", "polar"): (1, 100),
    ("readiness", "oura"): (1, 100),
    ("readiness", "polar"): (0, 10),
    ("recovery", "whoop"): (0, 100),
    ("recovery", "suunto"): (0, 100),
    ("recovery", "polar"): (1, 6),
}
SCORE_CATEGORIES = ("readiness", "recovery", "sleep")

ASSUMPTIONS = {
    "sleep_date": "OW rattache une nuit à la date LOCALE de réveil (`local_sleep_date = end_datetime + "
                  "zone_offset`, `repositories/event_record_repository.py` L397 et `services/summaries_service.py` L621, "
                  "vérifiés au commit épinglé) : la nuit du jour D est l'entrée dont `date == D`.",
    "single_source": "L'endpoint sommeil retient UNE source par date selon les priorités OW "
                     "(`_filter_by_priority`). Si `source.provider` diffère du fournisseur configuré, l'entrée "
                     "est ignorée (avertissement `provider_mismatch`) : une seule source santé par jour, "
                     "jamais un mélange de fabricants.",
    "resting_hr": "FC de repos = dernier échantillon `resting_heart_rate` du fournisseur tombé dans la nuit "
                  "principale [début − 5 min ; fin] : chez Oura, `lowest_heart_rate` est enregistrée au DÉBUT du "
                  "sommeil (`SLEEP_SCALAR_SERIES`, `providers/oura/coverage.py` ; `recorded_at=start_dt`, "
                  "`providers/oura/data_247.py` ~L850), donc la veille au soir pour un coucher avant minuit. Aucun "
                  "échantillon dans la nuit (ou nuit inconnue) : repli sur le dernier échantillon dont la date locale "
                  "(`timestamp` + `zone_offset`) est D. La sémantique varie selon le fabricant : les lignes de base "
                  "sont par source (#218), jamais comparées entre fabricants.",
    "hrv_fallback": "HRV RMSSD de secours (série temporelle) seulement si `avg_hrv_rmssd_ms` est absent : "
                    "moyenne des échantillons compris dans la fenêtre du sommeil principal, jamais au-delà "
                    "(une HRV diurne n'est pas une HRV nocturne). Sans fenêtre de sommeil connue : aucune.",
    "summary_hrv_sources": "`avg_hrv_rmssd_ms`/`avg_hrv_sdnn_ms` du résumé de sommeil sont la moyenne des "
                           "échantillons de TOUTES les sources de l'utilisateur dans la fenêtre de la nuit "
                           "(`repositories/event_record_repository.py` ~L716-741 : filtre `DataSource.user_id` "
                           "seul). Elles ne sont donc utilisées que si le fournisseur configuré est la SEULE "
                           "connexion de l'utilisateur (liste `/connections`). Sinon : RMSSD/SDNN recalculées "
                           "depuis la série temporelle filtrée par `provider` dans la fenêtre du sommeil, "
                           "avertissement `summary_hrv_multi_source`.",
    "score_scales": "Table `SCORE_RANGES` recopiée de `HEALTH_SCORE_RANGES` (OW 0.9.0). Couple (catégorie, "
                    "fournisseur) absent, ou valeur hors échelle : score écarté + avertissement, jamais une "
                    "échelle devinée ni un score remis sur 100.",
    "score_date": "OW ne documente aucune convention de jour pour `recorded_at` d'un score et AUCUN fournisseur ne "
                  "renseigne `zone_offset` d'un score (seule la strain WHOOP). Constaté dans les sources 0.9.0 : "
                  "score de SOMMEIL Polar/WHOOP = début de la nuit (`polar/data_247.py` ~L295, "
                  "`whoop/data_247.py`) ; Oura = `timestamp` d'Oura (minuit local) ou, à défaut, minuit UTC du "
                  "jour ; Nightly Recharge Polar (`recovery`) = `datetime.fromisoformat(date)` naïf, lu comme "
                  "minuit UTC. Règles (approximations du projet) : (1) `recorded_at` à exactement 00:00:00 UTC sans "
                  "`zone_offset` = date seule, on prend la date UTC ; (2) score de sommeil avec nuit connue : "
                  "`recorded_at` dans [début − 1 h ; fin + 1 h], ou minuit local du jour D (convention Oura) ; "
                  "(3) sinon date locale (`zone_offset` du score, à défaut celui de la nuit, à défaut le fuseau de la "
                  "machine) = D. Plusieurs scores de même catégorie : le plus récent.",
    "sdk_freshness": "Fournisseurs SDK (apple, health_connect, samsung) absents de la liste des connexions : "
                     "fraîcheur « inconnue », jamais devinée (non vérifié sur une instance).",
    "apple_hrv": "Apple Health ne fournit que la SDNN : toute valeur RMSSD qui serait renvoyée pour `apple` est "
                 "ignorée (le contrat interdit `hrv_overnight_ms` pour apple).",
    "check_shape": "`check` valide la forme des entrées de sommeil de la fenêtre D−1…D+1 (toutes, pas seulement "
                   "celle de D). Sans nuit dans la fenêtre, `shape_ok` ne juge que l'enveloppe de la réponse (clés "
                   "`data` et `pagination`) et le dit par un avertissement.",
    "timeout_retry": "`--timeout S` (ou `ARC_OW_TIMEOUT`) borne chaque requête. Une requête n'est rejouée UNE fois "
                     "que sur une erreur de connexion immédiate (refus, coupure) ; un DÉLAI dépassé n'est jamais "
                     "rejoué et interrompt la commande : la durée d'attente maximale est donc ≈ S secondes pour une "
                     "commande qui échoue sur un délai.",
    "transport": "Une `base_url` en `http://` vers un hôte ni local ni privé (hors boucle locale, RFC 1918, "
                 "`*.local`, `*.lan`, `*.internal`, noms sans point) envoie la clé en clair : avertissement "
                 "`insecure_transport`, sans blocage.",
}


class OWError(Exception):
    """Erreur propre (message français court, sans secret) ; `code` = code de sortie, `kind` = étiquette."""

    def __init__(self, code: int, kind: str, message: str, extra: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.kind = kind
        self.message = message
        self.extra = extra or {}


# ---------------------------------------------------------------------------------------------- configuration

def _config(workspace: Optional[str]) -> dict:
    """Configuration résolue (jamais d'exception brute). Rend un dict avec `source`, `provider`, `base_url`,
    `user_id`, `key_file`, `stale_after_h` ; lève OWError(2) si incomplète."""
    import arc_health_source as HS
    from coach_setup import workspace_root
    import arc_index

    try:
        conf = arc_index.load_config(workspace_root(workspace))
    except Exception:
        raise OWError(EXIT_CONFIG, "config", "Configuration illisible (config/workspace*.toml).")
    health = conf.get("health") if isinstance(conf.get("health"), dict) else {}
    raw_source = str(health.get("source") or "").strip().lower()
    raw_provider = HS.openwearables_section(conf).get("provider")
    raw_provider = raw_provider.strip().lower() if isinstance(raw_provider, str) else ""
    if raw_source == "openwearables" and raw_provider in HS.REFUSED_PROVIDERS:
        why = ("la donnée Garmin est lue en direct, jamais via Open Wearables" if raw_provider == "garmin"
               else "Strava n'a aucune donnée de santé")
        raise OWError(EXIT_CONFIG, "refused_provider",
                      f"Fournisseur « {raw_provider} » refusé ({why}) : choisir un autre fabricant dans "
                      "[health.openwearables].provider.")
    source, provider = HS.effective_health_source(conf)
    if source != "openwearables":
        raise OWError(EXIT_CONFIG, "not_enabled",
                      "Open Wearables n'est pas activé : [health].source doit valoir « openwearables ».")
    if not provider:
        raise OWError(EXIT_CONFIG, "no_provider",
                      "Aucun fournisseur santé valide : renseigner [health.openwearables].provider "
                      f"({', '.join(HS.PROVIDERS)}). Refus de lire sans fournisseur.")
    ow = HS.openwearables_section(conf)
    base_url = (os.environ.get("ARC_OW_BASE_URL") or str(ow.get("base_url") or "")).strip().rstrip("/")
    if not base_url:
        raise OWError(EXIT_CONFIG, "no_base_url", "[health.openwearables].base_url est vide.")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.query or parsed.fragment \
            or parsed.username or parsed.password:
        raise OWError(EXIT_CONFIG, "bad_base_url",
                      "[health.openwearables].base_url invalide (http(s)://hôte[:port], sans identifiants).")
    key_file = (os.environ.get("ARC_OW_API_KEY_FILE") or str(ow.get("api_key_file") or "")).strip()
    if not key_file:
        raise OWError(EXIT_CONFIG, "no_key_file", "[health.openwearables].api_key_file est vide.")
    user_id = str(ow.get("user_id") or "").strip()
    if user_id:
        try:
            user_id = str(uuid.UUID(user_id))
        except ValueError:
            raise OWError(EXIT_CONFIG, "bad_user_id", "[health.openwearables].user_id n'est pas un UUID.")
    stale = ow.get("stale_after_h", DEFAULT_STALE_AFTER_H)
    try:
        stale_after_h = float(stale)
        if isinstance(stale, bool) or not math.isfinite(stale_after_h) or stale_after_h <= 0:
            raise ValueError
    except (TypeError, ValueError):
        stale_after_h = DEFAULT_STALE_AFTER_H
    warnings: List[dict] = []
    if parsed.scheme == "http" and not _is_private_host(parsed.hostname):
        warnings.append(_warn("insecure_transport", "base_url en http:// vers un hôte non local : la clé d'API "
                              "circule en clair. Utiliser https:// (ou un hôte privé)."))
    return {"provider": provider, "base_url": base_url, "user_id": user_id, "key_file": key_file,
            "stale_after_h": stale_after_h, "warnings": warnings}


def _is_private_host(host: str) -> bool:
    """Vrai pour une boucle locale, une adresse privée ou un nom manifestement interne (approximation)."""
    host = (host or "").strip("[]").lower().rstrip(".")
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private or ip.is_link_local
    except ValueError:
        pass
    return host == "localhost" or "." not in host or host.endswith(
        (".localhost", ".local", ".lan", ".internal", ".home.arpa"))


def resolve_timeout(cli_value: Optional[float]) -> float:
    """Délai par requête : `--timeout` > `ARC_OW_TIMEOUT` > `TIMEOUT_S`. Lève OWError(2) si invalide."""
    raw = cli_value if cli_value is not None else os.environ.get("ARC_OW_TIMEOUT")
    if raw in (None, ""):
        return float(TIMEOUT_S)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = float("nan")
    if not math.isfinite(value) or not 0 < value <= MAX_TIMEOUT_S:
        raise OWError(EXIT_CONFIG, "bad_timeout", f"Délai invalide (attendu : nombre de secondes, "
                      f"0 < S ≤ {MAX_TIMEOUT_S}).")
    return value


def _read_key(key_file: str) -> Tuple[str, List[dict]]:
    """Lit la clé (jamais restituée). Rend (clé, avertissements)."""
    path = Path(key_file).expanduser()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raise OWError(EXIT_CONFIG, "key_unreadable", "Fichier de clé d'API introuvable ou illisible.")
    key = raw.strip()
    if not key or any(ch.isspace() or ord(ch) < 33 or ord(ch) > 126 for ch in key):
        raise OWError(EXIT_CONFIG, "key_invalid", "Fichier de clé d'API vide ou invalide.")
    warnings: List[dict] = []
    try:
        if path.stat().st_mode & 0o077:
            warnings.append(_warn("key_file_mode", "Le fichier de clé est lisible par d'autres comptes : "
                                  "le passer en mode 600."))
    except OSError:
        pass
    return key, warnings


def _warn(code: str, message: str) -> dict:
    return {"code": code, "message": message}


# --------------------------------------------------------------------------------------------------- réseau

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 — refuse toute redirection
        return None


class Client:
    """Appels GET authentifiés. La clé ne sort jamais de cet objet."""

    def __init__(self, base_url: str, key: str, opener=None, timeout: float = TIMEOUT_S):
        self._base = base_url
        self._key = key
        self._timeout = timeout
        self._opener = opener or urllib.request.build_opener(_NoRedirect)

    def get(self, path: str, params: Optional[list] = None):
        url = self._base + API_PREFIX + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        request = urllib.request.Request(url, method="GET", headers={
            API_KEY_HEADER: self._key, "Accept": "application/json"})
        for attempt in (0, 1):
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    body = response.read(MAX_BODY_BYTES + 1)
                break
            except urllib.error.HTTPError as err:
                status = err.code
                if status in (401, 403):
                    raise OWError(EXIT_UNREACHABLE, "auth", f"Clé d'API refusée par Open Wearables (HTTP {status}).")
                if 300 <= status < 400:
                    raise OWError(EXIT_UNREACHABLE, "redirect", "Open Wearables a répondu par une redirection "
                                  "(refusée) : vérifier base_url.")
                raise OWError(EXIT_UNREACHABLE, "http", f"Open Wearables a répondu HTTP {status}.",
                              {"http_status": status})
            except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as err:
                if _is_timeout(err):      # un délai n'est jamais rejoué : l'attente reste bornée par --timeout
                    raise OWError(EXIT_UNREACHABLE, "unreachable",
                                  f"Open Wearables ne répond pas (délai de {self._timeout:g} s dépassé).")
                if attempt == 0:
                    continue
                raise OWError(EXIT_UNREACHABLE, "unreachable", "Open Wearables injoignable (connexion refusée "
                              "ou coupée).")
            except Exception:
                raise OWError(EXIT_UNREACHABLE, "unreachable", "Open Wearables injoignable (réponse invalide).")
        if len(body) > MAX_BODY_BYTES:
            raise OWError(EXIT_UNREACHABLE, "bad_response", "Réponse d'Open Wearables trop volumineuse.")
        try:
            return json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise OWError(EXIT_UNREACHABLE, "bad_response", "Réponse d'Open Wearables illisible (JSON invalide).")


def _is_timeout(err: BaseException) -> bool:
    if isinstance(err, socket.timeout):
        return True
    return isinstance(err, urllib.error.URLError) and isinstance(err.reason, socket.timeout)


def _expect(value, kind, what: str):
    if not isinstance(value, kind):
        raise OWError(EXIT_UNREACHABLE, "bad_response", f"Réponse d'Open Wearables inattendue ({what}).")
    return value


# ----------------------------------------------------------------------------------------------- utilitaires

def parse_dt(raw) -> Optional[datetime]:
    """ISO 8601 tolérant (suffixe Z, fractions de longueur quelconque) ; `None` si illisible."""
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d+)", lambda m: (m.group(1) + "000000")[:7], text, count=1)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def offset_tz(zone_offset) -> Optional[timezone]:
    """`"+02:00"` → fuseau fixe ; `None` si absent ou illisible."""
    if not isinstance(zone_offset, str):
        return None
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", zone_offset.strip())
    if not m:
        return None
    delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
    return timezone(delta if m.group(1) == "+" else -delta)


def localize(raw, zone_offset, default_tz: Optional[timezone] = None) -> Optional[datetime]:
    """Instant en heure locale de l'appareil : `zone_offset` du résumé si connu, sinon `default_tz`."""
    moment = parse_dt(raw)
    if moment is None:
        return None
    tz = offset_tz(zone_offset) or default_tz
    if moment.tzinfo is None:
        return moment.replace(tzinfo=tz) if tz else moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz) if tz else moment


def local_date(raw, zone_offset, default_tz: Optional[timezone] = None) -> Optional[date]:
    moment = localize(raw, zone_offset, default_tz)
    return moment.date() if moment else None


def _num(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _minutes_to_s(value) -> Optional[int]:
    n = _num(value)
    return int(round(n * 60)) if n is not None and n >= 0 else None


def _round(value: float):
    return int(value) if float(value).is_integer() else round(value, 2)


# ------------------------------------------------------------------------------------------------ étapes OW

def resolve_user(client: Client, configured_id: str) -> Tuple[str, int]:
    """Étape 1. Rend (user_id, nombre d'utilisateurs). Lève OWError(2) si ambigu ou introuvable."""
    params = [("limit", USERS_LIMIT)]
    if configured_id:
        params.append(("search", configured_id))
    payload = _expect(client.get("/users", params), dict, "utilisateurs")
    items = _expect(payload.get("items"), list, "utilisateurs.items")
    total = payload.get("total")
    count = total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else len(items)
    ids = [str(i.get("id")) for i in items if isinstance(i, dict) and i.get("id")]
    if configured_id:
        if configured_id.lower() in (i.lower() for i in ids):
            return configured_id, count
        raise OWError(EXIT_CONFIG, "user_not_found",
                      "[health.openwearables].user_id ne figure pas parmi les utilisateurs de cette clé d'API.",
                      {"user_count": count})
    if count != 1 or len(ids) != 1:
        kind = "ambiguous_user" if count > 1 else "no_user"
        message = (f"{count} utilisateurs visibles : renseigner [health.openwearables].user_id."
                   if count > 1 else "Aucun utilisateur visible par cette clé d'API.")
        raise OWError(EXIT_CONFIG, kind, message, {"user_count": count})
    try:
        return str(uuid.UUID(ids[0])), 1
    except ValueError:
        raise OWError(EXIT_UNREACHABLE, "bad_response", "Identifiant d'utilisateur inattendu.")


def fetch_connection(client: Client, user_id: str, provider: str, stale_after_h: float,
                     now: datetime) -> Tuple[dict, List[dict], bool]:
    """Étape 2. Rend (fraîcheur, avertissements, source_unique). `freshness.status` : active | revoked |
    expired | absent | unknown (fournisseur SDK absent de la liste). `source_unique` : toutes les connexions
    listées appartiennent au fournisseur configuré (condition d'usage de la HRV du résumé de sommeil)."""
    payload = _expect(client.get(f"/users/{user_id}/connections"), list, "connexions")
    mine = [c for c in payload if isinstance(c, dict) and str(c.get("provider", "")).lower() == provider]
    warnings: List[dict] = []
    sole = all(isinstance(c, dict) and str(c.get("provider", "")).lower() == provider for c in payload)
    fresh = {"provider": provider, "status": "absent", "last_synced_at": None, "stale": None}
    if not mine:
        if provider in SDK_PROVIDERS:
            fresh["status"] = "unknown"
            warnings.append(_warn("freshness_unknown", f"Fraîcheur de {provider} inconnue : fournisseur SDK "
                                  "absent de la liste des connexions."))
        else:
            warnings.append(_warn("not_connected", f"{provider} n'est pas connecté dans Open Wearables."))
        return fresh, warnings, sole
    mine.sort(key=lambda c: (c.get("status") == "active", str(c.get("last_synced_at") or "")), reverse=True)
    conn = mine[0]
    status = str(conn.get("status") or "").lower()
    fresh["status"] = status if status in ("active", "revoked", "expired") else "unknown"
    synced = parse_dt(conn.get("last_synced_at"))
    if synced is not None:
        fresh["last_synced_at"] = conn.get("last_synced_at")
        if synced.tzinfo is None:
            synced = synced.replace(tzinfo=timezone.utc)
    if fresh["status"] != "active":
        warnings.append(_warn("not_active", f"Connexion {provider} « {fresh['status']} » : reconnecter le "
                              "fournisseur dans le portail Open Wearables."))
        return fresh, warnings, sole
    if synced is None and provider in SDK_PROVIDERS:
        warnings.append(_warn("freshness_unknown", f"Fraîcheur de {provider} inconnue : fournisseur SDK sans "
                              "date de dernière synchronisation."))
    elif synced is None:
        fresh["stale"] = True
        warnings.append(_warn("stale", f"{provider} n'a encore jamais synchronisé : données périmées."))
    else:
        fresh["stale"] = (now - synced) > timedelta(hours=stale_after_h)
        if fresh["stale"]:
            hours = int((now - synced).total_seconds() // 3600)
            warnings.append(_warn("stale", f"Dernière synchronisation de {provider} il y a {hours} h "
                                  f"(seuil {stale_after_h:g} h) : données périmées."))
    return fresh, warnings, sole


def _window(day: date) -> List[Tuple[str, str]]:
    return [("start_date", (day - timedelta(days=1)).isoformat()), ("end_date", (day + timedelta(days=1)).isoformat())]


def fetch_sleep(client: Client, user_id: str, day: date) -> List[dict]:
    """Étape 3 : résumés de sommeil de la fenêtre D−1…D+1 (toutes pages, plafonnées)."""
    out: List[dict] = []
    cursor = None
    for _ in range(MAX_PAGES):
        params = _window(day) + [("limit", 50)] + ([("cursor", cursor)] if cursor else [])
        payload = _expect(client.get(f"/users/{user_id}/summaries/sleep", params), dict, "sommeil")
        out.extend(i for i in _expect(payload.get("data"), list, "sommeil.data") if isinstance(i, dict))
        pagination = payload.get("pagination")
        cursor = pagination.get("next_cursor") if isinstance(pagination, dict) else None
        if not cursor:
            break
    return out


def sleep_shape_ok(entries: List[dict]) -> bool:
    keys = {"date", "source", "duration_minutes", "avg_hrv_rmssd_ms", "avg_hrv_sdnn_ms", "stages"}
    return all(keys <= set(e) and isinstance(e.get("source"), dict) and "provider" in e["source"] for e in entries)


def pick_sleep(entries: List[dict], day: date, provider: str) -> Tuple[Optional[dict], List[dict]]:
    """Garde l'entrée `date == D` du fournisseur configuré. Rend (entrée, avertissements)."""
    same_day = [e for e in entries if e.get("date") == day.isoformat()]
    mine = [e for e in same_day if str((e.get("source") or {}).get("provider", "")).lower() == provider]
    warnings: List[dict] = []
    other = [e for e in same_day if e not in mine]
    if other:
        seen = sorted({str((e.get("source") or {}).get("provider", "?")).lower() for e in other})
        warnings.append(_warn("provider_mismatch", f"Le sommeil du {day.isoformat()} vient de {', '.join(seen)}, "
                              f"pas de {provider} : ignoré. Régler les priorités de sources dans le portail "
                              "Open Wearables (une seule source santé par jour)."))
    return (mine[0] if mine else None), warnings


def fetch_timeseries(client: Client, user_id: str, provider: str, start: datetime, end: datetime,
                     types: List[str]) -> Tuple[List[dict], bool]:
    """Étape 4. Rend (échantillons, tronqué)."""
    out: List[dict] = []
    cursor = None
    for _ in range(MAX_PAGES):
        params: list = [("start_time", start.isoformat()), ("end_time", end.isoformat())]
        params += [("types", t) for t in types]
        params += [("provider", provider), ("resolution", "raw"), ("limit", PAGE_LIMIT)]
        if cursor:
            params.append(("cursor", cursor))
        payload = _expect(client.get(f"/users/{user_id}/timeseries", params), dict, "séries temporelles")
        out.extend(s for s in _expect(payload.get("data"), list, "séries.data") if isinstance(s, dict))
        pagination = payload.get("pagination")
        cursor = pagination.get("next_cursor") if isinstance(pagination, dict) else None
        if not cursor:
            return out, False
    return out, True


def fetch_scores(client: Client, user_id: str, provider: str, day: date) -> List[dict]:
    """Étape 5 : scores de la fenêtre D−1…D+1 pour le fournisseur (pagination par `offset`)."""
    out: List[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        params = _window(day) + [("provider", provider), ("limit", 100), ("offset", offset)]
        payload = _expect(client.get(f"/users/{user_id}/health-scores", params), dict, "scores")
        data = [s for s in _expect(payload.get("data"), list, "scores.data") if isinstance(s, dict)]
        out.extend(data)
        pagination = payload.get("pagination")
        if not (isinstance(pagination, dict) and pagination.get("has_more") is True and data):
            break
        offset += len(data)
    return out


def score_belongs_to_day(category: str, score: dict, day: date, default_tz,
                         window: Optional[Tuple[datetime, datetime]]) -> bool:
    """Un score est-il celui du jour D ? Règles et sources : `ASSUMPTIONS["score_date"]`."""
    moment = parse_dt(score.get("recorded_at"))
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    utc = moment.astimezone(timezone.utc)
    if not score.get("zone_offset") and utc.time() == datetime.min.time():
        return utc.date() == day          # date seule (minuit UTC sans fuseau) : la date UTC EST le jour
    local = localize(score.get("recorded_at"), score.get("zone_offset"), default_tz)
    if local is None:
        return False
    if category == "sleep" and window is not None:
        if window[0] - SCORE_MARGIN <= local <= window[1] + SCORE_MARGIN:
            return True
        return local.date() == day and local.time() == datetime.min.time()     # minuit local (Oura)
    return local.date() == day


def native_scores(raw: List[dict], day: date, provider: str, default_tz,
                  window: Optional[Tuple[datetime, datetime]] = None) -> Tuple[List[dict], List[dict]]:
    """Scores natifs du jour D, sur leur échelle d'origine. Rend (provider_scores, avertissements)."""
    latest: Dict[str, Tuple[datetime, dict]] = {}
    warnings: List[dict] = []
    for score in raw:
        category = str(score.get("category") or "").lower()
        origin = str(score.get("provider") or "").lower()
        if category not in SCORE_CATEGORIES or origin == "internal":
            continue          # strain/activité/etc. et scores calculés par OW : hors périmètre
        if origin and origin != provider:
            continue
        if not score_belongs_to_day(category, score, day, default_tz, window):
            continue
        value = _num(score.get("value"))
        if value is None:
            continue
        bounds = SCORE_RANGES.get((category, provider))
        if bounds is None:
            warnings.append(_warn("unknown_score_scale", f"Score {category} de {provider} écarté : échelle "
                                  "inconnue de ce client (jamais devinée)."))
            continue
        if not bounds[0] <= value <= bounds[1]:
            warnings.append(_warn("score_out_of_range", f"Score {category} de {provider} écarté : {value:g} "
                                  f"hors de l'échelle {bounds[0]:g}-{bounds[1]:g}."))
            continue
        moment = parse_dt(score.get("recorded_at")) or datetime.min.replace(tzinfo=timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if category not in latest or moment >= latest[category][0]:
            entry = {"category": category, "value": _round(value), "scale_min": _round(bounds[0]),
                     "scale_max": _round(bounds[1]), "provider": provider}
            if isinstance(score.get("qualifier"), str) and score["qualifier"].strip():
                entry["qualifier"] = score["qualifier"].strip()
            latest[category] = (moment, entry)
    ordered = [latest[c][1] for c in SCORE_CATEGORIES if c in latest]
    return ordered, warnings


# ------------------------------------------------------------------------------------------------ health-day

def build_health_day(client: Client, cfg: dict, user_id: str, fresh: dict, day: date,
                     sole_source: bool = True) -> dict:
    provider = cfg["provider"]
    local_tz = datetime.now().astimezone().tzinfo
    warnings: List[dict] = []
    arc: Dict[str, object] = {"health_source": "openwearables", "health_provider": provider}
    unavailable: Dict[str, str] = {}
    result = {"ok": True, "date": day.isoformat(), "arc": arc, "unavailable": unavailable,
              "warnings": warnings, "freshness": fresh}
    if fresh["status"] in ("revoked", "expired", "absent"):
        why = (f"connexion {provider} {fresh['status']}" if fresh["status"] != "absent"
               else f"{provider} n'est pas connecté dans Open Wearables")
        for key in ("hrv_overnight_ms", "resting_hr_bpm", "readiness"):
            unavailable[key] = f"{why} : aucune donnée lue"
        return result

    entries = fetch_sleep(client, user_id, day)
    sleep, mismatch = pick_sleep(entries, day, provider)
    warnings.extend(mismatch)
    device = None
    sleep_tz = None
    window: Optional[Tuple[datetime, datetime]] = None
    rmssd = sdnn = None
    if sleep:
        source = sleep.get("source") if isinstance(sleep.get("source"), dict) else {}
        device = source.get("device_name") or source.get("device")
        sleep_tz = offset_tz(sleep.get("zone_offset"))
        total = _minutes_to_s(sleep.get("duration_minutes"))
        if total:
            arc["sleep_total_s"] = total
        stages = sleep.get("stages") if isinstance(sleep.get("stages"), dict) else {}
        for key, field in (("sleep_deep_s", "deep_minutes"), ("sleep_light_s", "light_minutes"),
                           ("sleep_rem_s", "rem_minutes"), ("sleep_awake_s", "awake_minutes")):
            seconds = _minutes_to_s(stages.get(field))
            if seconds is not None:
                arc[key] = seconds
        start = localize(sleep.get("start_time"), sleep.get("zone_offset"), local_tz)
        end = localize(sleep.get("end_time"), sleep.get("zone_offset"), local_tz)
        if start and end and start < end:
            arc["sleep_start"], arc["sleep_end"] = start.isoformat(), end.isoformat()
            window = (start, end)
        rmssd, sdnn = _num(sleep.get("avg_hrv_rmssd_ms")), _num(sleep.get("avg_hrv_sdnn_ms"))
        rmssd = rmssd if rmssd and rmssd > 0 else None
        sdnn = sdnn if sdnn and sdnn > 0 else None
        if not sole_source:
            if rmssd is not None or sdnn is not None:
                warnings.append(_warn("summary_hrv_multi_source", "HRV du résumé de sommeil ignorée : OW la moyenne "
                                      "sur TOUTES les sources de l'utilisateur, et d'autres connexions que "
                                      f"{provider} existent. HRV recalculée depuis la série temporelle de "
                                      f"{provider} (fenêtre du sommeil)."))
            rmssd = sdnn = None
        if provider == "apple" and rmssd is not None:
            warnings.append(_warn("apple_rmssd_ignored", "RMSSD renvoyée pour apple : ignorée (Apple Health "
                                  "ne fournit que la SDNN)."))
            rmssd = None
        if rmssd is not None:
            arc["hrv_overnight_ms"] = _round(round(rmssd, 1))
        if sdnn is not None:
            arc["hrv_sdnn_ms"] = _round(round(sdnn, 1))

    # Étape 4 : FC de repos (et HRV de secours si le résumé n'en a pas) sur une fenêtre encadrant la nuit.
    anchor = datetime(day.year, day.month, day.day, tzinfo=sleep_tz or local_tz)
    win_start = min(window[0] - RHR_LEAD, anchor) if window else anchor - timedelta(hours=6)  # D−1 18:00 locale
    win_end = anchor + timedelta(hours=12)                                         # D 12:00 locale
    if window and window[1] > win_end:
        win_end = window[1]
    want_hrv_series = rmssd is None and provider != "apple" and window is not None
    want_sdnn_series = not sole_source and sdnn is None and window is not None
    types = ["resting_heart_rate"] + (["heart_rate_variability_rmssd"] if want_hrv_series else []) \
        + (["heart_rate_variability_sdnn"] if want_sdnn_series else [])
    samples, truncated = fetch_timeseries(client, user_id, provider, win_start, win_end, types)
    if truncated:
        warnings.append(_warn("timeseries_truncated", f"Séries temporelles tronquées après {MAX_PAGES} pages."))
    rhr_night, rhr_day, hrv_samples, sdnn_samples = [], [], [], []
    for s in samples:
        value = _num(s.get("value"))
        if value is None or value <= 0:
            continue
        moment = localize(s.get("timestamp"), s.get("zone_offset"), sleep_tz or local_tz)
        if moment is None:
            continue
        if s.get("type") == "resting_heart_rate":
            if window and window[0] - RHR_LEAD <= moment <= window[1]:
                rhr_night.append((moment, value, s))
            if moment.date() == day:
                rhr_day.append((moment, value, s))
        elif s.get("type") == "heart_rate_variability_rmssd" and window and window[0] <= moment <= window[1]:
            hrv_samples.append(value)
        elif s.get("type") == "heart_rate_variability_sdnn" and window and window[0] <= moment <= window[1]:
            sdnn_samples.append(value)
    rhr_samples = rhr_night or rhr_day     # la nuit principale d'abord ; sinon la date locale D
    if rhr_samples:
        rhr_samples.sort(key=lambda t: t[0])
        bpm = int(round(rhr_samples[-1][1]))
        if 20 <= bpm <= 250:
            arc["resting_hr_bpm"] = bpm
        else:
            warnings.append(_warn("rhr_out_of_range", f"FC de repos {bpm} bpm implausible : écartée."))
        if device is None:
            src = rhr_samples[-1][2].get("source")
            device = (src.get("device_name") or src.get("device")) if isinstance(src, dict) else None
    if rmssd is None and hrv_samples:
        arc["hrv_overnight_ms"] = _round(round(sum(hrv_samples) / len(hrv_samples), 1))
        warnings.append(_warn("hrv_from_timeseries", "HRV RMSSD recalculée depuis la série temporelle "
                              "(fenêtre du sommeil), faute de moyenne exploitable dans le résumé."))
    if want_sdnn_series and sdnn_samples:
        sdnn = sum(sdnn_samples) / len(sdnn_samples)
        arc["hrv_sdnn_ms"] = _round(round(sdnn, 1))

    # Étape 5 : scores natifs.
    scores, score_warnings = native_scores(fetch_scores(client, user_id, provider, day), day, provider,
                                           sleep_tz or local_tz, window)
    warnings.extend(score_warnings)
    if scores:
        arc["provider_scores"] = scores
    if device:
        arc["health_device"] = str(device)

    # Indisponibilités explicites (triptyque du bilan matinal complet).
    if "hrv_overnight_ms" not in arc:
        if provider == "apple":
            unavailable["hrv_overnight_ms"] = "Apple Health ne fournit que la SDNN (non comparable)"
        elif sdnn is not None:
            unavailable["hrv_overnight_ms"] = f"{provider} ne fournit que la SDNN (non comparable au RMSSD)"
        elif sleep is None:
            unavailable["hrv_overnight_ms"] = f"aucune nuit de {provider} synchronisée pour le {day.isoformat()}"
        else:
            unavailable["hrv_overnight_ms"] = f"aucune HRV nocturne chez {provider} pour le {day.isoformat()}"
    if "resting_hr_bpm" not in arc:
        unavailable["resting_hr_bpm"] = f"aucune FC de repos chez {provider} pour le {day.isoformat()}"
    if not any(s["category"] in ("readiness", "recovery") for s in scores):
        cats = sorted({c for (c, p) in SCORE_RANGES if p == provider and c in ("readiness", "recovery")})
        unavailable["readiness"] = (
            f"aucun score de readiness ni de recovery chez {provider}" if not cats else
            f"score {' / '.join(cats)} de {provider} indisponible pour le {day.isoformat()}")
    return result


# --------------------------------------------------------------------------------------------------- check

def run_check(client: Client, cfg: dict, now: datetime, day: date) -> dict:
    out = {"ok": False, "reachable": True, "auth": "ok", "user": {"resolved": False, "count": 0},
           "provider": cfg["provider"], "provider_connected": False, "stale": None, "shape_ok": False,
           "tested_version": TESTED_VERSION, "warnings": []}
    user_id, count = resolve_user(client, cfg["user_id"])
    out["user"] = {"resolved": True, "count": count}
    fresh, warnings, _ = fetch_connection(client, user_id, cfg["provider"], cfg["stale_after_h"], now)
    out["warnings"].extend(warnings)
    out["provider_connected"] = fresh["status"] == "active"
    out["stale"] = fresh["stale"]
    out["freshness"] = fresh
    payload = _expect(client.get(f"/users/{user_id}/summaries/sleep", _window(day) + [("limit", 50)]),
                      dict, "sommeil")
    data = _expect(payload.get("data"), list, "sommeil.data")
    entries = [e for e in data if isinstance(e, dict)]
    out["shape_ok"] = isinstance(payload.get("pagination"), dict) and len(entries) == len(data) \
        and sleep_shape_ok(entries)
    if out["shape_ok"] and not entries:
        out["warnings"].append(_warn("shape_unverified", "Forme des résumés de sommeil non vérifiée : aucune "
                                     "nuit dans la fenêtre (enveloppe seulement)."))
    if not out["shape_ok"]:
        out["warnings"].append(_warn("shape_mismatch", f"Réponse sommeil différente de la forme d'Open "
                                     f"Wearables {TESTED_VERSION} : version non testée ?"))
    out["ok"] = bool(out["provider_connected"] and out["shape_ok"] and fresh["stale"] is not True)
    return out


# ------------------------------------------------------------------------------------------------- sortie

def _human(result: dict, command: str) -> str:
    lines: List[str] = []
    if not result.get("ok", False) and "error" in result:
        return result["error"]["message"]
    if command == "check":
        lines.append(f"Open Wearables {result['tested_version']} (forme) — fournisseur {result['provider']}")
        lines.append(f"  accessible : {'oui' if result['reachable'] else 'non'} ; clé : {result['auth']}")
        lines.append(f"  utilisateur : {'résolu' if result['user']['resolved'] else 'non résolu'} "
                     f"({result['user']['count']} visible)")
        lines.append(f"  fournisseur connecté : {'oui' if result['provider_connected'] else 'non'} ; "
                     f"périmé : {result['stale']}")
        lines.append(f"  forme de la réponse : {'conforme' if result['shape_ok'] else 'inattendue'}")
    else:
        arc = result["arc"]
        lines.append(f"Santé du {result['date']} — {arc.get('health_provider')}"
                     + (f" ({arc['health_device']})" if arc.get("health_device") else ""))
        for key, label in (("sleep_total_s", "sommeil (s)"), ("hrv_overnight_ms", "HRV RMSSD (ms)"),
                           ("hrv_sdnn_ms", "HRV SDNN (ms)"), ("resting_hr_bpm", "FC de repos (bpm)")):
            if key in arc:
                lines.append(f"  {label} : {arc[key]}")
        for s in arc.get("provider_scores", []):
            lines.append(f"  score {s['category']} {s['provider']} : {s['value']} "
                         f"(échelle {s['scale_min']}-{s['scale_max']})")
        for key, why in result["unavailable"].items():
            lines.append(f"  indisponible — {key} : {why}")
    for w in result.get("warnings", []):
        lines.append(f"  avertissement [{w['code']}] : {w['message']}")
    return "\n".join(lines)


def _emit(result: dict, command: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=False))
    elif result.get("ok") or "error" not in result:
        print(_human(result, command))
    else:
        print(_human(result, command), file=sys.stderr)


def _date_arg(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("date attendue au format AAAA-MM-JJ")


_TIMEOUT_HELP = (f"Délai d'UNE requête, en secondes (défaut {TIMEOUT_S}, ou $ARC_OW_TIMEOUT). Un délai dépassé "
                 "interrompt la commande (code 3), sans nouvel essai.")


def _timeout_arg(raw: str) -> float:
    try:
        return resolve_timeout(float(raw))
    except (ValueError, OWError):
        raise argparse.ArgumentTypeError(f"nombre de secondes attendu (0 < S ≤ {MAX_TIMEOUT_S})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Client REST Open Wearables (lecture seule, #219).")
    parser.add_argument("--workspace", help="Workspace (sinon $ARC_WORKSPACE, pointeur, moteur).")
    parser.add_argument("--timeout", type=_timeout_arg, default=None, help=_TIMEOUT_HELP)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, helptext in (("check", "État de la connexion, de l'utilisateur et de la forme des réponses."),
                           ("health-day", "Santé d'un jour (sommeil, HRV, FC de repos, scores natifs).")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--json", action="store_true", help="Sortie JSON sur stdout.")
        p.add_argument("--timeout", type=_timeout_arg, default=argparse.SUPPRESS, help=_TIMEOUT_HELP)
        if name == "health-day":
            p.add_argument("--date", type=_date_arg, help="Jour local AAAA-MM-JJ (défaut : aujourd'hui).")
    return parser


def main(argv: Optional[list] = None, opener=None) -> int:
    args = build_parser().parse_args(argv)
    as_json = bool(args.json)
    day = getattr(args, "date", None) or datetime.now().astimezone().date()
    try:
        cfg = _config(args.workspace)
        key, key_warnings = _read_key(cfg["key_file"])
        key_warnings = cfg["warnings"] + key_warnings
        client = Client(cfg["base_url"], key, opener, resolve_timeout(getattr(args, "timeout", None)))
        if args.command == "check":
            result = run_check(client, cfg, datetime.now(timezone.utc), day)
            result["warnings"] = key_warnings + result["warnings"]
        else:
            user_id, _ = resolve_user(client, cfg["user_id"])
            fresh, conn_warnings, sole = fetch_connection(client, user_id, cfg["provider"], cfg["stale_after_h"],
                                                          datetime.now(timezone.utc))
            result = build_health_day(client, cfg, user_id, fresh, day, sole)
            result["warnings"] = key_warnings + conn_warnings + result["warnings"]
        _emit(result, args.command, as_json)
        return EXIT_OK
    except OWError as err:
        payload = {"ok": False, "error": {"code": err.kind, "message": err.message, **err.extra}}
        if err.kind == "auth":
            payload.update({"reachable": True, "auth": "refused"})
        elif err.kind in ("unreachable", "http", "bad_response", "redirect"):
            payload["reachable"] = err.kind != "unreachable"
        _emit(payload, args.command, as_json)
        return err.code
    except Exception:       # jamais de traceback ni de détail pouvant contenir un secret
        payload = {"ok": False, "error": {"code": "internal", "message": "Erreur interne du client Open Wearables."}}
        _emit(payload, args.command, as_json)
        return EXIT_UNREACHABLE


if __name__ == "__main__":
    sys.exit(main())
