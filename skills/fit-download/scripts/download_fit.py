#!/usr/bin/env python3
"""Téléchargeur de fichiers FIT — Garmin Connect ou Intervals.icu, ou flux Strava, sans passer par le MCP.

Trois sources, choisies par `--source` (défaut : `[data].source` du workspace, #68) :

- **`garmin`** — résout le timeout MCP de `get_activity_fit_data` (records GPS =
  payload de plusieurs Mo qui dépasse le timeout côté client). Utilise la librairie
  `garminconnect` déjà installée dans l'environnement `garmin-mcp` et les tokens
  locaux `~/.garminconnect` — aucun mot de passe nécessaire.
- **`intervals`** — `GET /api/v1/activity/<id>/fit-file` de l'API Intervals.icu
  (bibliothèque standard, `urllib`), authentifié par la clé API déjà configurée pour
  le serveur MCP `intervals-icu-mcp` (`~/.config/ai-running-coach/intervals-icu-mcp/.env`,
  écrit par `./install.sh --source intervals`). Intervals.icu garde le FIT de toute
  activité importée depuis une montre (Garmin, COROS, Suunto, Polar, Apple Watch via
  HealthFit/RunGap…) — SAUF celles importées depuis Strava, que l'API Strava interdit
  de redistribuer : elles sont détectées (`source = "STRAVA"`) et sautées avec une
  raison explicite, jamais un FIT vide ni une valeur inventée.
- **`strava`** (#164) — Strava ne sert PAS de fichier FIT : l'API REST (`GET /activities/<id>/streams`,
  bibliothèque standard `urllib`) rend les flux par seconde (temps, distance, altitude, FC, vitesse
  lissée, cadence, GPS), normalisés par `arc_samples.strava_streams_to_records` vers le même
  `activities/fit/s<chiffres>.json` que le FIT — donc les mêmes KPI. Authentifié par les jetons du
  serveur MCP communautaire (`~/.config/strava-mcp/config.json`, écrit par son outil `connect-strava`) ;
  un jeton expiré est rafraîchi (le nouveau jeton, rotatif, est réécrit atomiquement dans ce même
  fichier) — aucun secret n'est jamais affiché. Pas de `.fit` brut ni de `<id>.records.json` : la
  copie normalisée est toujours écrite, avec ou sans `--json`.

Usage:
  download_fit.py 12345678901                          # -> activities/12345678901.fit
  download_fit.py 12345678901 --json                   # + JSON des records GPS
  download_fit.py 12345678901 12345678902 12345678903  # plusieurs
  download_fit.py --from-dir activities/               # lit l'identifiant dans les MD
  download_fit.py 12345678901 --output-dir /tmp/fits/
  download_fit.py i123456789 --json --source intervals # -> activities/i123456789.fit (+ fit/i123456789.json)

Options:
  --source       garmin | intervals | strava (défaut: [data].source du workspace, sinon garmin)
  --output-dir   Répertoire de sortie (défaut: activities/)
  --json         Écrit aussi <id>.records.json (bruts fitparse) ET la copie normalisée
                 activities/fit/<id>.json (#42 — ingérée par `scripts/arc_index.py`)
  --overwrite    Ré-télécharge même si le fichier existe
  --refresh-dynamics
                 (#151) RÉ-EXTRAIT la dynamique de course (temps de contact, balance, oscillation et
                 ratio verticaux, longueur de pas) depuis les `.fit` DÉJÀ présents dans le répertoire
                 de sortie, vers `activities/fit/<id>.json`. Aucun téléchargement, aucune connexion
                 Garmin : nécessite seulement `fitparse` (relance avec le python de garmin-mcp).
                 N'écrit que ces JSON dérivés (jetables, jamais versionnés) — jamais un Markdown, jamais
                 un `.fit`. Idempotent : un JSON déjà à jour est laissé tel quel. Ensuite, relancer
                 `scripts/arc_index.py` (ou ouvrir le tableau de bord) réingère les fichiers changés.
  --dry-run      Avec `--refresh-dynamics` : liste (id par id) ce qui serait créé / réécrit, sans rien écrire
  -v, --verbose  Avec `--refresh-dynamics` : liste aussi les id déjà à jour
                 Un `.fit` téléchargé sans `--json` n'a pas de JSON normalisé : `--refresh-dynamics` le CRÉE.
  --python PATH  Interpréteur contenant garminconnect/fitparse (auto-détecté sinon)

Identifiants : un entier pour Garmin (`garmin_activity_id` du bloc ```arc), une
chaîne `i<chiffres>` pour Intervals.icu (`intervals_activity_id`), `s<chiffres>` pour Strava
(`strava_activity_id`, préfixe du projet — l'API rend l'entier nu). La copie
normalisée porte ce même identifiant dans son nom (`fit/i123456789.json`) : c'est
lui qu'`arc_index.py` utilise pour la rattacher à la séance.

Sans `--overwrite`, une séance déjà téléchargée est sautée — avec `--json`, ce
saut porte sur la copie NORMALISÉE canonique (`<out_dir>/fit/<id>.json`), pas
sur le seul `.fit` brut (voir `_should_skip_download`) : relancer cette commande
avec `--from-dir --json` sur un historique déjà rattrapé ne re-télécharge donc
que les séances qui n'ont pas encore leur copie normalisée.

Avec `--json`, en plus du dump brut `fitparse` (`<id>.records.json`, à des fins de
diagnostic/analyse fine — `skills/session-parts-analyzer`), une copie **normalisée**
est écrite au chemin canonique `activities/fit/<id>.json` (voir `scripts/arc_samples.py`
pour le format et les règles de normalisation — unités, doublement de la cadence
course à pied). C'est ce second fichier que `scripts/arc_index.py` ingère dans
`activity_sample` ; le premier (`<id>.records.json`) reste inchangé pour compatibilité
ascendante avec les skills qui le lisent déjà (`session-parts-analyzer`).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# skills/<skill>/scripts/download_fit.py → 3 niveaux jusqu'à la racine du MOTEUR (là où
# vivent scripts/coach_setup.py et scripts/arc_samples.py) — jamais celle du workspace,
# voir `_activity_dir_out` ci-dessous pour la distinction et le bug qu'elle corrige.
_ENGINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ENGINE_ROOT / "scripts"))


def _activity_dir_out() -> Path:
    """Répertoire par défaut : `activities/` du WORKSPACE (pas forcément le moteur).

    Bug corrigé (revue PR #87) : une version antérieure remontait depuis `__file__`
    (`skills/<skill>/scripts/download_fit.py` → 3 niveaux) pour dériver `activities/`.
    Correct uniquement quand moteur et workspace sont le même dossier (installation
    fusionnée) — dans une installation séparée (`--workspace`, `docs/workspace.md`),
    `skills/` du workspace est un LIEN SYMBOLIQUE vers le moteur, que `Path.resolve()`
    suit : le résultat pointait alors TOUJOURS `<moteur>/activities`, jamais le
    workspace réel de l'utilisateur — les échantillons canoniques n'étaient donc
    jamais là où `scripts/arc_index.py` (qui, lui, résout bien le workspace via
    `coach_setup.workspace_root`) les cherche.

    Même résolution que `scripts/coach_setup.workspace_root()` : `$ARC_WORKSPACE`,
    puis le pointeur `~/.config/ai-running-coach/workspace`, puis (installation
    fusionnée ou pointeur absent) le moteur lui-même — la même chaîne que le reste
    du projet (`scripts/lib/config.sh`, `arc_index.py`).
    """
    from coach_setup import workspace_root  # noqa: E402 (sys.path déjà préparé plus haut)

    return workspace_root() / "activities"


# Par source : module requis, variable d'override de l'interpréteur (`--python`), outil
# `uv` qui l'embarque, et commande de réparation affichée si rien n'est trouvé. Côté
# Intervals.icu, le téléchargement lui-même est stdlib (`urllib`) : seul `fitparse`
# (lecture des records, `--json`) manque — `./install.sh --source intervals` l'installe
# dans l'environnement `intervals-icu-mcp` (`uv tool install --with fitparse`).
_RELAUNCH = {
    "garmin": {
        "module": "garminconnect", "env": "GARMIN_PYTHON", "tool": "garmin-mcp",
        "fix": "→ utilisez le python de garmin-mcp : --python ~/.local/share/uv/tools/garmin-mcp/bin/python3",
    },
    "intervals": {
        "module": "fitparse", "env": "INTERVALS_PYTHON", "tool": "intervals-icu-mcp",
        "fix": "→ relancez ./install.sh --source intervals (installe fitparse dans l'environnement "
               "intervals-icu-mcp), ou passez --python vers un interpréteur qui a fitparse",
    },
    # Strava (#164) : téléchargement stdlib et pas de FIT à lire — aucun module, aucun relancement.
    "strava": {"module": None, "env": "STRAVA_PYTHON", "tool": None, "fix": ""},
}


_RELAUNCHED_ENV = "ARC_FIT_DOWNLOAD_RELAUNCHED"


def _relaunch_for_fitparse(argv: list[str]) -> None:
    """`--refresh-dynamics` (#151) : seul `fitparse` est requis, quelle que soit la source des `.fit`. Présent
    dans l'environnement de `garmin-mcp` ET (`./install.sh --source intervals`) dans celui d'`intervals-icu-mcp` :
    on essaie l'un puis l'autre, une seule relance (jamais de boucle)."""
    if _module_available("fitparse"):
        return
    if not os.environ.get(_RELAUNCHED_ENV):
        for source in ("garmin", "intervals"):
            spec = _RELAUNCH[source]
            py = pick_relaunch_candidate(relaunch_candidates(
                os.environ.get(spec["env"]), shutil.which(spec["tool"]), tool=spec["tool"]))
            if py:
                r = subprocess.run([py, os.path.abspath(__file__)] + argv,
                                   env={**os.environ, _RELAUNCHED_ENV: "1"})
                sys.exit(r.returncode)
    print("ERREUR : module 'fitparse' introuvable dans cet interpréteur.\n"
          f"{_RELAUNCH['garmin']['fix']}\n{_RELAUNCH['intervals']['fix']}", file=sys.stderr)
    sys.exit(2)


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def relaunch_candidates(garmin_python=None, garmin_mcp_exe=None, home=None, tool: str = "garmin-mcp") -> list[str]:
    """Interpréteurs candidats (ordre de priorité) : la variable d'override (`GARMIN_PYTHON` /
    `INTERVALS_PYTHON`), le venv du binaire `tool` du PATH, puis l'emplacement uv par défaut.
    `python3` ET `python` à chaque fois (sur Linux l'un est un lien vers l'autre)."""
    candidates: list[str] = []
    if garmin_python:
        candidates.append(os.path.expanduser(garmin_python))
    if garmin_mcp_exe:
        bindir = os.path.dirname(os.path.realpath(garmin_mcp_exe))
        candidates += [os.path.join(bindir, n) for n in ("python3", "python")]
    base = os.path.join(home or os.path.expanduser("~"), f".local/share/uv/tools/{tool}/bin")
    candidates += [os.path.join(base, n) for n in ("python3", "python")]
    return candidates


def is_current_interpreter(candidate: str, prefix: str = None, executable: str = None) -> bool:
    """Le candidat est-il l'interpréteur courant ? Un venv se reconnaît à son dossier (`pyvenv.cfg` à côté de
    `bin/`), PAS au `realpath` de son python : sur Linux `bin/python` d'un venv uv est un lien vers
    `/usr/bin/python3.x`, donc identique au python système une fois résolu — alors que les deux n'ont pas les
    mêmes paquets. Sans `pyvenv.cfg`, repli sur la comparaison des chemins résolus."""
    prefix = prefix or sys.prefix
    executable = executable or sys.executable
    venv_dir = os.path.dirname(os.path.dirname(os.path.abspath(candidate)))
    if os.path.isfile(os.path.join(venv_dir, "pyvenv.cfg")):
        return os.path.realpath(venv_dir) == os.path.realpath(prefix)
    return os.path.realpath(candidate) == os.path.realpath(executable)


def pick_relaunch_candidate(candidates, prefix: str = None, executable: str = None) -> str | None:
    for py in candidates:
        if os.path.exists(py) and not is_current_interpreter(py, prefix, executable):
            return py
    return None


def _auto_relaunch(argv: list[str], source: str = "garmin") -> None:
    """Relance ce script avec le python de l'outil MCP de `source` si le module requis
    (`garminconnect` pour Garmin, `fitparse` pour Intervals.icu) est absent."""
    spec = _RELAUNCH[source]
    if _module_available(spec["module"]):
        return

    # Ordre : --python (via la variable d'override), l'outil du PATH, puis l'emplacement
    # uv par défaut — ~/.local/bin est souvent absent du PATH d'une session SSH/cron.
    # Une seule relance : un interpréteur candidat qui n'a pas non plus le module ne doit
    # jamais relancer à son tour l'interpréteur d'origine (boucle infinie).
    py = None
    if not os.environ.get(_RELAUNCHED_ENV):
        py = pick_relaunch_candidate(relaunch_candidates(
            os.environ.get(spec["env"]), shutil.which(spec["tool"]), tool=spec["tool"]))
    if py:
        r = subprocess.run([py, os.path.abspath(__file__)] + argv,
                           env={**os.environ, _RELAUNCHED_ENV: "1"})
        sys.exit(r.returncode)

    print(
        f"ERREUR : module '{spec['module']}' introuvable dans cet interpréteur.\n{spec['fix']}",
        file=sys.stderr,
    )
    sys.exit(2)


def _login(client, token_dir: str) -> None:
    """Authentifie avec les tokens locaux (même store que le MCP garmin)."""
    try:
        client.login(token_dir)
    except TypeError:
        client.login()


def _unwrap_fit(data: bytes) -> bytes:
    """Garmin renvoie parfois un ZIP contenant le .fit → dézippe à la volée."""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            inner = next((n for n in z.namelist() if n.lower().endswith(".fit")), None)
            if inner:
                return z.read(inner)
    return data


def _ensure_gitignore(directory: Path, header: str, patterns: list[str]) -> None:
    """Garantit que chaque motif de `patterns` figure dans `directory/.gitignore`.

    Fichier absent : créé avec `header` + les motifs. Fichier déjà présent (ex. un
    `.gitignore` que l'athlète a lui-même écrit dans `activities/`) : le contenu
    existant n'est JAMAIS écrasé (whatever l'utilisateur y a mis — même geste que
    `.arc/.gitignore` dans `arc_index.open_db`), mais les motifs qui y manquent
    ENCORE sont ajoutés à la suite. Bug corrigé (revue PR #87) : une version
    antérieure de cette fonction ne faisait rien dès que le fichier existait, même
    sans les motifs attendus — un `.gitignore` préexistant dans `activities/` (créé
    par l'installateur, ou par l'athlète pour tout autre motif) empêchait alors
    silencieusement l'exclusion de `*.fit`/`*.records.json`, et le `git add -A` de
    `daily-sync` aurait committé des pistes GPS complètes dans le dépôt privé.
    Idempotent : un motif déjà présent (créé par un appel précédent, ou par
    l'utilisateur) n'est jamais dupliqué.
    """
    marker = directory / ".gitignore"
    if not marker.is_file():
        marker.write_text(header + "\n".join(patterns) + "\n", encoding="utf-8")
        return
    existing_text = marker.read_text(encoding="utf-8")
    existing_lines = {line.strip() for line in existing_text.splitlines()}
    missing = [p for p in patterns if p not in existing_lines]
    if not missing:
        return
    # Racine propre avant d'ajouter : un fichier existant sans retour à la ligne final
    # ne doit pas coller le premier motif ajouté à la dernière ligne existante.
    prefix = "" if not existing_text or existing_text.endswith("\n") else "\n"
    marker.write_text(existing_text + prefix + "\n".join(missing) + "\n", encoding="utf-8")


def _download_one(client, activity_id: int, out_dir: Path, want_json: bool) -> Path:
    from garminconnect import Garmin

    fit = client.download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    return _persist_fit(_unwrap_fit(fit), activity_id, out_dir, want_json)


def _persist_fit(fit: bytes, activity_id, out_dir: Path, want_json: bool) -> Path:
    """Écrit le FIT brut `<out_dir>/<id>.fit` et, avec `want_json`, ses records
    `fitparse` + la copie normalisée canonique — commun aux deux sources, qui ne
    diffèrent que par la façon d'obtenir les octets du FIT."""
    # FIT brut + records.json (pistes GPS complètes) : lourds, jetables, jamais
    # versionnés — même dans un workspace privé qui versionne `activities/`
    # (docs/workspace.md). `daily-sync` avec `git_autocommit = true` fait un
    # `git add -A` : sans ce marqueur, ces fichiers y seraient embarqués (should-fix
    # #4, revue PR #87). Motifs `*.fit`/`*.records.json` CIBLÉS, jamais un `*` : ce
    # répertoire (`out_dir`, normalement `activities/` du workspace) contient aussi
    # les Markdown de séances, versionnés eux — un blanket-ignore les exclurait à
    # tort du dépôt.
    _ensure_gitignore(out_dir, "# FIT bruts + records GPS complets : lourds, jetables, jamais versionnés.\n",
                       ["*.fit", "*.records.json"])

    out = out_dir / f"{activity_id}.fit"
    out.write_bytes(fit)
    print(f"OK {len(fit):,} octets -> {out}")

    if want_json and fit:
        records, sport = _write_records_json(fit, out.with_suffix(".records.json"))
        _write_canonical_samples(activity_id, records, out_dir, sport)
    return out


# ---------------------------------------------------------------------------
# Source Intervals.icu (#68) — API REST, bibliothèque standard uniquement
# ---------------------------------------------------------------------------

INTERVALS_API = "https://intervals.icu/api/v1"
# Identifiant d'une activité importée dans Intervals.icu (fichier FIT/TCX/GPX) :
# « i » + chiffres, ex. `i123456789` — la forme que `get_recent_activities` rend et
# que le contrat stocke dans `intervals_activity_id`. Une activité importée depuis
# Strava porte, elle, un identifiant sans préfixe — et n'est de toute façon pas
# redistribuable (voir `IntervalsUnavailable`).
INTERVALS_ID_RE = re.compile(r"^i\d+$")
# Même fichier que celui du serveur MCP (`install.sh`, INTERVALS_ENV_DIR) : une seule
# clé API à configurer pour le MCP ET pour ce script.
INTERVALS_ENV_FILE = Path("~/.config/ai-running-coach/intervals-icu-mcp/.env")
_HTTP_TIMEOUT_S = 60


class IntervalsError(RuntimeError):
    """Échec d'un appel à l'API Intervals.icu (réseau, authentification, statut HTTP)."""


class IntervalsUnavailable(IntervalsError):
    """Activité sans FIT récupérable — importée depuis Strava (API Strava : données non
    redistribuables par un tiers), ou saisie manuelle sans fichier. Jamais une panne :
    une raison à dire à l'athlète, la séance reste valide sans échantillons."""


def _read_env_file(path: Path) -> dict:
    """`KEY=VALUE` d'un fichier `.env` (commentaires `#`, guillemets simples ou doubles
    retirés) — le format qu'écrit `intervals-icu-mcp-auth` (python-dotenv `set_key`)."""
    values: dict = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _intervals_api_key(env_file: Path | None = None) -> str:
    """Clé API Intervals.icu : `$INTERVALS_ICU_API_KEY` si défini (même précédence que
    `intervals-icu-mcp`, pydantic-settings), sinon le `.env` du serveur MCP."""
    key = os.environ.get("INTERVALS_ICU_API_KEY", "").strip()
    if not key:
        key = _read_env_file((env_file or INTERVALS_ENV_FILE).expanduser()).get("INTERVALS_ICU_API_KEY", "").strip()
    if not key or key == "your_api_key_here":
        raise IntervalsError(
            f"clé API Intervals.icu introuvable ($INTERVALS_ICU_API_KEY ou {INTERVALS_ENV_FILE}) — "
            "lancez `./install.sh --source intervals` (ou `intervals-icu-mcp-auth`), voir docs/intervals-setup.md")
    return key


def _intervals_get(path: str, api_key: str, opener=None) -> bytes:
    """GET authentifié (Basic `API_KEY:<clé>`, comme `intervals-icu-mcp`). `opener`
    injectable pour les tests (aucun appel réseau dans la suite de tests)."""
    import base64
    import urllib.error
    import urllib.request

    token = base64.b64encode(f"API_KEY:{api_key}".encode()).decode()
    req = urllib.request.Request(f"{INTERVALS_API}{path}", headers={
        "Authorization": f"Basic {token}", "User-Agent": "ai-running-coach/download_fit"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=_HTTP_TIMEOUT_S) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise IntervalsError(f"HTTP 401 sur {path} : clé API Intervals.icu refusée "
                                 "(régénérer la clé : https://intervals.icu/settings, section Developer)") from exc
        if exc.code == 403:
            raise IntervalsError(f"HTTP 403 sur {path} : accès refusé — clé API Intervals.icu refusée, ou "
                                 "activité d'un autre athlète (régénérer la clé : https://intervals.icu/settings, "
                                 "section Developer)") from exc
        if exc.code == 429:
            raise IntervalsError(f"HTTP 429 sur {path} : limite de requêtes Intervals.icu atteinte — "
                                 "réessayer plus tard") from exc
        if exc.code == 404:
            raise IntervalsUnavailable(f"HTTP 404 sur {path} : activité introuvable, ou sans fichier FIT "
                                       "(saisie manuelle)") from exc
        raise IntervalsError(f"HTTP {exc.code} sur {path}") from exc
    except urllib.error.URLError as exc:
        raise IntervalsError(f"Intervals.icu injoignable ({exc.reason})") from exc


def _intervals_check_available(meta: dict) -> None:
    """Lève `IntervalsUnavailable` si l'activité est importée depuis Strava
    (`source = "STRAVA"` — l'API renvoie alors une coquille presque vide avec une
    `_note`). Une activité sans fichier d'origine (saisie manuelle) n'est PAS devinée
    ici : c'est le 404 de `/fit-file` qui la signale (`_intervals_get`)."""
    if str(meta.get("source") or "").upper() == "STRAVA":
        raise IntervalsUnavailable(
            "activité importée dans Intervals.icu depuis Strava — l'API Strava interdit sa "
            "redistribution, aucun FIT disponible. Connecter la montre (ou l'app qui l'exporte) "
            "directement à Intervals.icu pour les séances suivantes.")


def _unwrap_gzip(data: bytes) -> bytes:
    """Intervals.icu peut servir le fichier d'origine compressé (gzip)."""
    if data[:2] == b"\x1f\x8b":
        import gzip

        return gzip.decompress(data)
    return data


def _download_one_intervals(activity_id: str, out_dir: Path, want_json: bool, api_key: str,
                             opener=None) -> Path:
    if not INTERVALS_ID_RE.match(activity_id):
        raise IntervalsUnavailable(
            f"identifiant « {activity_id} » : forme i<chiffres> attendue (intervals_activity_id) — "
            "un identifiant sans préfixe est en général une activité importée depuis Strava, "
            "non redistribuable")
    meta = json.loads(_intervals_get(f"/activity/{activity_id}", api_key, opener).decode("utf-8"))
    _intervals_check_available(meta)
    fit = _unwrap_fit(_unwrap_gzip(_intervals_get(f"/activity/{activity_id}/fit-file", api_key, opener)))
    if not fit:
        raise IntervalsUnavailable("fichier FIT vide renvoyé par Intervals.icu")
    return _persist_fit(fit, activity_id, out_dir, want_json)


# ---------------------------------------------------------------------------
# Source Strava (#164) — flux par seconde via l'API REST, bibliothèque standard uniquement
# ---------------------------------------------------------------------------

STRAVA_API = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
# Fichier de jetons du serveur MCP communautaire r-huijts/strava-mcp (clés camelCase `clientId`,
# `clientSecret`, `accessToken`, `refreshToken`, `expiresAt` en secondes epoch — src/config.ts du
# commit épinglé par install.sh). Une seule connexion OAuth pour le MCP ET pour ce script.
STRAVA_CONFIG_FILE = Path("~/.config/strava-mcp/config.json")
STRAVA_ID_RE = re.compile(r"^s\d+$")
# Flux demandés (`keys`, avec `key_by_type=true` — exigé par l'API) : ceux que normalise
# `arc_samples.strava_streams_to_records`. La puissance (`watts`) n'est pas demandée : aucune
# colonne d'échantillon ne la porte.
STRAVA_STREAM_KEYS = "time,distance,altitude,heartrate,velocity_smooth,cadence,latlng"
# Marge (s) avant `expiresAt` à partir de laquelle on rafraîchit le jeton d'accès.
_STRAVA_REFRESH_MARGIN_S = 120


class StravaError(RuntimeError):
    """Échec d'un appel à l'API Strava (réseau, authentification, statut HTTP, jetons absents).
    Les messages ne contiennent JAMAIS un jeton, un secret client ou un corps de réponse."""


class StravaUnavailable(StravaError):
    """Activité sans flux récupérable (saisie manuelle, introuvable, d'un autre athlète) — jamais
    une panne : une raison à dire à l'athlète, la séance reste valide sans échantillons."""


class StravaTokens:
    """Jetons Strava lus dans le fichier du serveur MCP communautaire, rafraîchis au besoin.

    Le jeton de rafraîchissement de Strava est ROTATIF : chaque rafraîchissement en émet un nouveau
    et invalide l'ancien — il est donc réécrit sur place (même fichier que le MCP, atomiquement,
    mode 0600, autres clés conservées) avant toute autre utilisation, sinon le MCP serait
    déconnecté. Si le serveur MCP tourne en même temps, il relit ce fichier à chaque démarrage
    seulement : éviter de lancer un téléchargement pendant une session MCP qui rafraîchit aussi.
    `opener`/`now` injectables pour les tests (aucun appel réseau, aucune horloge réelle)."""

    def __init__(self, path: Path | None = None, opener=None, now=None):
        import time

        self.path = (path or STRAVA_CONFIG_FILE).expanduser()
        self.opener = opener
        self._now = now or time.time
        self.data = self._load()
        if not (self.data.get("accessToken") and self.data.get("refreshToken")):
            raise StravaError(
                f"jetons Strava introuvables ({STRAVA_CONFIG_FILE}) — lancez `./install.sh --source strava` "
                "puis demandez à l'agent d'exécuter l'outil `connect-strava` du serveur strava, "
                "voir docs/strava-setup.md")

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def access_token(self) -> str:
        expires = self.data.get("expiresAt")
        if isinstance(expires, (int, float)) and expires - self._now() < _STRAVA_REFRESH_MARGIN_S:
            self.refresh()
        return self.data["accessToken"]

    def refresh(self) -> None:
        """Échange le jeton de rafraîchissement (POST `/oauth/token`) et persiste le résultat."""
        import urllib.error
        import urllib.parse
        import urllib.request

        client_id = os.environ.get("STRAVA_CLIENT_ID") or self.data.get("clientId")
        client_secret = os.environ.get("STRAVA_CLIENT_SECRET") or self.data.get("clientSecret")
        if not (client_id and client_secret and self.data.get("refreshToken")):
            raise StravaError("rafraîchissement impossible : clientId/clientSecret absents — relancer "
                              "`connect-strava` (voir docs/strava-setup.md)")
        body = urllib.parse.urlencode({
            "client_id": client_id, "client_secret": client_secret,
            "grant_type": "refresh_token", "refresh_token": self.data["refreshToken"]}).encode()
        req = urllib.request.Request(STRAVA_TOKEN_URL, data=body, headers={
            "User-Agent": "ai-running-coach/download_fit"})
        try:
            with (self.opener or urllib.request.urlopen)(req, timeout=_HTTP_TIMEOUT_S) as resp:
                fresh = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise StravaError(f"HTTP {exc.code} au rafraîchissement du jeton Strava — reconnecter le compte "
                              "(`connect-strava`, voir docs/strava-setup.md)") from exc
        except urllib.error.URLError as exc:
            raise StravaError(f"Strava injoignable ({exc.reason})") from exc
        except ValueError as exc:
            raise StravaError("réponse illisible au rafraîchissement du jeton Strava") from exc
        if not (isinstance(fresh, dict) and fresh.get("access_token") and fresh.get("refresh_token")):
            raise StravaError("réponse de rafraîchissement Strava incomplète")
        self.data.update(accessToken=fresh["access_token"], refreshToken=fresh["refresh_token"],
                         expiresAt=fresh.get("expires_at"))
        self._persist()

    def _persist(self) -> None:
        # Fusion avec le contenu actuel du fichier (le MCP a pu y écrire entre-temps), puis
        # remplacement atomique : jamais un fichier de jetons à moitié écrit.
        merged = {**self._load(), **self.data}
        tmp = self.path.with_name(self.path.name + f".tmp{os.getpid()}")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(merged, fh, indent=2)
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()


def _strava_get(path: str, tokens: StravaTokens, opener=None, _retry: bool = True):
    """GET JSON authentifié (Bearer). Un 401 déclenche UN rafraîchissement puis une relance.
    Erreurs expliquées sans jamais citer le jeton ni le corps de la réponse."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(f"{STRAVA_API}{path}", headers={
        "Authorization": f"Bearer {tokens.access_token}", "User-Agent": "ai-running-coach/download_fit"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=_HTTP_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401 and _retry:
            tokens.refresh()
            return _strava_get(path, tokens, opener, _retry=False)
        if exc.code == 401:
            raise StravaError(f"HTTP 401 sur {path} : jeton Strava refusé même après rafraîchissement — "
                              "reconnecter le compte (`connect-strava`)") from exc
        if exc.code == 403:
            raise StravaError(f"HTTP 403 sur {path} : accès refusé — portée OAuth insuffisante "
                              "(activity:read_all requise pour les activités privées) ou activité d'un autre "
                              "athlète ; reconnecter le compte avec les bonnes portées") from exc
        if exc.code == 429:
            raise StravaError(f"HTTP 429 sur {path} : limite de requêtes de l'API Strava atteinte (par défaut "
                              "200 requêtes / 15 min et 2000 / jour par application — à vérifier pour la "
                              "vôtre) ; deux requêtes par séance : réessayer plus tard, par petits lots") from exc
        if exc.code == 404:
            raise StravaUnavailable(f"HTTP 404 sur {path} : activité introuvable, ou sans flux "
                                    "(saisie manuelle)") from exc
        raise StravaError(f"HTTP {exc.code} sur {path}") from exc
    except urllib.error.URLError as exc:
        raise StravaError(f"Strava injoignable ({exc.reason})") from exc
    except ValueError as exc:
        raise StravaError(f"réponse illisible de Strava sur {path}") from exc


def _download_one_strava(activity_id: str, out_dir: Path, tokens: StravaTokens, opener=None) -> Path:
    """Flux d'une activité Strava → copie normalisée `<out_dir>/fit/s<chiffres>.json`. Deux requêtes
    (détail pour le sport, puis flux). Données privées de l'athlète : écrites seulement dans son espace
    de travail (`activities/fit/` est gitignoré), jamais redistribuées (accord API Strava)."""
    import arc_samples as S  # noqa: E402 (sys.path déjà préparé en tête de module)

    if not STRAVA_ID_RE.match(activity_id):
        raise StravaUnavailable(
            f"identifiant « {activity_id} » : forme s<chiffres> attendue (strava_activity_id) — "
            "l'API Strava rend un entier nu, à préfixer par « s »")
    num = activity_id[1:]
    meta = _strava_get(f"/activities/{num}", tokens, opener)
    if isinstance(meta, dict) and meta.get("manual"):
        raise StravaUnavailable("activité saisie à la main : aucun flux par seconde")
    sport = (meta.get("sport_type") or meta.get("type")) if isinstance(meta, dict) else None
    streams = _strava_get(f"/activities/{num}/streams?keys={STRAVA_STREAM_KEYS}&key_by_type=true", tokens, opener)
    records = S.strava_streams_to_records(streams, sport)
    if not records:
        raise StravaUnavailable("aucun flux `time` exploitable renvoyé par Strava")
    _write_canonical_samples(activity_id, records, out_dir)
    return out_dir / "fit" / f"{activity_id}.json"


def _read_fit(fit: bytes) -> tuple[list[dict], str | None]:
    """Records FIT bruts (champs `fitparse` tels quels, valeurs nulles/binaires écartées) et sport
    de la séance (message `session`, minuscules) — sans rien écrire. Partagé par l'écriture du
    dump brut et par `--refresh-dynamics`."""
    import fitparse

    f = fitparse.FitFile(io.BytesIO(fit))
    records: list[dict] = []
    for m in f.get_messages("record"):
        r: dict = {}
        for field in m.fields:
            if field.value is None or isinstance(field.value, bytes):
                continue
            r[field.name] = field.value
        records.append(r)

    sport = None
    for m in f.get_messages("session"):
        value = m.get_value("sport")
        if value is not None:
            sport = str(value).lower()
            break
    return records, sport


def refresh_dynamics(out_dir: Path, dry_run: bool = False) -> dict:
    """Ré-extrait la copie normalisée `<out_dir>/fit/<id>.json` de chaque `<out_dir>/<id>.fit` présent
    (#151) — pour rattraper la dynamique de course sur les FIT déjà téléchargés avant qu'elle soit
    extraite. Ne touche QUE ces JSON dérivés (pas de Markdown, pas de `.fit`, pas de réseau) ; les
    clés du JSON existant autres que `records` sont conservées. Idempotent : contenu identique =
    fichier laissé intact. Un `.fit` téléchargé SANS `--json` n'a pas encore de JSON : il est CRÉÉ (`created`),
    pas seulement réécrit. Rend des compteurs `{"created", "rewritten", "unchanged", "failed", "with_dynamics",
    "files": [(id, statut)]}` ; `dry_run` compte sans écrire."""
    import arc_samples as S  # noqa: E402 (sys.path déjà préparé en tête de module)

    fit_dir = out_dir / "fit"
    result: dict = {"created": 0, "rewritten": 0, "unchanged": 0, "failed": 0, "with_dynamics": 0, "files": []}
    for fit_path in sorted(out_dir.glob("*.fit")):
        # `<entier>.fit` (Garmin) ET `i<chiffres>.fit` (Intervals.icu, #68) : même emplacement, même nom de
        # copie normalisée (`fit/<id>.json`), identifiant conservé tel quel (entier ou chaîne).
        if fit_path.stem.isdigit():
            activity_id = int(fit_path.stem)
        elif INTERVALS_ID_RE.match(fit_path.stem):
            activity_id = fit_path.stem
        else:
            continue
        try:
            records, sport = _read_fit(fit_path.read_bytes())
            normalised = S.normalise_records(records, sport=sport)
        except Exception as e:  # noqa: BLE001 — un FIT illisible ne doit pas arrêter le lot
            print(f"FAIL {activity_id}: {e}", file=sys.stderr)
            result["failed"] += 1
            result["files"].append((activity_id, "failed"))
            continue
        if any(rec.get(k) is not None for rec in normalised for k in S.DYNAMICS_KEYS):
            result["with_dynamics"] += 1
        target = fit_dir / f"{activity_id}.json"
        payload: dict = {}
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    payload = existing
            except (ValueError, OSError):
                payload = {}
        payload.update({"activity_id": activity_id, "records": normalised})
        text = json.dumps(payload, ensure_ascii=False)
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            result["unchanged"] += 1
            result["files"].append((activity_id, "unchanged"))
            continue
        existed = target.is_file()       # sinon : `.fit` téléchargé sans `--json`, le JSON est CRÉÉ
        if not dry_run:
            fit_dir.mkdir(parents=True, exist_ok=True)
            _ensure_gitignore(fit_dir, "# Échantillons FIT normalisés : jetables, jamais versionnés.\n",
                               ["*", "!.gitignore"])
            target.write_text(text, encoding="utf-8")
        key = "rewritten" if existed else "created"
        result[key] += 1
        result["files"].append((activity_id, ("would_" if dry_run else "") + {"rewritten": "rewrite", "created": "create"}[key]
                                 if dry_run else key))
    return result


def _write_records_json(fit: bytes, out: Path) -> tuple[list[dict], str | None]:
    """Extrait les records (timestamp, lat/long, altitude, FC, cadence, power) → JSON
    BRUT (champs `fitparse` tels quels), et le sport de la séance (message FIT
    `session`, ex. `"running"`, `"cycling"`). Rend `(records, sport)` pour
    `_write_canonical_samples`, qui les normalise (#42) sans reparser le FIT une
    seconde fois — `sport` gouverne le doublement (ou non) de la cadence, spécifique
    aux sports à pied (voir `arc_samples.CADENCE_DOUBLING_SPORTS` — un FIT vélo lu
    sans ce paramètre verrait sa cadence, déjà complète, doublée à tort)."""
    records, sport = _read_fit(fit)

    out.write_text(json.dumps(records, default=str))
    print(f"OK {len(records)} records -> {out} (sport: {sport or 'inconnu'})")
    return records, sport


def _write_canonical_samples(activity_id: int, raw_records: list[dict], activities_root: Path,
                              sport: str | None = None) -> None:
    """Copie normalisée (#42) au chemin canonique `activities/fit/<id>.json`, ingérée par
    `scripts/arc_index.py` (table `activity_sample`). `activities_root` est le
    `--output-dir` de ce script — normalement `activities/` du workspace ; si un autre
    répertoire est passé, la copie canonique reste relative à CE répertoire (pas au
    workspace) pour ne jamais écrire hors de l'endroit demandé par l'utilisateur.

    `scripts/arc_samples.py` est un module stdlib pur (pas de dépendance à
    `garminconnect`/`fitparse`) : l'importer ici ne casse pas la contrainte « aucune
    dépendance dans l'index » (CONTRIBUTING.md) — seul CE script (déjà hors-stdlib pour
    `garminconnect`/`fitparse`) l'utilise en plus de `arc_index.py`. `sport` (lu du
    message FIT `session` par `_write_records_json`) gouverne le doublement de la
    cadence course à pied — voir `arc_samples.normalise_records`.
    """
    import arc_samples as S  # noqa: E402 (sys.path déjà préparé en tête de module)

    fit_dir = activities_root / "fit"
    fit_dir.mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(fit_dir, "# Échantillons FIT normalisés : jetables, jamais versionnés.\n",
                       ["*", "!.gitignore"])
    records = S.normalise_records(raw_records, sport=sport)
    out = fit_dir / f"{activity_id}.json"
    out.write_text(json.dumps({"activity_id": activity_id, "records": records}, ensure_ascii=False),
                    encoding="utf-8")
    print(f"OK {len(records)} échantillons normalisés -> {out}")


def _activity_id_from_arc(text: str, source: str = "garmin"):
    """Identifiant de la séance dans le bloc ```arc (contrat workspace-data-contract),
    ou None : `garmin_activity_id` (entier) pour `source="garmin"`,
    `intervals_activity_id` (chaîne `i<chiffres>`) pour `source="intervals"`."""
    m = re.search(r"^```arc[ \t]*\n(.*?)\n```", text, re.M | re.S)
    if not m:
        return None
    key = {"intervals": "intervals_activity_id", "strava": "strava_activity_id"}.get(source, "garmin_activity_id")
    try:
        value = json.loads(m.group(1)).get(key)
    except (ValueError, AttributeError):
        return None
    if source == "intervals":
        return value if isinstance(value, str) and INTERVALS_ID_RE.match(value) else None
    if source == "strava":
        return value if isinstance(value, str) and STRAVA_ID_RE.match(value) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _should_skip_download(dst: Path, out_dir: Path, activity_id, *,
                           overwrite: bool, want_json: bool) -> bool:
    """`True` si `activity_id` peut être sauté (déjà téléchargé) — jamais un simple
    `dst.exists()` (le `.fit` brut) quand `--json` est demandé : une version
    antérieure re-téléchargeait ALORS SYSTÉMATIQUEMENT chaque séance déjà présente
    dès que `--json` était passé (revue de code, correctif rattrapage historique) —
    coûteux et inutile sur un historique de centaines de séances déjà rattrapées.
    Avec `--json`, on saute aussi UNIQUEMENT si la copie **normalisée** canonique
    (`<out_dir>/fit/<activity_id>.json`, celle qu'`arc_index.py` ingère réellement,
    voir `_write_canonical_samples`) existe déjà — le `.fit` brut seul ne suffit pas
    (une exécution antérieure SANS `--json` n'a jamais produit cette copie).
    Avec `--json`, la copie normalisée suffit : si l'athlète a supprimé les `.fit`
    bruts (lourds, jetables) en gardant `fit/<id>.json`, rien n'est re-téléchargé.
    `overwrite=True` ne saute jamais, quel que soit l'état des fichiers."""
    if overwrite:
        return False
    if want_json:
        return (out_dir / "fit" / f"{activity_id}.json").exists()
    return dst.exists()


def _configured_source() -> str:
    """`[data].source` du workspace (#68), `garmin` par défaut ou si illisible — la
    même résolution que `garmin_watch.load_settings`."""
    try:
        from arc_index import load_config  # noqa: E402 (sys.path déjà préparé en tête de module)
        from coach_setup import workspace_root  # noqa: E402

        source = (load_config(workspace_root()).get("data") or {}).get("source", "garmin")
    except Exception:  # noqa: BLE001 — TOML invalide : signalé par coach_doctor, pas ici
        return "garmin"
    return source if source in _RELAUNCH else "garmin"


def _parse_ids(raw: list[str], source: str, ap: argparse.ArgumentParser) -> list:
    """Entiers pour Garmin ; chaînes pour Intervals.icu (validées au téléchargement,
    pour qu'un identifiant Strava sans préfixe reçoive une raison explicite) ; chaînes
    aussi pour Strava (`s<chiffres>`, validées au téléchargement)."""
    if source in ("intervals", "strava"):
        return list(raw)
    ids = []
    for value in raw:
        if not value.isdigit():
            hint = " (identifiant Intervals.icu ? ajoutez --source intervals)" if INTERVALS_ID_RE.match(value) else ""
            ap.error(f"identifiant Garmin entier attendu, « {value} » reçu{hint}")
        ids.append(int(value))
    return ids


def _ids_from_dir(directory: Path, source: str) -> list:
    ids = []
    for md in directory.glob("*.md"):
        txt = md.read_text(encoding="utf-8", errors="ignore")
        found = _activity_id_from_arc(txt, source)
        if found is None and source == "garmin":
            # Fichiers antérieurs au contrat : la clé en début de ligne du bloc YAML
            # uniquement — un « activity_id: 123 » cité dans la prose n'est pas une séance.
            m = re.search(r"^activity_id:\s*(\d+)", txt, re.M)
            found = int(m.group(1)) if m else None
        if found is not None:
            ids.append(found)
    return ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Télécharge des fichiers FIT (Garmin Connect ou Intervals.icu) sans passer par le MCP."
    )
    ap.add_argument("activity_ids", nargs="*",
                    help="identifiants à télécharger (entier Garmin, i<chiffres> Intervals.icu, s<chiffres> Strava)")
    ap.add_argument("--source", choices=sorted(_RELAUNCH), default=None,
                    help="garmin | intervals | strava (défaut : [data].source du workspace, sinon garmin)")
    ap.add_argument("--output-dir", type=Path, default=None, help="Répertoire de sortie (défaut: activities/)")
    ap.add_argument("--json", action="store_true", help="Écrit aussi <id>.records.json")
    ap.add_argument("--overwrite", action="store_true", help="Réécrire même si présent")
    ap.add_argument("--from-dir", type=Path, default=None, help="Scan de fichiers MD pour l'identifiant")
    ap.add_argument("--python", type=Path, default=None, help="Interpréteur garminconnect/fitparse (override)")
    ap.add_argument("--refresh-dynamics", action="store_true",
                    help="Ré-extrait la dynamique de course des .fit déjà présents (aucun téléchargement)")
    ap.add_argument("--dry-run", action="store_true", help="Avec --refresh-dynamics : n'écrit rien")
    ap.add_argument("-v", "--verbose", action="store_true", help="Avec --refresh-dynamics : liste aussi les id à jour")
    args = ap.parse_args(argv)

    source = args.source or _configured_source()
    if args.python and source != "strava":
        os.environ[_RELAUNCH[source]["env"]] = str(args.python)
    if args.refresh_dynamics:
        # Hors ligne, quelle que soit la source : ni `garminconnect` ni tokens ni clé API — seul
        # `fitparse` est requis. Fichiers Garmin (`<entier>.fit`) ET Intervals.icu (`i<chiffres>.fit`).
        _relaunch_for_fitparse(sys.argv[1:] if argv is None else list(argv))
        out_dir = args.output_dir or _activity_dir_out()
        result = refresh_dynamics(out_dir, dry_run=args.dry_run)
        labels = {"create": "à créer", "rewrite": "à réécrire", "created": "créé", "rewritten": "réécrit",
                  "unchanged": "déjà à jour", "failed": "échec"}
        for activity_id, status in result["files"]:
            if status != "unchanged" or args.verbose:
                print(f"  {activity_id} : {labels.get(status.replace('would_', ''), status)}")
        if args.dry_run:
            print(f"{result['created']} JSON à créer, {result['rewritten']} à réécrire, ", end="")
        else:
            print(f"{result['created']} JSON créés, {result['rewritten']} réécrits, ", end="")
        print(f"{result['unchanged']} déjà à jour, {result['failed']} échec(s) ; "
              f"{result['with_dynamics']} séance(s) avec dynamique de course — {out_dir / 'fit'}")
        return 1 if result["failed"] else 0
    # Intervals.icu : le téléchargement est stdlib, seul `--json` (lecture fitparse) a
    # besoin d'un autre interpréteur. Garmin : garminconnect est requis dans tous les cas.
    if source == "garmin" or (args.json and source == "intervals"):
        _auto_relaunch(sys.argv[1:] if argv is None else list(argv), source)

    ids = _parse_ids(args.activity_ids, source, ap)
    if args.from_dir:
        # Entiers Garmin en ordre numérique (9 avant 10), puis identifiants Intervals.icu.
        ids = sorted(set(ids + _ids_from_dir(args.from_dir, source)), key=lambda x: (isinstance(x, str), x))
    if not ids:
        ap.error("aucun identifiant fourni (args ou --from-dir)")

    out_dir = args.output_dir or _activity_dir_out()
    out_dir.mkdir(parents=True, exist_ok=True)

    if source == "strava":
        try:
            tokens = StravaTokens()
        except StravaError as exc:
            print(f"ERREUR : {exc}", file=sys.stderr)
            return 2

        def fetch(aid):
            return _download_one_strava(aid, out_dir, tokens)
    elif source == "intervals":
        try:
            api_key = _intervals_api_key()
        except IntervalsError as exc:
            print(f"ERREUR : {exc}", file=sys.stderr)
            return 2

        def fetch(aid):
            return _download_one_intervals(aid, out_dir, args.json, api_key)
    else:
        token_dir = str(Path("~/.garminconnect").expanduser())
        from garminconnect import Garmin

        client = Garmin()
        _login(client, token_dir)

        def fetch(aid):
            return _download_one(client, aid, out_dir, args.json)

    counts = _download_all(ids, fetch, lambda aid: _should_skip_download(
        out_dir / f"{aid}.fit", out_dir, aid, overwrite=args.overwrite,
        want_json=args.json or source == "strava"))
    suffix = f", {counts['unavailable']} sans FIT disponible" if counts["unavailable"] else ""
    if counts["skipped"]:
        suffix += f", {counts['skipped']} déjà présents"
    print(f"{counts['ok']}/{len(ids)} téléchargements OK dans {out_dir}{suffix}")
    return 1 if counts["failed"] else 0


def _download_all(ids, fetch, should_skip) -> dict:
    """Télécharge chaque identifiant et compte les issues. Seul un `FAIL` (erreur réelle :
    réseau, clé refusée, FIT illisible…) est une panne : une activité INDISPONIBLE
    (import Strava, saisie manuelle) ou déjà présente n'en est pas une — sinon un jour
    avec une seule séance Strava ferait échouer `daily-sync.sh` en headless."""
    counts = {"ok": 0, "unavailable": 0, "skipped": 0, "failed": 0}
    for aid in ids:
        if should_skip(aid):
            print(f"skip {aid} (existe) — --overwrite pour forcer")
            counts["skipped"] += 1
            continue
        try:
            fetch(aid)
            counts["ok"] += 1
        except (IntervalsUnavailable, StravaUnavailable) as e:
            # Pas une panne : la séance reste valide sans échantillons — raison dite, puis on continue.
            counts["unavailable"] += 1
            print(f"INDISPONIBLE {aid}: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            counts["failed"] += 1
            print(f"FAIL {aid}: {e}", file=sys.stderr)
    return counts

if __name__ == "__main__":
    sys.exit(main())