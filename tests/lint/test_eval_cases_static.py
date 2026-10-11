"""Palier B — contrôles statiques des cas d'éval, sans modèle.

`tests/evals/test_evals.py` mêle deux natures de tests : `TestPromptBehaviour`
(palier C, facturé, lancé seulement sur étiquette `run-evals`) et trois classes
déterministes et gratuites qui valident la FORME des cas (`cases/*.toml`,
fixtures à dates relatives, `unchanged_files`). Rangées au palier C, ces
dernières ne tournaient jamais en CI : un cas mal formé (p. ex. un
`sqlite_query` avec `min` ET `max`) passait la revue et ne cassait qu'au
prochain run d'évals. Les ré-exporter ici les fait découvrir au palier B, à
chaque poussée. (Avec `--tier all`, elles tournent deux fois — sans effet.)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from tests.evals.test_evals import (  # noqa: E402,F401 — ré-export pour la découverte
    TestCaseFilesAreValid,
    TestRelativeDateFixtures,
    TestUnchangedFiles,
)
