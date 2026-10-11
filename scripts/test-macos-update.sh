#!/usr/bin/env bash
# Deux vrais DMG de test ; aucune installation, aucun compte ni trousseau modifiés.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/arc-update-test.XXXXXX")"
trap 'rm -rf "$TEST_ROOT"' EXIT
umask 077
cat > "$TEST_ROOT/keys.swift" <<'SWIFT'
import CryptoKit
import Foundation
let directory = URL(fileURLWithPath: CommandLine.arguments[1])
let key = Curve25519.Signing.PrivateKey()
try key.rawRepresentation.base64EncodedString().write(to: directory.appendingPathComponent("private.key"), atomically: true, encoding: .utf8)
try key.publicKey.rawRepresentation.base64EncodedString().write(to: directory.appendingPathComponent("public.key"), atomically: true, encoding: .utf8)
SWIFT
swift "$TEST_ROOT/keys.swift" "$TEST_ROOT"
export ARC_SPARKLE_PUBLIC_KEY
ARC_SPARKLE_PUBLIC_KEY="$(cat "$TEST_ROOT/public.key")"
export ARC_UPDATE_FEED_URL="https://example.invalid/appcast.xml"
export ARC_CODESIGN_IDENTITY=-
unset ARC_NOTARY_PROFILE
mkdir -p "$TEST_ROOT/updates"
for version in 0.0.1-test 0.0.2-test; do
    ARC_APP_VERSION="$version" scripts/build-macos-dmg.sh
    # Le vrai exécutable doit charger Sparkle avec sa signature finale. Une
    # simple compilation ne détecte pas un refus de bibliothèque par dyld.
    python3 - <<'PYTEST'
import subprocess
subprocess.run(['dist/macos-build/AI Running Coach.app/Contents/MacOS/AI Running Coach',
                '--smoke-test'], check=True, timeout=15)
PYTEST
    cp "dist/AI-Running-Coach-$version.dmg" "$TEST_ROOT/updates/"
    if [[ "$version" == 0.0.1-test ]]; then
        ditto "dist/macos-build/AI Running Coach.app" "$TEST_ROOT/Previous.app"
    fi
done
SPARKLE_DIR="$(scripts/fetch-sparkle.sh)"
"$SPARKLE_DIR/bin/generate_appcast" --ed-key-file "$TEST_ROOT/private.key" \
    --maximum-deltas 0 --download-url-prefix "https://example.invalid/" "$TEST_ROOT/updates"
swiftc -F "$SPARKLE_DIR" -framework Sparkle -Xlinker -rpath -Xlinker "$SPARKLE_DIR" \
    tests/macos/ProbeUpdate.swift -o "$TEST_ROOT/probe"
python3 - "$TEST_ROOT" "$SPARKLE_DIR" <<'PY'
from pathlib import Path
import plistlib
import functools
import http.server
import threading
import uuid
from tests.lib.local_http import ThreadingHTTPServer
import subprocess
import sys
import xml.etree.ElementTree as ET
root, sparkle = map(Path, sys.argv[1:])
ns = '{http://www.andymatuschak.org/xml-namespaces/sparkle}'
feed = ET.parse(root / 'updates/appcast.xml')
items = feed.findall('./channel/item')
assert len(items) == 2, 'Les deux versions doivent être présentes dans le flux.'
assert items[0].findtext(ns + 'shortVersionString') == '0.0.2-test'
old = plistlib.loads((root / 'Previous.app/Contents/Info.plist').read_bytes())
assert old['CFBundleShortVersionString'] == '0.0.1-test'
assert old['SUPublicEDKey'] == (root / 'public.key').read_text()
# Un identifiant unique empêche la sonde de lire/écrire les préférences de l'app réelle.
old['CFBundleIdentifier'] = 'org.example.arc-update-test.' + uuid.uuid4().hex
old['SUEnableAutomaticChecks'] = False
old_path = root / 'Previous.app/Contents/Info.plist'
old_path.write_bytes(plistlib.dumps(old))
subprocess.run(['codesign', '--force', '--sign', '-', str(root / 'Previous.app')], check=True)
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root / 'updates'))
server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    subprocess.run([str(root / 'probe'), str(root / 'Previous.app'),
                    f'http://127.0.0.1:{server.server_port}/appcast.xml', '0.0.2-test'], check=True, timeout=40)
    old['CFBundleVersion'] = items[0].findtext(ns + 'version')
    old_path.write_bytes(plistlib.dumps(old))
    subprocess.run(['codesign', '--force', '--sign', '-', str(root / 'Previous.app')], check=True)
    subprocess.run([str(root / 'probe'), str(root / 'Previous.app'),
                    f'http://127.0.0.1:{server.server_port}/appcast.xml', 'none'], check=True, timeout=40)
finally:
    server.shutdown()
    server.server_close()
    thread.join()
    subprocess.run(['/usr/bin/defaults', 'delete', old['CFBundleIdentifier']], capture_output=True)
architectures = subprocess.check_output(['lipo', '-archs',
    str(root / 'Previous.app/Contents/MacOS/AI Running Coach')], text=True).split()
assert set(architectures) == {'arm64', 'x86_64'}, architectures
for item in items:
    enclosure = item.find('enclosure')
    archive = root / 'updates' / enclosure.get('url').rsplit('/', 1)[1]
    assert archive.stat().st_size == int(enclosure.get('length'))
    command = [str(sparkle / 'bin/sign_update'), '--verify', '--ed-key-file', str(root / 'private.key'),
               str(archive), enclosure.get(ns + 'edSignature')]
    subprocess.run(command, check=True)
    with archive.open('ab') as stream:
        stream.write(b'alteration')
    result = subprocess.run(command, capture_output=True)
    assert result.returncode != 0, 'Un DMG altéré ne doit jamais être accepté.'
print('Deux DMG universels vérifiés ; signatures valides ; archives altérées refusées.')
PY
