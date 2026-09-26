"""Palier D — rendu Markdown -> HTML de `scripts/arc_serve.py` (`render_markdown`,
`_inline`, `strip_leading_heading`), pur, sans serveur ni bac à sable.

Revue de code #55 : `_inline` échappait avec `html.escape(quote=False)`, et le
groupe d'URL du motif de lien (`\\((https?://[^)\\s]+)\\)`) acceptait `"` — un
lien Markdown malformé (`[texte](https://a"onmouseover="alert(5))`) pouvait donc
faire sortir la valeur générée de l'attribut `href="..."` qui l'accueille. La CSP
du serveur (`arc_serve.Handler._send`) bloquerait déjà l'exécution d'un script
ainsi injecté, mais l'attribut lui-même ne doit jamais pouvoir être rompu — ces
tests verrouillent les deux réparations indépendamment : l'échappement
(`quote=True`) ET la classe de caractères de l'URL (`"'<>` exclus), pour qu'un
futur appel qui oublierait l'une des deux protections reste couvert par l'autre.
`render_markdown` est utilisé par `/api/report`, `/api/week` et
`/api/decision/<id>` : ces tests couvrent le rendu lui-même, commun aux trois.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import arc_serve as S  # noqa: E402


class TestRenderMarkdownEscaping(unittest.TestCase):
    def test_plain_quotes_and_angle_brackets_are_escaped(self):
        html = S.render_markdown("""He said "hi" and it's <fine>.""")
        self.assertNotIn('"', html)
        self.assertNotIn("'", html)
        self.assertNotIn("<fine>", html)
        self.assertIn("&quot;", html)
        self.assertIn("&#x27;", html)

    def test_malformed_link_with_a_quote_never_breaks_out_of_the_href_attribute(self):
        """Le motif de « payload » classique d'injection d'attribut : une URL de
        lien Markdown qui tente de refermer `href="..."` prématurément puis
        d'ouvrir un nouvel attribut (`onmouseover=`). Le lien peut rester rendu
        (le texte de l'URL est alors inerte dans l'attribut) ou ne plus être
        reconnu comme un lien du tout (la classe de caractères de l'URL exclut
        désormais `"`) — dans les deux cas, aucun `onmouseover=` ne doit
        apparaître HORS de la valeur d'un attribut `href`."""
        html = S.render_markdown('[texte](https://a"onmouseover="alert(5))')
        # ` onmouseover=` ne doit jamais apparaître comme un attribut HTML séparé
        # (précédé d'un espace, hors de la valeur `href="..."`) — seul un
        # `&quot;onmouseover=&quot;` inerte, À L'INTÉRIEUR de cette valeur, est
        # acceptable.
        self.assertNotIn(" onmouseover=", html)
        self.assertIn("&quot;onmouseover=&quot;", html)
        # La valeur de l'attribut `href` elle-même ne doit contenir AUCUN `"`
        # littéral (celui du contenu source, jamais ceux, légitimes, du gabarit
        # `href="..."` ajoutés par `render_markdown`) : extraite entre les
        # guillemets du gabarit, elle ne doit plus porter de `"` du tout.
        start = html.index('href="') + len('href="')
        end = html.index('"', start)
        href_value = html[start:end]
        self.assertNotIn('"', href_value)

    def test_malformed_link_with_angle_brackets_stays_inert(self):
        html = S.render_markdown('[t](https://a><script>alert(1)</script>)')
        self.assertNotIn("<script>", html)

    def test_well_formed_link_still_renders_as_a_link(self):
        html = S.render_markdown("[Trail des Collines](https://example.org/course)")
        self.assertIn('<a href="https://example.org/course" rel="noopener noreferrer">Trail des Collines</a>', html)

    def test_inline_code_and_emphasis_still_escape_their_content(self):
        html = S.render_markdown('`<b>` and **"bold"**')
        self.assertIn("<code>&lt;b&gt;</code>", html)
        self.assertIn("<strong>&quot;bold&quot;</strong>", html)


class TestStripLeadingHeading(unittest.TestCase):
    """#55, nit de revue : le titre `# ...` de tête d'un corps de décision est
    redondant avec le titre de page déjà affiché par `header()` juste au-dessus
    (`d.summary`) — retiré UNIQUEMENT quand il ouvre le texte, jamais un `#`
    plus loin dans le corps."""

    def test_removes_a_leading_h1(self):
        self.assertEqual(S.strip_leading_heading("# Titre\n\nCorps du texte."), "Corps du texte.")

    def test_leaves_text_without_a_leading_heading_untouched(self):
        self.assertEqual(S.strip_leading_heading("Pas de titre ici."), "Pas de titre ici.")

    def test_only_removes_the_first_heading_a_later_one_stays(self):
        result = S.strip_leading_heading("# Titre\n\n## Contexte\n\nTexte.")
        self.assertEqual(result, "## Contexte\n\nTexte.")

    def test_empty_string_is_safe(self):
        self.assertEqual(S.strip_leading_heading(""), "")


if __name__ == "__main__":
    unittest.main()
