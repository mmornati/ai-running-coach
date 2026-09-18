#!/usr/bin/env python3
"""Téléchargeur de fichiers FIT Garmin — bypass du canal MCP.

Résout le timeout MCP de `garmin_get_activity_fit_data` (records GPS = payload
de plusieurs Mo qui dépasse le timeout côté client). Ce script utilise la
librairie `garminconnect` déjà installée dans l'environnement `garmin-mcp` et
les tokens locaux `~/.garminconnect` — aucun mot de passe nécessaire.

Usage:
  download_fit.py 12345678901                          # -> activities/12345678901.fit
  download_fit.py 12345678901 --json                   # + JSON des records GPS
  download_fit.py 12345678901 12345678902 12345678903  # plusieurs
  download_fit.py --from-dir activities/               # lit activity_id dans les MD
  download_fit.py 12345678901 --output-dir /tmp/fits/

Options:
  --output-dir   Répertoire de sortie (défaut: activities/)
  --json         Écrit aussi <id>_records.json (records GPS/HR/power/cadence)
  --overwrite    Ré-télécharge même si le fichier existe
  --python PATH  Interpréteur contenant garminconnect (auto-détecté sinon)
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


def _activity_dir_out() -> Path:
    """Répertoire par défaut : `activities/` du workspace.

    Remonte depuis `scripts/` jusqu'à la racine du projet (skills/<skill>/scripts/),
    puis utilise `<racine>/activities`. Si le dossier n'existe pas encore, il est
    créé à la première utilisation.
    """
    here = Path(__file__).resolve()
    # skills/<skill>/scripts/analyze_*.py → remonter de 3 niveaux pour la racine
    root = here.parents[3]
    return root / "activities"


def _auto_relaunch(argv: list[str]) -> None:
    """Relance ce script avec le python de garmin-mcp si garminconnect est absent."""
    try:
        import garminconnect  # noqa: F401
        return
    except ImportError:
        pass

    exe = shutil.which("garmin-mcp")
    if exe:
        real = os.path.realpath(exe)  # symlink uv -> bin/garmin-mcp
        for name in ("python3", "python"):
            py = os.path.join(os.path.dirname(real), name)
            if os.path.exists(py):
                r = subprocess.run([py, os.path.abspath(__file__)] + argv)
                sys.exit(r.returncode)

    print(
        "ERREUR : module 'garminconnect' introuvable dans cet interpréteur.\n"
        "→ utilisez le python de garmin-mcp : --python ~/.local/share/uv/tools/garmin-mcp/bin/python3",
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


def _download_one(client, activity_id: int, out_dir: Path, want_json: bool) -> Path:
    from garminconnect import Garmin

    fit = client.download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    fit = _unwrap_fit(fit)

    out = out_dir / f"{activity_id}.fit"
    out.write_bytes(fit)
    print(f"OK {len(fit):,} octets -> {out}")

    if want_json and fit:
        _write_records_json(fit, out.with_suffix(".records.json"))
    return out


def _write_records_json(fit: bytes, out: Path) -> None:
    """Extrait les records (timestamp, lat/long, altitude, FC, cadence, power) → JSON."""
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
    out.write_text(json.dumps(records, default=str))
    print(f"OK {len(records)} records -> {out}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Télécharge des fichiers FIT Garmin (bypass MCP) via garminconnect + tokens locaux."
    )
    ap.add_argument("activity_ids", nargs="*", type=int, help="IDs Garmin à télécharger")
    ap.add_argument("--output-dir", type=Path, default=None, help="Répertoire de sortie (défaut: activities/)")
    ap.add_argument("--json", action="store_true", help="Écrit aussi <id>.records.json")
    ap.add_argument("--overwrite", action="store_true", help="Réécrire même si présent")
    ap.add_argument("--from-dir", type=Path, default=None, help="Scan de fichiers MD pour activity_id")
    ap.add_argument("--python", type=Path, default=None, help="Interpréteur garminconnect (override)")
    args = ap.parse_args(argv)

    if args.python:
        os.environ["GARMIN_PYTHON"] = str(args.python)
    _auto_relaunch(sys.argv[1:])

    ids: list[int] = list(args.activity_ids)
    if args.from_dir:
        for md in args.from_dir.glob("*.md"):
            txt = md.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"activity_id:\s*(\d+)", txt)
            if m:
                ids.append(int(m.group(1)))
        ids = sorted(set(ids))
    if not ids:
        ap.error("aucun activity_id fourni (args ou --from-dir)")

    out_dir = args.output_dir or _activity_dir_out()
    out_dir.mkdir(parents=True, exist_ok=True)

    token_dir = str(Path("~/.garminconnect").expanduser())
    from garminconnect import Garmin

    client = Garmin()
    _login(client, token_dir)

    ok = 0
    for aid in ids:
        dst = out_dir / f"{aid}.fit"
        if dst.exists() and not args.overwrite and not args.json:
            print(f"skip {aid} (existe) — --overwrite pour forcer")
            continue
        try:
            _download_one(client, aid, out_dir, args.json)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {aid}: {e}", file=sys.stderr)
    print(f"{ok}/{len(ids)} téléchargements OK dans {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())