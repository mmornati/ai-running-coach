"""Métadonnées de distribution : versions ordonnées et flux signé configurable."""
import base64
import importlib.util
from pathlib import Path
import plistlib
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("macos_plist", ROOT / "scripts/arc_macos_plist.py")
plist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plist)


class TestMacUpdateMetadata(unittest.TestCase):
    def config(self, **overrides):
        args = dict(version="1.2.3", build="12.1", engine_hash="abc")
        args.update(overrides)
        template = plistlib.loads((ROOT / "macos/AI-Running-Coach/Info.plist").read_bytes())
        return plist.configure(template, **args)

    def test_local_build_has_no_update_feed(self):
        result = self.config()
        self.assertNotIn("SUFeedURL", result)
        self.assertNotIn("SUPublicEDKey", result)

    def test_published_version_precedes_workflow_counter(self):
        result = self.config(version="2.0.0", build="1.1")
        self.assertEqual(result["CFBundleVersion"], "2.0.0.1.1")
        self.assertEqual(result["CFBundleShortVersionString"], "2.0.0")

    def test_signed_feed_enables_checks_but_installation_stays_opt_in(self):
        key = base64.b64encode(bytes(32)).decode()
        result = self.config(public_key=key, feed_url="https://example.org/appcast.xml")
        self.assertEqual(result["SUPublicEDKey"], key)
        self.assertTrue(result["SUEnableAutomaticChecks"])
        self.assertFalse(result["SUAutomaticallyUpdate"])
        self.assertEqual(plistlib.loads(plistlib.dumps(result)), result)

    def test_incomplete_or_invalid_update_config_is_rejected(self):
        key = base64.b64encode(bytes(32)).decode()
        for kwargs in (
            dict(public_key=key), dict(feed_url="https://example.org/feed"),
            dict(public_key="bad", feed_url="https://example.org/feed"),
            dict(public_key=key, feed_url="http://example.org/feed"),
            dict(public_key=key, feed_url="https://user:password@example.org/feed"),
            dict(version="main"), dict(build="oops"),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.config(**kwargs)

    def test_local_signing_does_not_enable_library_validation_without_team_id(self):
        build = (ROOT / "scripts/build-macos-dmg.sh").read_text()
        self.assertIn('if [[ "$IDENTITY" != "-" ]]; then', build)
        self.assertIn('SIGN_OPTIONS=(--options runtime --timestamp)', build)
        self.assertNotIn('codesign --force --options runtime --timestamp --sign "$IDENTITY" "$component"', build)

    def test_smoke_test_exits_before_starting_the_real_app(self):
        source = (ROOT / "macos/AI-Running-Coach/AI_Running_CoachApp.swift").read_text()
        entry = source.split('enum CoachEntryPoint {', 1)[1]
        self.assertLess(entry.index('"--smoke-test"'), entry.index('AIRunningCoachApp.main()'))
        test = (ROOT / "scripts/test-macos-update.sh").read_text()
        self.assertIn("'--smoke-test'], check=True, timeout=15", test)
