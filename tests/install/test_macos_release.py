"""Exécute les étapes CI de publication avec de faux DMG et un signataire isolé."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
GITHUB = ROOT / '.github/workflows/macos-dmg.yml'
CIRCLE = ROOT / '.circleci/config.yml'


def step_command(path: Path, name: str) -> str:
    text = path.read_text()
    block = text.split(f'name: {name}\n', 1)[1]
    match = re.search(r'(?m)^( +)(?:command|run): \|\n', block)
    if not match:
        raise ValueError(f'étape sans commande : {name}')
    indent = len(match.group(1)) + 2
    lines = []
    for line in block[match.end():].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        lines.append(line[indent:])
    return '\n'.join(lines) + '\n'


class TestMacReleaseSigning(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='arc-release-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.envfile = self.root / 'environment'
        self.envfile.touch()
        self.env = dict(os.environ, GITHUB_ENV=str(self.envfile), BASH_ENV=str(self.envfile),
                        GITHUB_REPOSITORY='example/coach', GH_REPO='example/coach',
                        TAG='v2.3.4', RELEASE_TAG='v2.3.4', PUBLIC_KEY='public-key-for-test',
                        PRIVATE_KEY='private-key-for-test', SPARKLE_PUBLIC_KEY='public-key-for-test',
                        SPARKLE_PRIVATE_KEY='private-key-for-test')
        self.env.pop('ARC_SIGNED_RELEASE', None)

    def run_step(self, path, name, **env):
        return subprocess.run(['/bin/bash', '-c', step_command(path, name)], cwd=self.root,
                              env=dict(self.env, **env), capture_output=True, text=True)

    def test_circle_enables_updates_without_apple_and_never_persists_private_key(self):
        result = self.run_step(CIRCLE, 'Configurer la signature Sparkle')
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.envfile.read_text()
        self.assertIn('ARC_SPARKLE_PUBLIC_KEY=public-key-for-test', output)
        self.assertIn('https://github.com/example/coach/releases/latest/download/appcast.xml', output)
        self.assertNotIn('private-key-for-test', output + result.stdout + result.stderr)

    def test_circle_requires_both_keys(self):
        for field in ('SPARKLE_PUBLIC_KEY', 'SPARKLE_PRIVATE_KEY'):
            with self.subTest(field=field):
                result = self.run_step(CIRCLE, 'Configurer la signature Sparkle', **{field: ''})
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.envfile.read_text(), '')

    def test_github_enables_updates_without_apple(self):
        result = self.run_step(GITHUB, 'Configurer les mises à jour des versions publiées')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.envfile.read_text()
        self.assertIn('ARC_SPARKLE_PUBLIC_KEY=public-key-for-test', data)
        self.assertNotIn('private-key-for-test', data + result.stdout + result.stderr)

    def test_github_requires_both_keys(self):
        for field in ('PUBLIC_KEY', 'PRIVATE_KEY'):
            with self.subTest(field=field):
                result = self.run_step(GITHUB, 'Configurer les mises à jour des versions publiées', **{field: ''})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('ARC_SPARKLE_PUBLIC_KEY=', self.envfile.read_text())

    def test_final_filename_is_fixed_before_signing_for_both_ci_services(self):
        for path in (CIRCLE, GITHUB):
            text = path.read_text()
            with self.subTest(ci=path):
                self.assertLess(text.index('name: Nommer le DMG'), text.index('name: Signer le flux'))
                sign = text.split('name: Signer le flux', 1)[1].split('run: |', 1)[0]
                self.assertNotIn("env.ARC_SIGNED_RELEASE == 'true'", sign)

    def test_unsigned_dmg_checksum_and_signing_use_published_filename(self):
        # Le signataire de test enregistre les arguments et reçoit la clé sur stdin.
        # Les vraies signatures sont également vérifiées par test-macos-update.sh.
        tools = self.root / 'tools/bin'
        tools.mkdir(parents=True)
        signer = tools / 'generate_appcast'
        signer.write_text('''#!/usr/bin/env python3
import json, pathlib, sys
out = pathlib.Path(sys.argv[-1])
(out / 'call.json').write_text(json.dumps({'args': sys.argv[1:], 'key': sys.stdin.read(),
    'dmgs': [p.name for p in out.glob('*.dmg')]}))
(out / 'appcast.xml').write_text('<rss/>')
''')
        signer.chmod(0o755)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        fetch = scripts / 'fetch-sparkle.sh'
        fetch.write_text('#!/bin/bash\nprintf "%s\\n" "$PWD/tools"\n')
        fetch.chmod(0o755)
        for path in (CIRCLE, GITHUB):
            with self.subTest(ci=path):
                dist = self.root / 'dist'
                if dist.exists():
                    shutil.rmtree(dist)
                self.envfile.write_text('')
                dist.mkdir()
                source = dist / 'AI-Running-Coach-2.3.4.dmg'
                source.write_bytes(b'test-dmg')
                result = self.run_step(path, 'Nommer le DMG et calculer son empreinte')
                self.assertEqual(result.returncode, 0, result.stderr)
                name = 'AI-Running-Coach-2.3.4-unsigned.dmg'
                self.assertTrue((dist / name).exists())
                self.assertEqual((dist / (name + '.sha256')).read_text().split()[0],
                                 hashlib.sha256(b'test-dmg').hexdigest())
                result = self.run_step(path, 'Signer le flux de mises à jour', ARC_DMG_NAME=name)
                self.assertEqual(result.returncode, 0, result.stderr)
                call = json.loads((dist / 'updates/call.json').read_text())
                self.assertEqual(call['dmgs'], [name])
                self.assertEqual(call['key'], 'private-key-for-test')
                self.assertIn('https://github.com/example/coach/releases/download/v2.3.4/', call['args'])
                self.assertIn('--ed-key-file', call['args'])
                self.assertNotIn('private-key-for-test', call['args'])
                self.assertNotIn('private-key-for-test', result.stdout + result.stderr)

    def test_circle_publication_uploads_feed_with_dmg(self):
        publish = step_command(CIRCLE, 'Publier sur la release GitHub')
        self.assertIn('"dist/updates/appcast.xml" --clobber', publish)

    def test_circle_fallback_marks_prereleases(self):
        command = step_command(CIRCLE, 'Attendre la release GitHub (créée par « Tag a release »)')
        self.assertIn('args+=(--prerelease)', command)

    def test_github_apple_signed_artifact_keeps_original_name(self):
        dist = self.root / 'dist'
        dist.mkdir()
        original = dist / 'AI-Running-Coach-2.3.4.dmg'
        original.write_bytes(b'test-dmg')
        result = self.run_step(GITHUB, 'Nommer le DMG et calculer son empreinte', ARC_SIGNED_RELEASE='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(original.exists())
        self.assertIn('ARC_DMG_NAME=AI-Running-Coach-2.3.4.dmg', self.envfile.read_text())
