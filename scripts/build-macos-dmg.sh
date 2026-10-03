#!/usr/bin/env bash
# Construit l'application/lanceur macOS et son image DMG.
# Signature publique optionnelle : ARC_CODESIGN_IDENTITY + ARC_NOTARY_PROFILE.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_DIR="$ROOT/macos/AI-Running-Coach"
VERSION="$(sed -n 's/^VERSION="\([^"]*\)"/\1/p' "$ROOT/install.sh" | head -1)"
[[ -n "$VERSION" ]] || { echo "Version introuvable dans install.sh" >&2; exit 1; }

BUILD_ROOT="$ROOT/dist/macos-build"
APP_NAME="AI Running Coach"
APP="$BUILD_ROOT/$APP_NAME.app"
CONTENTS="$APP/Contents"
RESOURCES="$CONTENTS/Resources"
DMG="$ROOT/dist/AI-Running-Coach-$VERSION.dmg"
PAYLOAD="$RESOURCES/engine.tar.gz"

[[ "$(uname -s)" == "Darwin" ]] || { echo "La construction du DMG nécessite macOS." >&2; exit 1; }
for tool in swiftc hdiutil codesign iconutil qlmanage sips lipo shasum; do
    command -v "$tool" >/dev/null 2>&1 || { echo "$tool est requis." >&2; exit 1; }
done

mkdir -p "$ROOT/dist"
if [[ -e "$BUILD_ROOT" ]]; then
    # Le dossier ne contient que les sorties de ce script, jamais des données utilisateur.
    find "$BUILD_ROOT" -depth -mindepth 1 -delete
fi
mkdir -p "$CONTENTS/MacOS" "$RESOURCES"

echo "→ Compilation de l'application"
ARM_BINARY="$BUILD_ROOT/app-arm64"
INTEL_BINARY="$BUILD_ROOT/app-x86_64"
for arch in arm64 x86_64; do
    output="$ARM_BINARY"
    [[ "$arch" == "x86_64" ]] && output="$INTEL_BINARY"
    swiftc -swift-version 5 -O -parse-as-library \
        -target "$arch-apple-macos13.0" \
        -framework SwiftUI -framework AppKit \
        "$SOURCE_DIR/AI_Running_CoachApp.swift" \
        -o "$output"
done
lipo -create "$ARM_BINARY" "$INTEL_BINARY" -output "$CONTENTS/MacOS/$APP_NAME"

echo "→ Création de l'icône"
ICON_WORK="$BUILD_ROOT/icon-work"
ICONSET="$ICON_WORK/AppIcon.iconset"
mkdir -p "$ICONSET"
qlmanage -t -s 1024 -o "$ICON_WORK" "$ROOT/web/favicon.svg" >/dev/null 2>&1
ICON_SOURCE="$ICON_WORK/favicon.svg.png"
for spec in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" "64 icon_32x32@2x" "128 icon_128x128" "256 icon_128x128@2x" "256 icon_256x256" "512 icon_256x256@2x" "512 icon_512x512" "1024 icon_512x512@2x"; do
    size="${spec%% *}"
    name="${spec#* }"
    sips -z "$size" "$size" "$ICON_SOURCE" --out "$ICONSET/$name.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$RESOURCES/AppIcon.icns"

echo "→ Embarquement du moteur"
# La liste vient de Git : aucun cache, secret ou fichier personnel non suivi ne
# peut se glisser dans un DMG construit depuis un poste de développement.
git -C "$ROOT" ls-files -z -- \
    . \
    ':(exclude)activities/**' \
    ':(exclude)medical/**' \
    ':(exclude)nutrition/**' \
    ':(exclude)planning/**' \
    ':(exclude)rapports/**' \
    ':(exclude)gear/**' \
    ':(exclude)resources/**' \
    ':(exclude)config/workspace.user.toml' \
    ':(exclude)logs/**' \
    ':(exclude)tests/**' \
    ':(exclude)macos/**' \
    ':(exclude).github/workflows/**' \
    ':(exclude).impeccable/**' \
    | tar --null -czf "$PAYLOAD" -C "$ROOT" -T -

# Le numéro fonctionnel peut rester identique entre deux itérations d'un même
# DMG. L'empreinte du moteur permet alors à l'application de voir que les
# fichiers embarqués ont changé et d'actualiser sa copie dans Application Support.
BUILD_NUMBER="${GITHUB_RUN_NUMBER:-1}"
ENGINE_BUILD="$(shasum -a 256 "$PAYLOAD" | awk '{print $1}')"
sed -e "s/__VERSION__/$VERSION/g" \
    -e "s/__BUILD__/$BUILD_NUMBER/g" \
    -e "s/__ENGINE_BUILD__/$ENGINE_BUILD/g" \
    "$SOURCE_DIR/Info.plist" > "$CONTENTS/Info.plist"

IDENTITY="${ARC_CODESIGN_IDENTITY:--}"
echo "→ Signature de l'application"
codesign --force --deep --options runtime --timestamp --sign "$IDENTITY" "$APP"

STAGE="$BUILD_ROOT/dmg"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/Applications"

if [[ -f "$DMG" ]]; then
    mv "$DMG" "$DMG.previous"
fi
echo "→ Création du DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
codesign --force --timestamp --sign "$IDENTITY" "$DMG"

if [[ -n "${ARC_NOTARY_PROFILE:-}" ]]; then
    [[ "$IDENTITY" != "-" ]] || { echo "ARC_NOTARY_PROFILE exige une vraie identité ARC_CODESIGN_IDENTITY." >&2; exit 1; }
    echo "→ Notarisation Apple"
    xcrun notarytool submit "$DMG" --keychain-profile "$ARC_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
fi

[[ ! -f "$DMG.previous" ]] || rm -f "$DMG.previous"
echo "✓ DMG prêt : $DMG"
