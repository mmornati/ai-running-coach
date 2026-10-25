#!/usr/bin/env python3
"""Captures d'écran de la DOCUMENTATION du tableau de bord (`docs/assets/dashboard/*.webp`), reproductibles.

    uv run --with playwright scripts/docs_capture.py [--only nom,nom] [--out docs/assets/dashboard] [--list]

Mêmes ingrédients que `scripts/video_capture.py` (dont ce script réutilise les aides : services, Playwright,
temps figé, conversion WebP) : workspace fictif « Camille » (`scripts/video_demo_workspace.py`, variante
`docs=True` qui ajoute les données que les images documentent), `arc_serve.py --today 2026-09-29`, base en
mémoire, chat `mock`. Différences avec la série de vidéos : design **roadbook** (le défaut), thème **clair**
(sauf `sombre-forme`), cadrage « vignette » d'une carte ou d'une vue, et noms de fichiers stables : aucun lien
de la documentation ne change quand on régénère.

Chaque image est décrite par UNE ligne de `SHOTS` (nom → route, format, thème, découpe, actions). Formats :
`desktop` 1440 px de large @2x (la page est agrandie à sa hauteur pour que l'en-tête et le rail collants ne
recouvrent rien), `chat` 1280 px @2x, `mobile` 390×844 @2x (écran seul, comme les images d'origine),
`thumb` 1440×900 réduit à 800×500 (vignettes de la page d'accueil du tableau de bord).

Découpes (`clip`) : `page` (toute la page, en-tête et rail compris), `main` (le contenu, sans le vide sous
la dernière carte), `("sel", css)` ou `("h2", texte)` (une carte), `viewport` (l'écran, mobile et vignettes) ;
`until=texte` arrête la découpe sous la carte dont le titre `h2` contient ce texte (jamais une carte coupée) ;
`crop=(haut, hauteur)` garde une tranche en px CSS depuis le haut de la découpe.

Les captures ne portent aucun artefact de développement (feuille adoptée `DOCS_CSS`) : ni version du moteur
(`git describe`), ni pastille de mise à jour, ni lien « Ancien design », ni lien « fichiers hors contrat » du rail
(sauf `debt=True`), ni curseur de frappe ou bouton « Interrompre » du coach. La vérification de mise à jour
est coupée (`ARC_UPDATE_CHECK=off`) : aucun appel à GitHub.

Rien n'est lu hors du dépôt : workspace fictif, aucune requête hors 127.0.0.1. Prérequis : `uv`, Google Chrome
ou le Chromium de Playwright, `cwebp` (qualité 82, comme les images d'origine).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import video_capture as vc  # noqa: E402

REPO = vc.REPO
DEMO = vc.demo
OUT = REPO / "docs/assets/dashboard"

FORMATS = {
    "desktop": {"width": 1440, "height": 900, "scale": 2},
    "chat": {"width": 1280, "height": 1200, "scale": 2},
    "mobile": {"width": 390, "height": 844, "scale": 2},
    "thumb": {"width": 1440, "height": 900, "scale": 1},
}
THUMB_SIZE = (800, 500)

ULTRA = "roadbook?plan=planning/2026-09-27_ultra_ultra-des-cretes.md&scenario=realistic"


def S(name, route, fmt="desktop", clip="main", wait="main h2", **kw):
    return dict(name=name, route=route, fmt=fmt, clip=clip, wait=wait, **kw)


# ---------------------------------------------------------------------------
# Table nom → vue. `{act}` : séance du 27 septembre ; `{ultra}` / `{laps}` : séances ajoutées par la variante docs.
# `ws` : workspace servi (« docs » par défaut, « bloc » pour la semaine à venir, « chat » pour le coach).
# `scroll` : (sélecteur, texte, décalage) amené en haut avant la capture ; `click` : (sélecteur, texte) cliqué.
# ---------------------------------------------------------------------------

SHOTS = [
    # --- vues complètes ---------------------------------------------------------------------------------------
    S("aujourdhui", "", clip="page", wait=".rk-verdict"),
    S("aujourdhui-materiel", "", clip=("h2", "Au programme"), wait=".rk-verdict"),
    S("forme", "forme", wait="svg"),
    S("sombre-forme", "forme", scheme="dark", until="Courbe de forme", wait="svg"),
    S("sante", "sante?jours=180", until="Dette de sommeil", wait="#c-sleepdebt svg"),
    S("sante-foulee", "sante", clip=("h2", "Comment évolue ma foulée"), wait="svg"),
    S("semaine", "semaine", wait=".rk-runsheet"),
    S("semaine-bloc", "semaine?debut=2026-10-12", ws="bloc", wait=".rk-runsheet", reload=False),
    S("seances", "seances", wait=".list, table"),
    S("seance", "seance/{act}", until="Profil", wait="main h1"),
    S("seance-tours", "seance/{laps}", clip=("h2", "Splits"), wait="main h2"),
    S("seance-ultra", "seance/{ultra}", clip=("h2", "Splits"), wait="main h2"),
    S("seance-materiel", "seance/{act}", clip=("sel", ".session-hero .ledger"), wait="main h1"),
    S("performance", "performance", wait="main h2"),
    S("materiel", "materiel", until="Chaussures"),
    S("equipement", "materiel", clip=("h2", "Équipement")),
    S("inspections", "materiel", clip=("h2", "Inspections photo")),
    S("materiel-fiche", "materiel/crete-pro-bleue", until="Kilomètres par mois"),
    S("materiel-fiche-equipement", "materiel/poche-eau", crop=(0, 1010)),
    S("trail-shape", "trail-shape"),
    S("calendrier", "calendrier"),
    S("rapports", "rapports", wait=".list li"),
    S("rapport", "rapport?path=rapports/2026-09-27_rapport.md", wait=".prose"),
    S("nutrition", "nutrition"),
    S("fichiers", "fichiers", clip="page", wait="main h1", debt=True),
    # --- coach (chat) -----------------------------------------------------------------------------------------
    S("coach", "chat", fmt="chat", clip="viewport", ws="chat"),
    S("coach-trace", "chat", fmt="chat", clip="viewport", ws="chat", trace=True),
    S("mobile-coach", "chat", fmt="mobile", clip="viewport", ws="chat"),
    # --- téléphone --------------------------------------------------------------------------------------------
    S("mobile-aujourdhui", "", fmt="mobile", clip="viewport", wait=".rk-verdict"),
    S("mobile-semaine", "semaine", fmt="mobile", clip="viewport", wait=".rk-runsheet"),
    S("mobile-seance", "seance/{act}", fmt="mobile", clip="viewport", wait="main h1"),
    S("mobile-trail-shape", "trail-shape", fmt="mobile", clip="viewport"),
    S("mobile-materiel", "materiel", fmt="mobile", clip="viewport"),
    S("mobile-foulee", "sante", fmt="mobile", clip="viewport", wait="svg", scroll=("h2", "Comment évolue ma foulée", 64),
      hide=".readout--sticky"),
    # --- vignettes de la page d'accueil du tableau de bord ---------------------------------------------------
    S("vignette-aujourdhui", "", fmt="thumb", clip="viewport", wait=".rk-verdict"),
    S("vignette-forme", "forme", fmt="thumb", clip="viewport", wait="svg"),
    S("vignette-sante", "sante", fmt="thumb", clip="viewport", wait="svg"),
    S("vignette-semaine", "semaine", fmt="thumb", clip="viewport", wait=".rk-runsheet"),
    S("vignette-seance", "seance/{act}", fmt="thumb", clip="viewport", wait="main h1"),
    S("vignette-performance", "performance", fmt="thumb", clip="viewport"),
    S("vignette-materiel", "materiel", fmt="thumb", clip="viewport"),
    S("vignette-trail-shape", "trail-shape", fmt="thumb", clip="viewport"),
    S("vignette-calendrier", "calendrier", fmt="thumb", clip="viewport"),
    S("vignette-rapport", "rapports", fmt="thumb", clip="viewport", wait=".list li"),
    S("vignette-coach", "chat", fmt="thumb", clip="viewport", ws="chat"),
    S("vignette-nutrition", "nutrition", fmt="thumb", clip="viewport"),
]

# Feuille adoptée (insensible à la CSP) : rien d'une build de développement ni d'un état transitoire à l'image.
DOCS_CSS = """
#version, #update, .rk-rail__foot, .rk-classic { display: none !important; }
.msg--coach.is-streaming .msg__text > :last-child::after, .msg__text .typing::after { content: none !important; }
#stop { display: none !important; }
#send[hidden] { display: grid !important; }
"""
DEBT_CSS = ".rk-navgroup--debt { display: none !important; }"

DOCS_INIT_JS = """
((rules) => { const css = new CSSStyleSheet(); css.replaceSync(rules);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, css]; })(%s);
"""

RECT_JS = """
([clip, arg, until]) => {
  const q = (s) => document.querySelector(s);
  const card = (text) => {
    const h = [...document.querySelectorAll('main h2')].find((n) => n.textContent.includes(text));
    return h && (h.closest('section') || h.parentElement);
  };
  let el = null;
  if (clip === 'main') el = q('main');
  else if (clip === 'sel') el = q(arg);
  else if (clip === 'h2') el = card(arg);
  else if (clip === 'page') el = document.documentElement;
  if (!el) return null;
  const r = el.getBoundingClientRect();
  let height = r.height;
  if (clip === 'main') {            // page agrandie à sa hauteur : on s'arrête sous le dernier élément du contenu
    const kids = [...el.children].filter((n) => n.getBoundingClientRect().height > 0);
    if (kids.length) height = Math.max(...kids.map((n) => n.getBoundingClientRect().bottom)) - r.top + 32;
  }
  if (until) {
    const c = card(until);
    if (!c) return null;
    height = c.getBoundingClientRect().bottom - r.top + 10;   // marge plus courte que l'écart entre deux cartes
  }
  return [r.x + scrollX, r.y + scrollY, r.width, Math.min(height, r.height)];
}
"""


def to_webp(png: Path, webp: Path, size: tuple | None = None) -> None:
    cmd = ["cwebp", "-quiet", "-q", "82"]
    if size:
        cmd += ["-resize", str(size[0]), str(size[1])]
    subprocess.run(cmd + [str(png), "-o", str(webp)], check=True)


def snap(page, shot, fmt, tmp: Path, out: Path) -> bool:
    name, clip = shot["name"], shot["clip"]
    kind, arg = (clip, None) if isinstance(clip, str) else clip
    png = tmp / f"{name}.png"
    if kind in ("viewport",):
        page.screenshot(path=str(png), animations="disabled")
    else:
        # Page agrandie à sa hauteur : en-tête et rail collants restent à leur place, rien ne recouvre la découpe.
        for _ in range(2):
            h = int(page.evaluate("document.documentElement.scrollHeight"))
            page.set_viewport_size({"width": fmt["width"], "height": max(h, fmt["height"])})
            page.wait_for_timeout(300)
        rect = page.evaluate(RECT_JS, [kind, arg, shot.get("until")])
        if not rect:
            print(f"  !! découpe introuvable : {name} {clip}", file=sys.stderr)
            return False
        x, y, w, hh = rect
        if kind == "page":
            x, y, w = 0, 0, fmt["width"]
        crop = shot.get("crop")
        if crop:
            y += crop[0]
            hh = min(hh - crop[0], crop[1])
        page.screenshot(path=str(png), clip={"x": x, "y": y, "width": w, "height": hh}, animations="disabled")
    to_webp(png, out / f"{name}.webp", THUMB_SIZE if shot["fmt"] == "thumb" else None)
    print(f"  {name}: {(out / (name + '.webp')).stat().st_size // 1024} Ko", file=sys.stderr)
    return True


def run_shot(browser, shot, base, ids, tmp, out):
    fmt = FORMATS[shot["fmt"]]
    ctx = vc.new_context(browser, fmt, scheme=shot.get("scheme", "light"), design="roadbook")
    rules = DOCS_CSS + ("" if shot.get("debt") else DEBT_CSS)
    ctx.add_init_script(DOCS_INIT_JS % json.dumps(rules))
    page = ctx.new_page()
    try:
        route = shot["route"].format(**ids)
        if route == "chat":
            page.goto(f"{base}/chat.html")
            page.wait_for_selector("#composer-input:not([disabled])", timeout=20000)
            vc.send(page, vc.USER_MESSAGE)
            page.wait_for_selector(".action .btn--primary", timeout=60000)
            page.wait_for_timeout(3000)              # la réponse finit de s'écrire (plus de curseur)
            if shot.get("trace"):
                vc.open_trace(page)
            if shot["fmt"] == "mobile":
                page.evaluate("document.querySelector('.action').scrollIntoView({block: 'center'})")
        else:
            vc.open_view(page, base, route, shot["wait"], reload=shot.get("reload", True))
        if shot.get("hide"):                  # bulle collante d'une autre carte qui recouvrirait la découpe
            page.evaluate("(sel) => document.querySelectorAll(sel).forEach((n) => { n.style.display = 'none'; })", shot["hide"])
        if shot.get("scroll"):
            sel, text, off = shot["scroll"]
            page.evaluate("""([sel, text, off]) => {
              const h = [...document.querySelectorAll(sel)].find((n) => n.textContent.includes(text));
              const el = h && (h.closest('section') || h);          // le haut de la carte, pas celui du titre
              if (el) { el.scrollIntoView({block: 'start'}); scrollBy(0, -off); }
            }""", [sel, text, off])
            page.wait_for_timeout(300)
        if shot.get("click"):
            page.evaluate(vc.CLICK_JS, list(shot["click"]))
            page.wait_for_timeout(500)
        return snap(page, shot, fmt, tmp, out)
    finally:
        ctx.close()


def find_ids(base: str) -> dict:
    import urllib.request
    with urllib.request.urlopen(f"{base}/api/activities?limit=400", timeout=20) as r:
        acts = json.load(r)["activities"]
    ids = {"act": next(a["id"] for a in acts if a["date"] == "2026-09-27")}
    for key, day in (("ultra", DEMO.ULTRA_ACTIVITY_DATE), ("laps", DEMO.LAPS_ACTIVITY_DATE)):
        match = [a["id"] for a in acts if a["date"] == day.isoformat()]
        ids[key] = match[0] if match else ids["act"]
    return ids


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default="", help="noms séparés par des virgules (défaut : tout)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--list", action="store_true", help="affiche la table nom → vue et sort")
    args = ap.parse_args()
    if args.list:
        for s in SHOTS:
            print(f"{s['name']:28} {s['fmt']:8} {s.get('scheme', 'light'):5} {s['route'] or '(aujourd’hui)':45} {s['clip']}")
        return 0
    only = {n.strip() for n in args.only.split(",") if n.strip()}
    unknown = only - {s["name"] for s in SHOTS}
    if unknown:
        print(f"noms inconnus : {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright manquant : uv run --with playwright scripts/docs_capture.py", file=sys.stderr)
        return 2
    if not shutil.which("cwebp"):
        print("cwebp requis (brew install webp).", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    shots = [s for s in SHOTS if not only or s["name"] in only]
    failed = []
    with tempfile.TemporaryDirectory(prefix="arc-docs-") as tmpname:
        tmp = Path(tmpname)
        services = {}
        try:
            def serve(key):
                if key in services:
                    return services[key][0]
                ws = tmp / f"workspace-{key}"
                DEMO.build_demo(ws, docs=True, bloc=(key == "bloc"))
                if key == "chat":
                    chat_port = vc.free_port()
                    vc.start_chat(ws, chat_port, tmp).stop()      # écrit [chat] avant le tableau de bord
                else:
                    chat_port = None
                dash = vc.Service([sys.executable, str(REPO / "scripts/arc_serve.py"), "--workspace", str(ws),
                                   "--today", vc.TODAY, "--memory", "--port", "0"],
                                  env={"ARC_UPDATE_CHECK": "off"})       # aucune requête vers GitHub
                base = dash.url.rstrip("/")
                services[key] = (base, dash, ws, chat_port, find_ids(base))
                return base

            with sync_playwright() as pw:
                browser = vc.launch(pw)
                for shot in shots:
                    key = shot.get("ws", "docs")
                    fresh = key not in services
                    base = serve(key)
                    if fresh and key != "chat":       # premier chargement lent (index des échantillons) : à chaud
                        warm = browser.new_page()
                        try:
                            warm.goto(f"{base}/#/")
                            warm.wait_for_selector("main h2", timeout=180000)
                        except Exception as exc:  # noqa: BLE001 - mise en route facultative : les essais suivent
                            print(f"  (mise en route : {str(exc).splitlines()[0]})", file=sys.stderr)
                        finally:
                            warm.close()
                    _, _, ws, chat_port, ids = services[key]
                    chat = None
                    if key == "chat":
                        chat = vc.start_chat(ws, chat_port, tmp)       # conversation vierge pour chaque capture
                    try:
                        ok = False
                        for attempt in (1, 2, 3):       # un chargement lent n'est pas une erreur : d'autres chances
                            try:
                                ok = run_shot(browser, shot, base, ids, tmp, args.out)
                                break
                            except Exception as exc:  # noqa: BLE001 - une capture en échec n'arrête pas les autres
                                print(f"  !! {shot['name']} (essai {attempt}) : {str(exc).splitlines()[0]}", file=sys.stderr)
                    finally:
                        if chat:
                            chat.stop()
                    if not ok:
                        failed.append(shot["name"])
                browser.close()
        finally:
            for _, dash, *_ in services.values():
                dash.stop()
    if failed:
        print(f"échecs : {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
