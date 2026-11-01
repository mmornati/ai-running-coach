"""Pièces jointes du chat coach (#342) : liste blanche par contenu, nom généré, rangement sûr.

Utilisé par `scripts/arc_chat.py` (route `POST /api/chat/sessions/<id>/attachments`). Rien ici ne
touche au réseau : seulement des fonctions pures et l'écriture dans une boîte de dépôt du workspace.

Principes (deploy/chat/SPEC.md, « Pièces jointes ») :
- l'extension DOIT concorder avec le contenu (`.gpx` avec un PNG dedans → refus, et inversement) ;
- le nom du client ne sert qu'à l'extension et à un « slug » ASCII : jamais utilisé comme chemin ;
- le XML (GPX/TCX) est lu sans DTD ni entité : tout `<!DOCTYPE` / `<!ENTITY` est refusé ;
- écriture atomique (fichier temporaire du même dossier, puis rename), jamais d'écrasement ;
- le dossier de dépôt doit se résoudre exactement sous le workspace (liens symboliques refusés).

Bibliothèque standard uniquement.
"""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote

DEFAULT_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 10
CHUNK = 64 * 1024

# Extension (minuscules) → (type de pièce jointe, dossier de dépôt relatif au workspace).
EXTENSIONS = {
    ".gpx": ("gpx", "planning/inbox"),
    ".tcx": ("tcx", "planning/inbox"),
    ".fit": ("fit", "planning/inbox"),
    ".jpg": ("image", "gear/photos"),
    ".jpeg": ("image", "gear/photos"),
    ".png": ("image", "gear/photos"),
    ".webp": ("image", "gear/photos"),
}
# Extension normalisée écrite sur le disque (`.jpeg` et `.jpg` donnent `.jpg`).
NORMAL_EXT = {".jpeg": ".jpg"}
HEIC_EXTENSIONS = (".heic", ".heif")
HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1")
HEIC_MESSAGE = "Format HEIC/HEIF non pris en charge : exportez la photo en JPEG (Réglages de l'appareil photo > Formats > Le plus compatible) puis joignez-la à nouveau."
XML_ROOTS = {"gpx": "gpx", "tcx": "TrainingCenterDatabase"}
_XML_DANGER = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class UploadError(Exception):
    """Refus d'une pièce jointe : `status` HTTP et message en français destiné à l'athlète."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Nom d'origine → extension et « slug »
# ---------------------------------------------------------------------------

def decode_filename(header: Optional[str]) -> str:
    """Valeur de `X-Filename` (URL-encodée) décodée ; jamais utilisée comme chemin."""
    return unquote(header or "", errors="replace")[:4096]


def split_filename(name: str) -> Tuple[str, str]:
    """(radical, extension en minuscules avec le point) du dernier composant du nom client.

    `../a/b\\c.GPX` → (`c`, `.gpx`). Les séparateurs, les NUL et les contrôles sont écartés AVANT
    de chercher l'extension : un nom malveillant ne peut pas influencer autre chose que le slug."""
    base = re.split(r"[/\\]", name.replace("\x00", ""))[-1]
    base = "".join(c for c in base if c.isprintable()).strip()
    suffix = Path(base).suffix.lower()
    stem = base[: len(base) - len(suffix)] if suffix else base
    return stem, suffix


def slugify(stem: str, limit: int = 40) -> str:
    """Slug ASCII court (`Sortie Longue à Tournai` → `sortie-longue-a-tournai`), `fichier` à défaut."""
    ascii_text = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:limit].strip("-")
    return slug or "fichier"


def classify_name(name: str) -> Tuple[str, str, str, str]:
    """(type, dossier, extension normalisée, slug) d'après le nom client ; `UploadError` sinon.

    Appelée AVANT de lire le corps : un type refusé n'envoie pas 20 Mo pour rien."""
    stem, suffix = split_filename(name)
    if suffix in HEIC_EXTENSIONS:
        raise UploadError(415, HEIC_MESSAGE)
    if suffix not in EXTENSIONS:
        allowed = ", ".join(sorted({e.lstrip(".") for e in EXTENSIONS}))
        raise UploadError(415, f"Type de fichier non pris en charge ({suffix or 'sans extension'}) : "
                               f"formats acceptés : {allowed}.")
    kind, folder = EXTENSIONS[suffix]
    return kind, folder, NORMAL_EXT.get(suffix, suffix), slugify(stem)


# ---------------------------------------------------------------------------
# Contrôle du CONTENU (l'extension doit concorder)
# ---------------------------------------------------------------------------

class _RootOnly:
    """Cible d'analyseur XML qui ne garde rien : seulement le nom de la racine (mémoire constante)."""

    def __init__(self):
        self.root = None

    def start(self, tag, attrib):
        if self.root is None:
            self.root = tag.rsplit("}", 1)[-1]

    def end(self, tag):
        pass

    def data(self, data):
        pass

    def close(self):
        return self.root


def check_xml(path: Path, kind: str) -> None:
    """GPX/TCX : XML bien formé, sans DTD ni entité, racine attendue. Lecture par morceaux."""
    tail = b""
    target = _RootOnly()
    parser = ET.XMLParser(target=target)
    mismatch = UploadError(415, f"Le contenu n'est pas un fichier {kind.upper()} valide.")
    try:
        with open(path, "rb") as handle:
            first = True
            while True:
                chunk = handle.read(CHUNK)
                if not chunk:
                    break
                if first:
                    first = False
                    if chunk[:2] in (b"\xff\xfe", b"\xfe\xff") or chunk[:4] == b"\x00\x00\xfe\xff":
                        raise UploadError(415, "Encodage XML non pris en charge : enregistrez le fichier en UTF-8.")
                if b"\x00" in chunk:
                    raise mismatch
                if _XML_DANGER.search(tail + chunk):
                    raise UploadError(415, "Déclaration DOCTYPE / ENTITY refusée dans un fichier XML (sécurité).")
                tail = chunk[-16:]
                parser.feed(chunk)
            parser.close()
    except UploadError:
        raise
    except (ET.ParseError, ValueError, LookupError):
        raise mismatch from None
    except OSError:
        raise UploadError(500, "Lecture du fichier reçu impossible.") from None
    if target.root != XML_ROOTS[kind]:
        raise mismatch


def sniff(path: Path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(64)


def check_content(path: Path, kind: str, ext: str) -> None:
    """Concordance extension / contenu ; lève `UploadError(415, …)`."""
    if kind in XML_ROOTS:
        check_xml(path, kind)
        return
    head = sniff(path)
    if kind == "fit":
        # En-tête FIT : octet 0 = taille (12 ou 14), octets 8-11 = « .FIT ».
        ok = len(head) >= 12 and head[0] in (12, 14) and head[8:12] == b".FIT"
        if not ok:
            raise UploadError(415, "Le contenu n'est pas un fichier FIT valide.")
        return
    if head[4:8] == b"ftyp" and head[8:12] in HEIC_BRANDS:
        raise UploadError(415, HEIC_MESSAGE)
    magic_ok = {
        ".jpg": head[:3] == b"\xff\xd8\xff",
        ".png": head[:8] == PNG_MAGIC,
        ".webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP",
    }.get(ext, False)
    if not magic_ok:
        raise UploadError(415, f"Le contenu ne correspond pas à l'extension {ext}.")


# ---------------------------------------------------------------------------
# Rangement
# ---------------------------------------------------------------------------

def safe_folder(workspace: Path, rel: str) -> Path:
    """Dossier de dépôt `workspace/rel` (créé au besoin), sans jamais suivre de lien symbolique.

    Chaque composant est contrôlé AVANT d'être créé : un lien symbolique (même vers un dossier
    valide) est refusé et rien n'est créé au-delà ; la résolution réelle doit enfin être exactement
    `<workspace réel>/rel` (même règle que `gear_photo_file` pour la lecture)."""
    try:
        current = Path(workspace).resolve(strict=True)
        for part in rel.split("/"):
            current = current / part
            if current.is_symlink():
                raise OSError("lien symbolique")
            if not current.exists():
                current.mkdir()
            elif not current.is_dir():
                raise OSError("pas un dossier")
        if current.resolve(strict=True) != current:
            raise OSError("résolution inattendue")
    except OSError:
        raise UploadError(500, "Dossier de dépôt indisponible ou invalide dans le workspace.") from None
    return current


def new_temp(folder: Path) -> Tuple[int, str]:
    """Fichier temporaire (mode 600, caché) dans le dossier de destination, pour un rename atomique."""
    return tempfile.mkstemp(prefix=".upload-", suffix=".tmp", dir=folder)


def publish(tmp: str, folder: Path, slug: str, ext: str, now: Optional[datetime] = None) -> str:
    """Donne à `tmp` son nom définitif `AAAA-MM-JJ_HHMMSS_<slug><ext>` sans jamais écraser :
    réservation exclusive (`O_EXCL`), suffixes `-2`, `-3`… puis rename atomique. Renvoie le nom."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    for index in range(1, 1000):
        name = f"{stamp}_{slug}{'' if index == 1 else f'-{index}'}{ext}"
        try:
            fd = os.open(folder / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        os.replace(tmp, folder / name)       # remplace NOTRE réservation vide, jamais un fichier existant
        return name
    raise UploadError(409, "Trop de fichiers du même nom : réessayez dans une seconde.")
