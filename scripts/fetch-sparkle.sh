#!/usr/bin/env bash
# Dépendance binaire officielle, version et empreinte épinglées.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPARKLE_VERSION=2.10.0
SPARKLE_SHA256=c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c
DEST="$ROOT/dist/sparkle-$SPARKLE_VERSION"
ARCHIVE="$ROOT/dist/sparkle-$SPARKLE_VERSION.tar.xz"
mkdir -p "$ROOT/dist"
if [[ ! -f "$ARCHIVE" ]]; then
    curl --fail --location --silent --show-error \
        "https://github.com/sparkle-project/Sparkle/releases/download/$SPARKLE_VERSION/Sparkle-$SPARKLE_VERSION.tar.xz" \
        -o "$ARCHIVE.download"
    mv "$ARCHIVE.download" "$ARCHIVE"
fi
printf '%s  %s\n' "$SPARKLE_SHA256" "$ARCHIVE" | shasum -a 256 --check >&2
mkdir -p "$DEST"
tar -xf "$ARCHIVE" -C "$DEST"
printf '%s\n' "$DEST"
