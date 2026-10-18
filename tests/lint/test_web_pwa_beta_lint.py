"""Palier B — PWA du tableau de bord et design bêta « roadbook » : garanties lues statiquement.

- Manifeste valide, icônes présentes et aux bonnes dimensions, pages qui le déclarent (avec
  `crossorigin="use-credentials"` : derrière un proxy qui authentifie, il suit la session).
- Service worker : la coque seulement. Les données (`/api/`, `/media/`) ne passent jamais par
  son cache, et chaque fichier de la coque existe vraiment.
- Design bêta : opt-in. Toutes les règles de `css/beta.css` sont portées par
  `[data-design="roadbook"]` (sauf le lien d'essai), et `js/beta.js` n'injecte aucun
  attribut `style=` (la CSP `style-src 'self'` le bloquerait en silence).
- Polices auto-hébergées : chaque fichier cité par `css/fonts.css` existe, est un woff2, fait
  partie de la coque hors ligne, et sa licence OFL l'accompagne ; aucune page ne charge plus
  Google Fonts (la CSP `font-src 'self'` le bloquerait).
"""

from __future__ import annotations

import json
import re
import struct
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
WEB = REPO / "web"
PAGES = ("index.html", "chat.html")


def png_size(path: Path):
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} n'est pas un PNG"
    return struct.unpack(">II", head[16:24])


def top_level_selectors(css: str):
    """Sélecteurs de premier niveau, et ceux directement sous un @media (commentaires retirés)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, depth, buf, stack = [], 0, "", []
    for ch in css:
        if ch == "{":
            head = buf.strip()
            in_media = bool(stack) and stack[-1].startswith("@media")
            if head and (depth == 0 or (depth == 1 and in_media)) and not head.startswith("@"):
                out.append(head)
            stack.append(head)
            depth += 1
            buf = ""
        elif ch == "}":
            depth -= 1
            stack.pop()
            buf = ""
        elif ch == ";" and depth == 0:
            buf = ""
        else:
            buf += ch
    return out


class TestManifestAndIcons(unittest.TestCase):
    def test_manifest_is_valid_and_installable(self):
        m = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
        for key in ("name", "short_name", "start_url", "scope", "display", "icons", "theme_color", "background_color"):
            self.assertIn(key, m)
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["lang"], "fr")
        sizes = {(i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
        self.assertIn(("192x192", "any"), sizes)
        self.assertIn(("512x512", "any"), sizes)
        self.assertIn(("512x512", "maskable"), sizes)

    def test_icons_exist_with_declared_sizes(self):
        m = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
        for icon in m["icons"]:
            path = WEB / icon["src"]
            with self.subTest(icon=icon["src"]):
                self.assertTrue(path.is_file())
                if path.suffix == ".png":
                    w, h = png_size(path)
                    self.assertEqual(f"{w}x{h}", icon["sizes"])
        self.assertEqual(png_size(WEB / "icons/apple-touch-icon.png"), (180, 180))

    def test_pages_declare_the_pwa_and_the_early_script(self):
        for name in PAGES:
            html = (WEB / name).read_text(encoding="utf-8")
            with self.subTest(page=name):
                self.assertRegex(html, r'<link rel="manifest" href="manifest\.webmanifest" crossorigin="use-credentials">')
                self.assertIn('rel="apple-touch-icon"', html)
                self.assertIn('name="theme-color"', html)
                self.assertIn("viewport-fit=cover", html)
                # Script classique (pas de module) et AVANT les feuilles de style : le design est
                # choisi avant le premier rendu, sans flash du design actuel.
                early = html.index('<script src="js/early.js"></script>')
                self.assertLess(early, html.index('href="css/app.css"'))
                self.assertIn('href="css/beta.css"', html)

    def test_server_serves_the_manifest_type(self):
        src = (REPO / "scripts/arc_serve.py").read_text(encoding="utf-8")
        self.assertIn('".webmanifest": "application/manifest+json"', src)


class TestServiceWorker(unittest.TestCase):
    def setUp(self):
        self.sw = (WEB / "sw.js").read_text(encoding="utf-8")

    def test_data_routes_never_go_through_the_cache(self):
        self.assertRegex(self.sw, r"isData = \(url\) => /\^\\/\(api\|media\)\\//\.test\(url\.pathname\)")
        self.assertIn("isData(url)) return;", self.sw)

    def test_redirected_or_opaque_responses_are_never_cached(self):
        self.assertIn("res.ok && !res.redirected && res.type === \"basic\"", self.sw)

    def test_every_shell_file_exists(self):
        shell = re.search(r"const SHELL = \[(.*?)\];", self.sw, re.S).group(1)
        for path in re.findall(r'"([^"]+)"', shell):
            if path == "./":
                continue
            with self.subTest(path=path):
                self.assertTrue((WEB / path).is_file(), f"{path} absent de web/")

    def test_every_web_script_is_in_the_shell(self):
        shell = re.search(r"const SHELL = \[(.*?)\];", self.sw, re.S).group(1)
        for js in sorted((WEB / "js").glob("*.js")):
            with self.subTest(script=js.name):
                self.assertIn(f'"js/{js.name}"', shell, "nouveau script absent de la coque hors ligne")


class TestSelfHostedFonts(unittest.TestCase):
    def setUp(self):
        self.css = (WEB / "css/fonts.css").read_text(encoding="utf-8")
        self.shell = re.search(r"const SHELL = \[(.*?)\];", (WEB / "sw.js").read_text(encoding="utf-8"), re.S).group(1)

    def font_files(self):
        return re.findall(r'url\("\.\./(fonts/[^"]+)"\)', self.css)

    def test_every_font_exists_and_is_in_the_shell(self):
        files = self.font_files()
        self.assertTrue(files, "css/fonts.css ne cite aucune police")
        self.assertEqual(len(files), self.css.count("@font-face"))
        self.assertIn('"css/fonts.css"', self.shell)
        for path in files:
            with self.subTest(font=path):
                self.assertTrue(path.endswith(".woff2"))
                self.assertEqual((WEB / path).read_bytes()[:4], b"wOF2", f"{path} absent ou pas un woff2")
                self.assertIn(f'"{path}"', self.shell, "police absente de la coque hors ligne")

    def test_every_shipped_font_is_declared(self):
        declared = set(self.font_files())
        for woff2 in sorted((WEB / "fonts").glob("*.woff2")):
            with self.subTest(font=woff2.name):
                self.assertIn(f"fonts/{woff2.name}", declared, "fichier de police jamais utilisé")

    def test_families_used_by_the_css_and_licences(self):
        for family, licence in (("Inter", "OFL-Inter.txt"), ("Sora", "OFL-Sora.txt"),
                                ("Barlow Condensed", "OFL-BarlowCondensed.txt")):
            with self.subTest(family=family):
                self.assertIn(f'font-family: "{family}";', self.css)
                self.assertIn("SIL OPEN FONT LICENSE", (WEB / "fonts" / licence).read_text(encoding="utf-8"))
        self.assertEqual(self.css.count("font-display: swap;"), self.css.count("@font-face"))

    def test_pages_load_local_fonts_only(self):
        for name in PAGES:
            html = (WEB / name).read_text(encoding="utf-8")
            with self.subTest(page=name):
                self.assertNotIn("fonts.googleapis.com", html)
                self.assertNotIn("fonts.gstatic.com", html)
                self.assertLess(html.index('href="css/fonts.css"'), html.index('href="css/app.css"'))


class TestBetaDesignIsOptIn(unittest.TestCase):
    def test_every_beta_rule_is_scoped(self):
        allowed = (".sr-only", ".design-pill")
        for sel in top_level_selectors((WEB / "css/beta.css").read_text(encoding="utf-8")):
            if re.fullmatch(r"(from|to|\d+%)", sel):
                continue
            with self.subTest(selector=sel):
                for part in sel.split(","):
                    part = part.strip()
                    self.assertTrue(part.startswith(('[data-design="roadbook"]', ':root[data-design="roadbook"]')) or part.startswith(allowed),
                                    f"règle bêta non portée par [data-design=\"roadbook\"] : {part}")

    def test_beta_markup_has_no_inline_style(self):
        js = (WEB / "js/beta.js").read_text(encoding="utf-8")
        self.assertNotRegex(js, r"\sstyle=", "la CSP bloque style= : passer par data-vars et le CSSOM")

    def test_early_script_reads_and_clears_the_design_parameter(self):
        js = (WEB / "js/early.js").read_text(encoding="utf-8")
        self.assertIn('asked === "beta" || asked === "classic"', js)
        self.assertIn('url.searchParams.delete("design")', js)
        self.assertIn('root.dataset.design = "roadbook"', js)
        self.assertIn("window.isSecureContext", js)

    def test_both_pages_offer_the_switch_and_the_way_back(self):
        for name in PAGES:
            with self.subTest(page=name):
                self.assertIn('href="?design=beta"', (WEB / name).read_text(encoding="utf-8"))
        self.assertIn('href="?design=classic"', (WEB / "js/beta.js").read_text(encoding="utf-8"))

    def test_beta_shell_keeps_the_single_nav_list(self):
        js = (WEB / "js/beta.js").read_text(encoding="utf-8")
        self.assertIn('import { navItems } from "./nav.js";', js)


if __name__ == "__main__":
    unittest.main()
