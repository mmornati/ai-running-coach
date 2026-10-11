#!/usr/bin/env python3
"""Faux serveur HTTP Open Wearables (OW) pour le palier C (#221, épopée #216).

Contrairement à `stub_garmin_mcp.py` / `stub_intervals_mcp.py` (JSON-RPC sur stdin/stdout), OW est lu par
un client REST (`scripts/arc_openwearables.py`) : ce stub est donc un vrai serveur HTTP sur 127.0.0.1,
lancé par `runner.build_workspace` quand un cas déclare `[stub.openwearables.*]`. Le runner écrit
`[health.openwearables]` (adresse de ce serveur, fichier de clé en mode 600, fournisseur) dans la
configuration du workspace de test, de sorte que l'agent testé exécute le VRAI script client contre ce
faux serveur — rien d'autre n'est simulé.

Protocole de démarrage : le serveur écoute sur un port libre et imprime `PORT=<n>` (une ligne) sur la sortie
standard ; le runner lit cette ligne, puis arrête le processus à la fin du cas.

Endpoints servis (forme relue dans le client, lui-même vérifié au tag OW 0.9.0 — voir
`scripts/arc_openwearables.py`) et nom STABLE journalisé pour chacun dans `ARC_TOOL_LOG` via
`mcp_stub_common.log_call(log, "openwearables", <nom>, {paramètres})` — les assertions existantes
`tools_called`, `tools_not_called` et `tool_args_match` fonctionnent donc sans changement :

    GET /api/v1/users                          -> ow_users
    GET /api/v1/users/{id}/connections         -> ow_connections
    GET /api/v1/users/{id}/summaries/sleep     -> ow_sleep_summary
    GET /api/v1/users/{id}/timeseries          -> ow_timeseries
    GET /api/v1/users/{id}/health-scores       -> ow_health_scores
    GET /api/v1/users/{id}/summaries/recovery  -> ow_recovery_summary   (le client ne doit JAMAIS l'appeler :
                                                                          obsolète à OW 0.9.0, voir son docstring)

Données par défaut : celles d'une seule nuit pour la date LOCALE du jour (relative à l'exécution, jamais une
date figée), du fournisseur donné par `ARC_OW_STUB_PROVIDER` (`oura` par défaut, ou `apple`) :

* `oura` : HRV RMSSD, FC de repos, sommeil, scores natifs `readiness` 82/100 et `sleep` 77/100 (plus un score
  `internal` et une charge `whoop` que le client doit écarter), connexion active synchronisée il y a 1 h ;
* `apple` : HRV en SDNN seulement (52 ms), FC de repos, sommeil, aucun score, aucune connexion listée
  (fournisseur « SDK » : fraîcheur inconnue).

Scénarios par cas (même mécanique que les autres stubs) : `[stub.openwearables.<nom>]` avec `error = "401"`
(HTTP 401), `"timeout"` (le serveur attend puis coupe la connexion sans répondre ; le runner règle
`ARC_OW_TIMEOUT` pour que le client abandonne vite) ou `"empty"` (réponse bien formée mais vide : « pas de
nuit encore arrivée »), ou `file = "…json"` (réponse lue dans `fixtures/stub-responses/`, avec les jetons
`{{TODAY}}`, `{{TODAY-N}}`, `{{NOW-Nh}}` et `{{TZ}}` remplacés).

Clé d'API : l'en-tête `X-Open-Wearables-API-Key` doit valoir `ARC_OW_STUB_KEY`, sinon HTTP 401.
Bibliothèque standard uniquement.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent))      # racine du dépôt : `tests.lib.local_http`
import mcp_stub_common as common  # noqa: E402
from tests.lib.local_http import ThreadingHTTPServer  # noqa: E402

FIXTURES_DIR = HERE / "fixtures"
SERVER_NAME = "openwearables"
USER_ID = "00000000-0000-4000-8000-0000000000a1"
DEFAULT_PROVIDER = "oura"
KNOWN_PROVIDERS = ("oura", "apple")
DEFAULT_TIMEOUT_S = 8.0           # plus long que ARC_OW_TIMEOUT réglé par le runner : le client abandonne d'abord

# (nom journalisé, description) — consommé par `tests/evals/test_evals.py` pour valider les sections `[stub]`.
TOOLS = [
    ("ow_users", "GET /api/v1/users"),
    ("ow_connections", "GET /api/v1/users/{id}/connections"),
    ("ow_sleep_summary", "GET /api/v1/users/{id}/summaries/sleep"),
    ("ow_timeseries", "GET /api/v1/users/{id}/timeseries"),
    ("ow_health_scores", "GET /api/v1/users/{id}/health-scores"),
    ("ow_recovery_summary", "GET /api/v1/users/{id}/summaries/recovery"),
]

PAGINATION = {"next_cursor": None, "has_more": False}
DEVICES = {
    "oura": {"provider": "oura", "source": "oura", "device": "Oura Ring 4", "device_type": "ring",
             "device_name": "Oura Ring 4"},
    "apple": {"provider": "apple", "source": "apple", "device": "Apple Watch", "device_type": "watch",
              "device_name": "Apple Watch"},
}


def route(path: str):
    """Nom stable de l'endpoint demandé, ou None."""
    if path == "/api/v1/users":
        return "ow_users"
    match = re.fullmatch(r"/api/v1/users/[^/]+/(connections|summaries/sleep|summaries/recovery|timeseries|health-scores)", path)
    if not match:
        return None
    return {"connections": "ow_connections", "summaries/sleep": "ow_sleep_summary",
            "summaries/recovery": "ow_recovery_summary", "timeseries": "ow_timeseries",
            "health-scores": "ow_health_scores"}[match.group(1)]


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _offset(moment: datetime) -> str:
    raw = moment.strftime("%z") or "+0000"
    return f"{raw[:3]}:{raw[3:]}"


def canned(name: str, provider: str, now: datetime) -> object:
    """Réponse par défaut d'un endpoint pour la date locale du jour (`now` = maintenant, fuseau local)."""
    today = now.date()
    end = datetime(today.year, today.month, today.day, 6, 30, tzinfo=now.tzinfo)       # réveil local
    start = end - timedelta(hours=7, minutes=15)
    zone = _offset(end)
    device = DEVICES[provider]
    if name == "ow_users":
        return {"items": [{"id": USER_ID, "created_at": "2026-01-01T00:00:00Z", "first_name": "Prenom0",
                           "last_name": "Nom0", "email": "athlete0@example.invalid",
                           "has_active_connection": True}], "total": 1, "page": 1, "limit": 100}
    if name == "ow_connections":
        if provider == "apple":
            return []                    # fournisseur SDK : absent de la liste des connexions
        synced = _utc(now - timedelta(hours=1))
        return [{"id": "00000000-0000-4000-8000-0000000000d1", "user_id": USER_ID, "provider": provider,
                 "status": "active", "last_synced_at": synced, "created_at": "2026-01-01T00:00:00Z",
                 "updated_at": synced, "rest_pull": True}]
    if name == "ow_sleep_summary":
        stages = {"awake_minutes": 25, "light_minutes": 240, "deep_minutes": 90, "rem_minutes": 105}
        entry = {"date": today.isoformat(), "source": device, "start_time": _utc(start), "end_time": _utc(end),
                 "zone_offset": zone, "duration_minutes": 435, "total_duration_minutes": 435,
                 "time_in_bed_minutes": 460, "efficiency_percent": 90.0, "stages": stages,
                 "avg_hrv_sdnn_ms": 52.0 if provider == "apple" else None,
                 "avg_hrv_rmssd_ms": None if provider == "apple" else 48.2}
        return {"data": [entry], "pagination": {**PAGINATION, "total_count": 1},
                "metadata": {"resolution": "raw", "sample_count": 1}}
    if name == "ow_timeseries":
        sample = {"timestamp": _utc(start), "zone_offset": zone, "type": "resting_heart_rate",
                  "value": 52 if provider == "apple" else 47, "unit": "bpm", "source": device,
                  "is_daily_total": None}
        return {"data": [sample], "pagination": {**PAGINATION, "total_count": 1},
                "metadata": {"resolution": "raw", "sample_count": 1}}
    if name == "ow_health_scores":
        scores = []
        if provider == "oura":
            # Convention Oura constatée dans les sources OW : score daté de minuit LOCAL du jour de réveil.
            recorded = _utc(datetime(today.year, today.month, today.day, tzinfo=now.tzinfo))
            for ident, category, value, who in (("c1", "readiness", 82, "oura"), ("c2", "sleep", 77, "oura"),
                                                ("c3", "readiness", 70, "internal"), ("c4", "strain", 12, "whoop")):
                scores.append({"id": f"00000000-0000-4000-8000-0000000000{ident}", "category": category,
                               "value": value, "qualifier": None, "recorded_at": recorded, "zone_offset": None,
                               "components": None, "data_source_id": None, "provider": who,
                               "event_record_id": None})
        return {"data": scores, "pagination": {"has_more": False, "total_count": len(scores)}, "metadata": {}}
    return {"data": [], "pagination": {"has_more": False}}          # ow_recovery_summary : obsolète


def empty_like(name: str) -> object:
    if name == "ow_users":
        return {"items": [], "total": 0, "page": 1, "limit": 100}
    if name == "ow_connections":
        return []
    return {"data": [], "pagination": {**PAGINATION, "total_count": 0}, "metadata": {}}


def apply_placeholders(text: str, now: datetime) -> str:
    """`{{TODAY}}`, `{{TODAY-N}}` (jours), `{{NOW-Nh}}` (UTC) et `{{TZ}}` — mêmes dates relatives que les fixtures."""
    text = re.sub(r"\{\{TODAY-(\d+)\}\}", lambda m: (now.date() - timedelta(days=int(m.group(1)))).isoformat(), text)
    text = re.sub(r"\{\{NOW-(\d+)h\}\}", lambda m: _utc(now - timedelta(hours=int(m.group(1)))), text)
    return text.replace("{{TODAY}}", now.date().isoformat()).replace("{{TZ}}", _offset(now))


def resolve_file(override: dict, name: str, now: datetime) -> object:
    base = (FIXTURES_DIR / "stub-responses").resolve()
    candidate = (base / override["file"]).resolve()
    if base not in candidate.parents:
        raise ValueError(f"[stub.openwearables.{name}] file en dehors de stub-responses/ : {override['file']!r}")
    return json.loads(apply_placeholders(candidate.read_text(encoding="utf-8"), now))


def make_handler(overrides: dict, provider: str, key: str, log_path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, payload, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parts = urlsplit(self.path)
            name = route(parts.path)
            query = parse_qs(parts.query)
            if name is None:
                return self._send({"detail": "Not Found"}, 404)
            common.log_call(log_path, SERVER_NAME, name, {k: (v[0] if len(v) == 1 else v) for k, v in query.items()})
            if key and self.headers.get("X-Open-Wearables-API-Key") != key:
                return self._send({"detail": "Invalid or missing API key"}, 401)
            now = datetime.now().astimezone()
            override = overrides.get(name) or {}
            try:
                if "file" in override:
                    return self._send(resolve_file(override, name, now))
                error = str(override["error"]) if "error" in override else None
                if error == "401":
                    return self._send({"detail": "Invalid or missing API key"}, 401)
                if error == "empty":
                    return self._send(empty_like(name))
                if error == "timeout":
                    time.sleep(min(float(override.get("delay", DEFAULT_TIMEOUT_S)), common.MAX_TIMEOUT_DELAY_S))
                    self.close_connection = True
                    return                                         # aucune réponse, comme un vrai délai dépassé
                if error is not None:
                    raise ValueError(f"type d'erreur stub inconnu pour {name} : {error!r}")
                payload = canned(name, provider, now)
                if name == "ow_timeseries":
                    wanted = set(query.get("types") or [])
                    payload = {**payload, "data": [s for s in payload["data"] if not wanted or s["type"] in wanted]}
                return self._send(payload)
            except Exception as exc:  # noqa: BLE001 — un cas mal scripté ne doit jamais tuer le serveur
                return self._send({"detail": f"erreur interne du stub : {exc}"}, 500)

    return Handler


def main() -> int:
    provider = os.environ.get("ARC_OW_STUB_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    if provider not in KNOWN_PROVIDERS:
        print(f"fournisseur stub inconnu : {provider!r} (attendu : {', '.join(KNOWN_PROVIDERS)})", file=sys.stderr)
        return 2
    handler = make_handler(common.load_stub_config(), provider, os.environ.get("ARC_OW_STUB_KEY", ""),
                           os.environ.get(common.LOG_ENV_VAR))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    print(f"PORT={httpd.server_address[1]}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
