"""Palier B — pas de sigles déposés par TrainingPeaks dans ce que l'athlète lit.

TSS, NP et IF sont des marques enregistrées de Peaksware LLC ; CTL, ATL et TSB
sont revendiqués par la même société (GoldenCheetah et Intervals.icu ont dû
renommer leurs métriques). Une marque protège un nom, pas une formule : le
projet garde les calculs de Banister et les nomme *condition*, *fatigue*,
*forme*. Voir docs/marques.md.

Une ligne peut citer un sigle si elle le présente comme une marque (elle
contient « marque », « trademark » ou « ® ») ; docs/marques.md, qui tient la
table d'équivalence, est exempté en entier.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import arc_metrics as M  # noqa: E402

MARKS = re.compile(
    r"\b(?:r?TSS|hrTSS|NGP|CTL|ATL|TSB)\b"  # NP / IF seuls : trop courants (« IF » en anglais)
    r"|Training Stress (?:Score|Balance)|Normali[sz]ed (?:Power|Graded Pace)|Intensity Factor"
    r"|(?:Chronic|Acute) Training Load"
)
DECLARED = re.compile(r"marque|trademark|®", re.IGNORECASE)

# Surfaces lues par l'athlète ou par les agents qui écrivent pour lui.
SURFACES = ("README.md", "web", "docs", "agents", "skills", "templates", "config", "scripts/arc_metrics.py")
TEXT_SUFFIXES = {".md", ".html", ".js", ".css", ".toml", ".py", ".yml"}
EXEMPT = {REPO / "docs" / "marques.md"}


def _files():
    for entry in SURFACES:
        path = REPO / entry
        candidates = [path] if path.is_file() else path.rglob("*")
        for p in candidates:
            if p.is_file() and p.suffix in TEXT_SUFFIXES and p not in EXEMPT:
                yield p


class TestNoTrademarkedMetricNames(unittest.TestCase):
    def test_user_facing_text(self):
        hits = []
        for path in _files():
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if MARKS.search(line) and not DECLARED.search(line):
                    hits.append(f"{path.relative_to(REPO)}:{n}: {line.strip()[:100]}")
        self.assertFalse(
            hits,
            "sigle de marque tierce hors d'une mention de marque (dire condition / fatigue / forme) :\n  "
            + "\n  ".join(hits),
        )

    def test_series_keys_are_generic(self):
        point = M.daily_series({}, M.date(2026, 1, 1), M.date(2026, 1, 1))[0]
        self.assertTrue({"fitness", "fatigue", "form"} <= point.keys(), point.keys())
        self.assertFalse({"ctl", "atl", "tsb"} & point.keys(), point.keys())


if __name__ == "__main__":
    unittest.main()
