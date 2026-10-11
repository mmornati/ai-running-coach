#!/usr/bin/env python3
"""Prépare les métadonnées macOS et refuse une configuration Sparkle incomplète."""
import argparse
import base64
import os
from pathlib import Path
import plistlib
import re
from urllib.parse import urlparse


def configure(template, *, version, build, engine_hash, public_key="", feed_url=""):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("Version attendue : X.Y.Z, avec suffixe facultatif.")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", build):
        raise ValueError("Numéro de construction invalide.")
    result = dict(template)
    result.update(CFBundleShortVersionString=version, CFBundleVersion=f"{version}.{build}", ARCEngineBuild=engine_hash)
    if bool(public_key) != bool(feed_url):
        raise ValueError("La clé publique Sparkle et l’URL du flux doivent être configurées ensemble.")
    if public_key:
        if len(base64.b64decode(public_key, validate=True)) != 32:
            raise ValueError("La clé publique Sparkle doit contenir 32 octets.")
        url = urlparse(feed_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Le flux Sparkle doit être une URL HTTPS sans identifiants.")
        result.update(SUPublicEDKey=public_key, SUFeedURL=feed_url,
                      SUEnableAutomaticChecks=True, SUAutomaticallyUpdate=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--engine-hash", required=True)
    args = parser.parse_args()
    data = configure(plistlib.loads(args.template.read_bytes()), version=args.version, build=args.build,
                     engine_hash=args.engine_hash, public_key=os.environ.get("ARC_SPARKLE_PUBLIC_KEY", ""),
                     feed_url=os.environ.get("ARC_UPDATE_FEED_URL", ""))
    args.output.write_bytes(plistlib.dumps(data))


if __name__ == "__main__":
    main()
