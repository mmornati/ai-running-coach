"""Palier B — pièges du bash 3.2 de macOS dans les scripts shell.

Dans une locale UTF-8, bash 3.2 lit le premier octet d'un caractère non ASCII collé à
une variable (`"$target…"`) comme une partie de son nom : `target\\xe2: unbound variable`
sous `set -u`. Bash 4+ ne le fait pas, d'où un échec invisible sous Linux. Écrire
`${target}…`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UNBRACED_THEN_NON_ASCII = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]")


def shell_files() -> list:
    files = [REPO / "install.sh", *sorted((REPO / "scripts").glob("*.sh")),
             *sorted((REPO / "scripts/lib").glob("*.sh")), *sorted((REPO / "tests/lib/stubs").iterdir())]
    return [p for p in files if p.is_file()]


class TestBash32(unittest.TestCase):
    def test_no_unbraced_variable_followed_by_non_ascii(self):
        found = []
        for path in shell_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for match in UNBRACED_THEN_NON_ASCII.finditer(line):
                    found.append(f"{path.relative_to(REPO)}:{number}: {match.group(0)}")
        self.assertFalse(found, "variable collée à un caractère non ASCII — écrire ${nom} :\n  " + "\n  ".join(found))


if __name__ == "__main__":
    unittest.main()
