"""Palier B — la garde de `scripts/migrate-sync-127.sh` reconnaît les messages réels d'install.sh.

La migration refuse de mémoriser `install-args` si l'aperçu `install.sh --dry-run` annonce une
planification conservée, périmée retirée ou remplacée. Si un message d'install.sh est reformulé sans
que le motif suive, ce filet de sécurité devient muet : ce test extrait chaque `warn`/`log` concerné et
vérifie que le motif de la garde le reconnaît.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
INSTALL = REPO / "install.sh"
MIGRATE = REPO / "scripts" / "migrate-sync-127.sh"

EMIT = re.compile(r'^\s*(?:warn|log)\s+"(?P<msg>.*)"\s*(?:;;)?\s*$')
KEPT = re.compile(r"lanification", re.I)
KEPT_WORD = re.compile(r"conserv", re.I)
STALE = re.compile(r"p[ée]rim|retir[ée]e|remplac[ée]", re.I)
STALE_CTX = re.compile(r"cron|LaunchAgent|planification", re.I)


def _guard_pattern() -> str:
    m = re.search(r"^SCHEDULE_NOTICE_RE='([^']+)'", MIGRATE.read_text(encoding="utf-8"), re.M)
    assert m, "SCHEDULE_NOTICE_RE introuvable dans migrate-sync-127.sh"
    return m.group(1)


def _render(msg: str) -> str:
    return re.sub(r"\$\{?[A-Za-z_][A-Za-z_0-9]*\}?|\$\([^)]*\)", "PLACEHOLDER", msg).replace("\\$", "$")


def _schedule_messages() -> list:
    out = []
    for n, line in enumerate(INSTALL.read_text(encoding="utf-8").splitlines(), 1):
        m = EMIT.match(line)
        if not m:
            continue
        msg = m.group("msg")
        if line.lstrip().startswith("log") or line.lstrip().startswith("warn"):
            kept = KEPT.search(msg) and KEPT_WORD.search(msg)
            stale = STALE.search(msg) and STALE_CTX.search(msg) and not msg.lstrip().startswith("Pour ")
            if kept or stale:
                out.append((n, _render(msg)))
    return out


class TestMigrateGuardMatchesInstall(unittest.TestCase):
    def test_messages_are_found(self):
        self.assertGreaterEqual(len(_schedule_messages()), 6)

    def test_guard_matches_every_schedule_notice(self):
        pat = _guard_pattern()
        for n, msg in _schedule_messages():
            for env in ({"LC_ALL": "C"}, {"LC_ALL": "en_US.UTF-8"}):
                r = subprocess.run(["grep", "-qE", pat], input=msg.encode("utf-8"),
                                   env={"PATH": "/usr/bin:/bin", **env})
                self.assertEqual(r.returncode, 0, f"install.sh:{n} non reconnu par la garde ({env}) : {msg}")

    def test_guard_ignores_unrelated_lines(self):
        pat = _guard_pattern()
        for msg in ("Workspace mémorisé conservé : x", "heures fixes conservées ([sync].times)"):
            r = subprocess.run(["grep", "-qE", pat], input=msg.encode("utf-8"))
            self.assertEqual(r.returncode, 1, msg)


if __name__ == "__main__":
    unittest.main()
