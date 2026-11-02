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

import contextlib
import os
import re
import secrets
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


def _opened(source):
    """`source` : chemin (ouvert ici) ou fichier binaire déjà ouvert (non refermé)."""
    if hasattr(source, "read"):
        source.seek(0)
        return contextlib.nullcontext(source)
    return open(source, "rb")


def check_xml(source, kind: str) -> None:
    """GPX/TCX : XML bien formé, sans DTD ni entité, racine attendue. Lecture par morceaux."""
    tail = b""
    target = _RootOnly()
    parser = ET.XMLParser(target=target)
    mismatch = UploadError(415, f"Le contenu n'est pas un fichier {kind.upper()} valide.")
    try:
        with _opened(source) as handle:
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


def sniff(source) -> bytes:
    with _opened(source) as handle:
        return handle.read(64)


def check_content(source, kind: str, ext: str) -> None:
    """Concordance extension / contenu ; lève `UploadError(415, …)`. `source` : chemin ou fichier ouvert."""
    if kind in XML_ROOTS:
        check_xml(source, kind)
        return
    head = sniff(source)
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

class DropFolder:
    """Dossier de dépôt `workspace/rel` ouvert par descripteur : tout se fait RELATIVEMENT à ce `dir_fd`.

    Chaque composant est ouvert avec `O_DIRECTORY | O_NOFOLLOW` (créé au besoin par `mkdir(dir_fd=)`) :
    un lien symbolique, même vers un dossier valide, est refusé, et un composant remplacé par un lien
    entre deux requêtes ne peut pas détourner l'écriture (création du temporaire, réservation du nom
    et rename passent par le même descripteur). Les fichiers sont créés avec le mode 0o666 : c'est
    l'umask du service qui règle les droits, comme pour le reste du workspace."""

    def __init__(self, workspace: Path, rel: str):
        self.rel = rel
        self.fd = -1
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(Path(workspace).resolve(strict=True), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            for part in rel.split("/"):
                try:
                    os.mkdir(part, 0o777, dir_fd=fd)
                except FileExistsError:
                    pass
                except OSError:
                    os.close(fd)
                    raise
                try:
                    nxt = os.open(part, flags, dir_fd=fd)
                finally:
                    os.close(fd)
                fd = nxt
        except OSError:
            raise UploadError(500, "Dossier de dépôt indisponible ou invalide dans le workspace.") from None
        self.fd = fd

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def new_temp(self) -> Tuple[int, str]:
        """(descripteur en écriture, nom) d'un fichier temporaire caché du dossier, pour un rename atomique."""
        for _ in range(20):
            name = f".upload-{secrets.token_hex(6)}.tmp"
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o666,
                             dir_fd=self.fd)
            except FileExistsError:
                continue
            return fd, name
        raise UploadError(500, "Création du fichier temporaire impossible.")

    def open_read(self, name: str):
        """Le fichier `name` du dossier, ouvert en lecture binaire (sans suivre de lien)."""
        return os.fdopen(os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=self.fd), "rb")

    def discard(self, name: str) -> None:
        try:
            os.unlink(name, dir_fd=self.fd)
        except OSError:
            pass

    def publish(self, tmp: str, slug: str, ext: str, now: Optional[datetime] = None) -> str:
        """Donne à `tmp` son nom définitif `AAAA-MM-JJ_HHMMSS_<slug><ext>` sans jamais écraser :
        réservation exclusive (`O_EXCL`), suffixes `-2`, `-3`… puis rename atomique. Renvoie le nom."""
        stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
        for index in range(1, 1000):
            name = f"{stamp}_{slug}{'' if index == 1 else f'-{index}'}{ext}"
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o666,
                             dir_fd=self.fd)
            except FileExistsError:
                continue
            os.close(fd)
            try:
                os.replace(tmp, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)   # remplace NOTRE réservation vide
            except OSError:
                self.discard(name)                   # ne laisse pas la réservation vide sur le disque
                raise
            return name
        raise UploadError(409, "Trop de fichiers du même nom : réessayez dans une seconde.")


def effective_limit(value) -> int:
    """Plafond d'envoi valide (> 0, entier), sinon le défaut : MÊME règle pour le chat et pour le proxy."""
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_UPLOAD_MAX_BYTES
    return number if number > 0 else DEFAULT_UPLOAD_MAX_BYTES


def format_size(n: int) -> str:
    """« 20 Mo » ou « 512 Ko » (Ko sous 1 Mio)."""
    return f"{n // (1024 * 1024)} Mo" if n >= 1024 * 1024 else f"{max(1, n // 1024)} Ko"
