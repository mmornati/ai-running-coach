#!/usr/bin/env python3
"""Captures d'écran du tableau de bord pour la série de vidéos (workspace fictif « Camille »).

    uv run --with playwright scripts/video_capture.py [--only nom,nom] [--out docs/video/shots]

Étapes : construit le workspace de démonstration dans un dossier temporaire
(`scripts/video_demo_workspace.py`), lance `arc_serve.py` (--today 2026-09-29, port éphémère, base en
mémoire) et le service de chat `arc_chat.py` avec le backend `mock` rejouant
`docs/video/data/chat-scenario.fr.json`, puis pilote un navigateur (Playwright) : thème sombre, temps
et animations figés, 1440×900 @2x (bureau) et 390×844 @3x (mobile). Écrit `<nom>.webp` (cwebp, sinon
ffmpeg), `manifest.json` et `manifest.js` (`window.ARC_SHOTS = …;`, lisible en file://) dans `--out`.

Le manifeste donne, pour chaque capture, `width`/`height` (px CSS), `scale` et des cadres
`boxes = {nom: [x, y, w, h]}` en px CSS de la capture (getBoundingClientRect), que le moteur vidéo
utilise pour zoomer et surligner. Un élément absent ou hors de l'image est omis, jamais inventé.

Rien n'est lu hors du dépôt : le workspace est fictif, le service de chat ne charge pas
`~/.config/ai-running-coach/llm.env` (`ARC_LLM_ENV` pointe vers un fichier absent) et aucune
requête ne quitte 127.0.0.1. Prérequis : `uv`, Google Chrome ou le Chromium de Playwright, `cwebp` ou `ffmpeg`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import video_demo_workspace as demo  # noqa: E402

SCENARIO = REPO / "docs/video/data/chat-scenario.fr.json"
TODAY = "2026-09-29"
FIXED_NOW = "2026-09-29T08:30:00+02:00"
DESKTOP = {"width": 1440, "height": 900, "scale": 2}
MOBILE = {"width": 390, "height": 844, "scale": 3}
USER_MESSAGE = "Je me sens vidé·e ce matin, je fais quand même mon seuil ?"

INIT_JS = """
(() => {
  const F = new Date(%r).getTime(), D = Date;
  class FixedDate extends D { constructor(...a) { a.length ? super(...a) : super(F); } static now() { return F; } }
  window.Date = FixedDate;
  // Feuille adoptée : insensible à la CSP (pas de <style> en ligne).
  const css = new CSSStyleSheet();
  css.replaceSync(`*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}
    html{scroll-behavior:auto!important} #backend,#ctx-user,#session-select{visibility:hidden!important}`);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, css];
})();
""" % FIXED_NOW

FIND_JS = """
(specs) => specs.map((sp) => {
  let nodes = [...document.querySelectorAll(sp.sel)];
  if (sp.text) nodes = nodes.filter((n) => n.textContent.includes(sp.text));
  let el = nodes[sp.nth || 0];
  if (el && sp.closest) el = el.closest(sp.closest);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return [r.x, r.y, r.width, r.height];   // relatif au viewport ; les pages entières sont capturées à scroll 0
})
"""

SCROLL_JS = """
([sel, text, offset]) => {
  const nodes = [...document.querySelectorAll(sel)].filter((n) => !text || n.textContent.includes(text));
  if (!nodes.length) return false;
  nodes[0].scrollIntoView({block: 'start'});
  window.scrollBy(0, -offset);
  return true;
}
"""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Catalogue des captures (vues du tableau de bord)
# ---------------------------------------------------------------------------
# route : hash ; wait : sélecteur à attendre ; scroll : (sélecteur, texte) amené en haut ; full : page entière ;
# boxes : nom -> {sel, text?, closest?, nth?}

ULTRA_ROUTE = "roadbook?plan=planning/2026-09-27_ultra_ultra-des-cretes.md&scenario=realistic"   # épisode 14


def B(sel, text=None, closest=None, nth=0):
    return {"sel": sel, "text": text, "closest": closest, "nth": nth}


def h2(text):
    return B("main h2", text, closest="section")


SHOTS = [
    dict(name="aujourdhui", view="Aujourd'hui", route="", wait=".verdict",
         desc="Aujourd'hui, mardi 29 septembre : verdict « Alléger » et encart « Pourquoi aujourd'hui ? » (bilan matinal appliqué).",
         boxes={"verdict": B(".verdict"), "pourquoi": B("#decision-encart-title", closest="section"),
                "chip-bilan": B(".chip", "Bilan matinal"), "chip-appliquee": B(".chip", "Appliquée")}),
    dict(name="aujourdhui-sante", view="Aujourd'hui", route="", wait=".triad", scroll=(".triad", None),
         desc="Bilan du matin : HRV 38 ms sous la bande 52–70, FC de repos 52 (+6), readiness 34, sommeil 6 h 12.",
         boxes={"triade": B(".triad"), "hrv": B(".triad tr", "HRV nocturne"), "fc-repos": B(".triad tr", "FC de repos"),
                "readiness": B(".triad tr", "Readiness"), "sommeil": B(".triad tr", "Sommeil")}),
    dict(name="aujourdhui-programme", view="Aujourd'hui", route="", wait=".band--split", scroll=(".band--split", None),
         desc="Au programme : seuil annulé, EF 45' prévue ce soir, météo (créneau soir) et forme.",
         boxes={"programme": B("main h2", "Au programme", closest="div"), "seuil-annule": B(".plan li", "Seuil"),
                "ef45": B(".plan li", "EF 45"), "meteo": B(".weather"), "forme": B("main h2", "Forme", closest="div")}),
    dict(name="aujourdhui-complet", view="Aujourd'hui", route="", wait=".verdict", full=True,
         desc="Page Aujourd'hui entière.", boxes={"verdict": B(".verdict"), "triade": B(".triad"), "programme": B(".band--split")}),
    dict(name="semaine", view="Semaine", route="semaine", wait=".week",
         desc="Semaine du 28 septembre : seuil annulé mardi, côtes déplacées de mercredi à jeudi (garde-fou r7).",
         boxes={"aujourdhui": B(".day--today"), "seuil-annule": B(".session", "Annulée"), "cotes-deplacees": B(".session", "Déplacée"),
                "jeudi-cotes": B(".day", "1 oct."), "samedi-longue": B(".day", "3 oct.")}),
    dict(name="semaine-garde-fous", view="Semaine", route="semaine", wait=".prose table", scroll=("main .prose h3", "Garde-fous", 100),
         desc="Plan du coach : tableau des garde-fous (r7 qualité deux jours de suite → côtes jeudi).",
         boxes={"garde-fous": B(".prose table"), "regle-r7": B(".prose tbody tr"), "plan-du-coach": B("main h2", "Plan du coach", closest="section")}),
    dict(name="forme", view="Forme & charge", route="forme", wait="svg",
         desc="Forme & charge : courbe condition / fatigue / forme, ratio de charge et volume hebdomadaire.",
         boxes={"courbe": h2("Courbe de forme"), "ratio": h2("Ratio charge"), "volume": h2("Volume hebdomadaire")}),
    dict(name="analyse", view="Analyse", route="analyse", wait="main h2",
         desc="Analyse : polarisation, découplage, VAM, durabilité (échantillons FIT fictifs).", boxes={"premier-bloc": B("main section.band")}),
    dict(name="trail-shape", view="Trail Shape", route="trail-shape", wait="main h2",
         desc="Trail Shape : score de forme spécifique trail.", boxes={"score": B("main section.band")}),
    dict(name="sante", view="Santé", route="sante", wait="svg",
         desc="Santé : HRV nocturne vs bande personnelle, FC de repos, readiness, sommeil.",
         boxes={"hrv": h2("HRV nocturne"), "fc-repos": h2("FC de repos"), "readiness": h2("Readiness")}),
    dict(name="seance", view="Séance", route="seance/{act}", wait="main h1",
         desc="Séance du dimanche 27 septembre : 18,2 km, 820 m D+, FC 142, effort perçu 6.",
         boxes={"titre": B("main h1"), "zones": h2("Zones FC"), "splits": h2("Splits")}),
    dict(name="seance-montees", view="Séance", route="seance/{act}", wait="main h2", scroll=("main h2", "Montées", 100),
         desc="La même séance : montées détectées (D+, pente, VAM).", boxes={"montees": h2("Montées"), "descente": h2("Efficacité en descente")}),
    dict(name="seance-splits", view="Séance", route="seance/{act}", wait="main h2", scroll=("main h2", "Splits", 100),
         desc="La même séance : splits kilométriques.", boxes={"splits": h2("Splits")}),
    dict(name="calendrier", view="Calendrier", route="calendrier", wait="main h2",
         desc="Calendrier annuel des séances.", boxes={"calendrier": B("main section.band")}),
    dict(name="decisions", view="Décisions", route="decisions", wait=".list li",
         desc="Journal des décisions : bilan matinal du 29 et garde-fou r7 du 28.",
         boxes={"journal": B(".list"), "bilan-matinal": B(".list li", "HRV 38"),
                "garde-fou": B(".list li", "côtes décalées")}),
    dict(name="decision-detail", view="Décision", route="decision?id=2026-09-29_decision_bilan-matinal", wait=".data",
         desc="Détail de la décision du bilan matinal : avant/après (seuil → EF 45'), données, sources.",
         boxes={"avant-apres": h2("Avant / après"), "donnees": h2("Données"), "sources": h2("Sources")}),
    dict(name="materiel", view="Matériel", route="materiel", wait="main h2",
         desc="Matériel : chaussures (Crête Pro ~612 km / 700), équipement, inspections.",
         boxes={"chaussures": h2("Chaussures"), "equipement": h2("Équipement"), "crete-pro": B("main a", "Crête Pro")}),
    dict(name="materiel-fiche", view="Matériel — fiche", route="materiel/crete-pro-bleue", wait="main h2",
         desc="Fiche « Crête Pro (bleue) » : kilomètres par mois, séances, prévision de retraite.",
         boxes={"titre": B("main h1"), "km-par-mois": h2("Kilomètres par mois"), "seances": h2("Séances")}),
    dict(name="inspections", view="Matériel — inspections", route="materiel/crete-pro-bleue", wait="main h2",
         scroll=("main h2", "Inspections", 100),
         desc="Inspections photo de Crête Pro (bleue) : usure du talon gauche, comparaison avec la précédente.",
         boxes={"inspections": h2("Inspections"), "photos": B("main img")}),
    dict(name="nutrition", view="Nutrition", route="nutrition", wait="main h2",
         desc="Nutrition : poids et glucides par heure sur les sorties longues.", boxes={"poids": h2("Poids"), "glucides": h2("Glucides")}),
    dict(name="rapports", view="Rapports", route="rapports", wait=".list li",
         desc="Liste des rapports hebdomadaires du coach.", boxes={"liste": B(".list")}),
    dict(name="rapport", view="Rapport", route="rapport?path=rapports/2026-09-27_rapport.md", wait=".prose",
         desc="Bilan de la semaine du 21 au 27 septembre : synthèse, indicateurs, semaine prochaine.",
         boxes={"rapport": B(".prose"), "tableau": B(".prose table")}),
    dict(name="performance", view="Performance", route="performance", wait="main h2",
         desc="Performance : VO2max estimée et indices.", boxes={"premier-bloc": B("main section.band")}),
    dict(name="roadbook", view="Roadbook", route=ULTRA_ROUTE, wait=".rb-sheet.is-active .rb-table",
         desc="Roadbook de l'Ultra des Crêtes (scénario réaliste, départ 16 h) : profil relatif avec la nuit hachurée, sections, passages à l'heure locale.",
         boxes={"entete": B(".rb-sheet.is-active .rb-head"), "profil": B(".rb-sheet.is-active .rb-profile"),
                "sections": B(".rb-sheet.is-active .rb-table")}),
    dict(name="roadbook-sections", view="Roadbook", route=ULTRA_ROUTE, wait=".rb-sheet.is-active .rb-table",
         scroll=(".rb-sheet.is-active .rb-table-wrap", None, 110),
         desc="Roadbook : passages, barrières avec leur marge (« TENDU »), ravitos avec ce qu'on y prend, drapeau nuit et frontale.",
         boxes={"sections": B(".rb-sheet.is-active .rb-table"), "nuit": B(".rb-sheet.is-active .rb-night-tag"),
                "barriere-tendue": B(".rb-sheet.is-active .rb-cut--tendu", closest="td"),
                "a-prendre": B(".rb-sheet.is-active .rb-take"), "passage": B(".rb-sheet.is-active tr.rb-row--night td.num", nth=2)}),
    dict(name="roadbook-materiel", view="Roadbook", route=ULTRA_ROUTE, wait=".rb-sheet.is-active .rb-gearlist",
         scroll=(".rb-sheet.is-active .rb-cols", None, 110),
         desc="Roadbook : matériel obligatoire en liste à cocher, statut contre l'inventaire, urgence et consignes.",
         boxes={"materiel": B(".rb-sheet.is-active .rb-gearlist"), "manquant": B(".rb-sheet.is-active .rb-gear--bad"),
                "consignes": B(".rb-sheet.is-active .rb-cols")}),
]


# Épisode 15 : le bloc, sur une variante du workspace de Camille dont l'objectif est la course de fin décembre
# (`demo.build_demo(bloc=True)` : le squelette est écrit par le vrai `plan-skeleton --write`).
BLOC_SHOTS = [
    dict(name="bloc-frise", view="Semaine", route="semaine", wait=".band--frise .frise-cell",
         desc="Frise du bloc (vue Semaine) : 12 semaines du 5 octobre au 27 décembre, phases (Base, Développement, Spécifique, Affûtage), semaines allégées, drapeau de course, récupération post-course.",
         boxes={"frise": B(".band--frise"), "colonnes": B(".band--frise svg"), "legende": B(".band--frise .legend"),
                "lecture": B("#frise-readout"), "drapeau": B(".band--frise .frise-flag")}),
    dict(name="bloc-semaine", view="Semaine", route="semaine?debut=2026-10-12", wait=".band--frise .frise-cell", reload=False,
         desc="Semaine du 12 octobre du squelette : créneaux de séance à habiller (« à définir »), la frise du bloc en tête.",
         boxes={"frise": B(".band--frise"), "semaine": B(".week")}),
]


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Service:
    """Processus enfant qui imprime `URL: …` quand il écoute."""

    def __init__(self, argv, env=None):
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     env={**os.environ, **(env or {})})
        self.url = None
        deadline = time.time() + 30
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if line.startswith("URL:"):
                self.url = line.split("URL:", 1)[1].strip()
                return
            if not line and self.proc.poll() is not None:
                break
        self.stop()
        raise RuntimeError(f"service non démarré : {' '.join(map(str, argv))}")

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def start_chat(ws: Path, port: int, tmp: Path, hold: str = "") -> Service:
    shutil.rmtree(ws / ".arc/chat", ignore_errors=True)       # conversation vierge
    cfg = ws / "config/workspace.user.toml"
    base = cfg.read_text(encoding="utf-8").split("\n[chat]")[0]
    cfg.write_text(base + f'\n[chat]\nenabled = true\nbackend = "mock"\nport = {port}\n'
                   f'mock_scenario = "{SCENARIO}"\nmock_scenario_hold = "{hold}"\n', encoding="utf-8")
    return Service([sys.executable, str(REPO / "scripts/arc_chat.py"), "--workspace", str(ws), "--port", str(port)],
                   env={"ARC_LLM_ENV": str(tmp / "absent.env")})


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

def to_webp(png: Path, webp: Path) -> None:
    if shutil.which("cwebp"):
        subprocess.run(["cwebp", "-quiet", "-q", "82", str(png), "-o", str(webp)], check=True)
    elif shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), "-quality", "82", str(webp)], check=True)
    else:
        raise RuntimeError("ni cwebp ni ffmpeg dans le PATH")


class Recorder:
    def __init__(self, out: Path, tmp: Path):
        self.out, self.tmp, self.entries = out, tmp, []

    def snap(self, page, name, view, desc, vp, boxes=None, full=False) -> None:
        png = self.tmp / f"{name}.png"
        page.screenshot(path=str(png), full_page=full, animations="disabled")
        width = vp["width"]
        height = int(page.evaluate("document.documentElement.scrollHeight")) if full else vp["height"]
        found = {}
        if boxes:
            names = list(boxes)
            rects = page.evaluate(FIND_JS, [boxes[n] for n in names])
            for n, r in zip(names, rects):
                if r is None:
                    log(f"  (cadre absent : {name}/{n})")
                    continue
                x0, y0, x1, y1 = max(r[0], 0), max(r[1], 0), min(r[0] + r[2], width), min(r[1] + r[3], height)
                visible = max(x1 - x0, 0) * max(y1 - y0, 0)
                if r[2] * r[3] > 0 and visible / (r[2] * r[3]) >= 0.5:
                    found[n] = [round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1)]
                else:
                    log(f"  (cadre hors image : {name}/{n})")
        webp = self.out / f"{name}.webp"
        to_webp(png, webp)
        self.entries.append({"name": name, "file": f"{name}.webp", "view": view, "viewport": vp["label"], "width": width,
                             "height": height, "scale": vp["scale"], "description": desc, "boxes": found})
        log(f"  {name}: {webp.stat().st_size // 1024} Ko, {len(found)} cadres")

    def write_manifest(self) -> None:
        order = {s["name"]: i for i, s in enumerate(SHOTS + BLOC_SHOTS)}
        data = {"generated_for": "Camille — mardi 2026-09-29 (J-54), workspace fictif", "shots": sorted(
            self.entries, key=lambda e: order.get(e["name"], 999))}
        text = json.dumps(data, ensure_ascii=False, indent=1)
        (self.out / "manifest.json").write_text(text + "\n", encoding="utf-8")
        (self.out / "manifest.js").write_text(f"window.ARC_SHOTS = {text};\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Pilotage
# ---------------------------------------------------------------------------

def launch(pw):
    try:
        return pw.chromium.launch(channel="chrome")
    except Exception:  # noqa: BLE001 - repli sur le Chromium de Playwright
        return pw.chromium.launch()


def new_context(browser, vp):
    ctx = browser.new_context(viewport={"width": vp["width"], "height": vp["height"]}, device_scale_factor=vp["scale"],
                              color_scheme="dark", locale="fr-FR", timezone_id="Europe/Paris", reduced_motion="reduce",
                              is_mobile=vp["width"] < 500, has_touch=vp["width"] < 500)
    ctx.add_init_script(INIT_JS)
    return ctx


def open_view(page, base, route, wait, scroll=None, reload=True):
    page.goto(f"{base}/#/{route}")
    if reload:
        page.reload()                              # état propre malgré le changement de hash
    page.wait_for_selector(wait, timeout=20000)
    page.wait_for_timeout(500)
    page.evaluate("window.scrollTo(0, 0)")
    if scroll:
        sel, text = scroll[0], scroll[1]
        offset = scroll[2] if len(scroll) > 2 else 100      # sous l'en-tête fixe
        if not page.evaluate(SCROLL_JS, [sel, text, offset]):
            log(f"  (défilement impossible : {sel} {text})")
        page.wait_for_timeout(200)


def activity_id(base: str) -> int:
    import urllib.request
    with urllib.request.urlopen(f"{base}/api/activities?limit=5", timeout=20) as r:
        acts = json.load(r)["activities"]
    return next(a["id"] for a in acts if a["date"] == "2026-09-27")


def send(page, text):
    page.fill("#composer-input", text)
    page.press("#composer-input", "Enter")


def open_trace(page):
    page.evaluate("document.querySelectorAll('details.trace').forEach(d => d.open = true)")


def chat_boxes(extra=None):
    boxes = {"fil": B("#thread"), "saisie": B("#composer")}
    boxes.update(extra or {})
    return boxes


def capture_dashboard(rec, browser, base, only):
    ctx = new_context(browser, {**DESKTOP})
    page = ctx.new_page()
    act = activity_id(base)
    vp = {**DESKTOP, "label": "desktop 1440×900 @2x"}
    for shot in SHOTS:
        if only and shot["name"] not in only:
            continue
        open_view(page, base, shot["route"].format(act=act), shot["wait"], shot.get("scroll"))
        rec.snap(page, shot["name"], shot["view"], shot["desc"], vp, shot["boxes"], shot.get("full", False))
    ctx.close()


def capture_bloc(rec, browser, tmp, only):
    """Variante « bloc » du workspace (objectif de fin décembre + squelette), servie à part : les autres
    captures de la série ne changent pas."""
    shots = [sh for sh in BLOC_SHOTS if not only or sh["name"] in only]
    if not shots:
        return
    ws = tmp / "workspace-bloc"
    demo.build_demo(ws, bloc=True)
    dash = Service([sys.executable, str(REPO / "scripts/arc_serve.py"), "--workspace", str(ws), "--today", TODAY,
                    "--memory", "--port", "0"])
    try:
        vp = {**DESKTOP, "label": "desktop 1440×900 @2x"}
        for shot in shots:
            ctx = new_context(browser, {**DESKTOP})       # un contexte par capture : le routeur garde la semaine ouverte
            page = ctx.new_page()
            open_view(page, dash.url.rstrip("/"), shot["route"], shot["wait"], shot.get("scroll"), shot.get("reload", True))
            rec.snap(page, shot["name"], shot["view"], shot["desc"], vp, shot["boxes"], shot.get("full", False))
            ctx.close()
    finally:
        dash.stop()


def capture_mobile_dashboard(rec, browser, base, only):
    ctx = new_context(browser, MOBILE)
    page = ctx.new_page()
    vp = {**MOBILE, "label": "mobile 390×844 @3x"}
    for name, view, route, wait, desc, boxes in (
        ("mobile-aujourdhui", "Aujourd'hui", "", ".verdict", "Aujourd'hui sur téléphone : verdict « Alléger » et bilan du matin.",
         {"verdict": B(".verdict"), "pourquoi": B("#decision-encart-title", closest="section")}),
        ("mobile-semaine", "Semaine", "semaine", ".week", "Semaine sur téléphone : séances du jour par jour.",
         {"semaine": B(".week"), "aujourdhui": B(".day--today")}),
    ):
        if only and name not in only:
            continue
        open_view(page, base, route, wait)
        rec.snap(page, name, view, desc, vp, boxes)
    ctx.close()


def capture_chat(rec, browser, base, ws, port, tmp, only):
    wanted = lambda *names: not only or any(n in only for n in names)    # noqa: E731
    vp = {**DESKTOP, "label": "desktop 1440×900 @2x"}

    # Phase A : réponse figée à mi-parcours (marqueur « typing »).
    if wanted("chat-empty", "chat-typing"):
        svc = start_chat(ws, port, tmp, hold="typing")
        try:
            ctx = new_context(browser, DESKTOP)
            page = ctx.new_page()
            page.goto(f"{base}/chat.html")
            page.wait_for_selector("#composer-input:not([disabled])", timeout=20000)
            page.wait_for_timeout(500)
            rec.snap(page, "chat-empty", "Coach", "Page Coach avant la première question : conversation vide, contexte du coach à droite.",
                     vp, chat_boxes({"contexte": B("aside"), "commandes": B("#composer")}))
            send(page, USER_MESSAGE)
            page.locator(".msg--coach .msg__text", has_text="Sommeil").first.wait_for(timeout=30000)
            page.wait_for_timeout(600)
            open_trace(page)
            page.evaluate("document.querySelector('#thread').scrollTop = 1e6")
            rec.snap(page, "chat-typing", "Coach", "Le coach répond : trace des outils (HRV, FC de repos, readiness, météo) et bilan en tableau, réponse en cours.",
                     vp, chat_boxes({"trace": B("details.trace"), "reponse": B(".msg--coach .msg__text"), "tableau": B(".md-table"),
                                     "question": B(".msg--user")}))
            ctx.close()
        finally:
            svc.stop()

    # Phase B : tour complet, approbation puis accord.
    if wanted("chat-approval", "chat-done", "chat-samedi"):
        svc = start_chat(ws, port, tmp)
        try:
            ctx = new_context(browser, DESKTOP)
            page = ctx.new_page()
            page.goto(f"{base}/chat.html")
            page.wait_for_selector("#composer-input:not([disabled])", timeout=20000)
            send(page, USER_MESSAGE)
            page.wait_for_selector(".action .btn--primary", timeout=60000)
            page.wait_for_timeout(600)
            page.evaluate("document.querySelector('.action').scrollIntoView({block: 'center'})")
            rec.snap(page, "chat-approval", "Coach", "Carte d'approbation : seuil 5 × 6 min remplacé par EF 45 min, diff avant/après, boutons Appliquer / Refuser.",
                     vp, chat_boxes({"carte": B(".action"), "diff": B(".diff"), "appliquer": B(".action .btn--primary"),
                                     "refuser": B(".action .btn--ghost")}))
            page.click(".action .btn--primary")
            page.locator("#thread", has_text="Bonne récupération").wait_for(timeout=60000)
            page.wait_for_timeout(800)
            open_trace(page)
            page.evaluate("document.querySelector('#thread').scrollTop = 1e6")
            rec.snap(page, "chat-done", "Coach", "Après l'accord : séance planifiée, fichier de décision écrit, confirmation du coach.",
                     vp, chat_boxes({"fichier": B(".file-chip"), "confirmation": B(".msg--coach .msg__text", "Bonne récupération"),
                                     "carte": B(".action")}))
            send(page, "Et pour samedi ?")
            page.locator("#thread", has_text="Je refais le bilan").wait_for(timeout=60000)
            page.wait_for_timeout(800)
            page.evaluate("document.querySelector('#thread').scrollTop = 1e6")
            rec.snap(page, "chat-samedi", "Coach", "Deuxième question : la sortie longue de samedi est maintenue, créneau tôt le matin.",
                     vp, chat_boxes({"reponse": B(".msg--coach:last-of-type .msg__text")}))
            ctx.close()
        finally:
            svc.stop()

    # Phase C : mobile, carte d'approbation au premier plan.
    if wanted("mobile-coach"):
        svc = start_chat(ws, port, tmp)
        try:
            mvp = {**MOBILE, "label": "mobile 390×844 @3x"}
            ctx = new_context(browser, MOBILE)
            page = ctx.new_page()
            page.goto(f"{base}/chat.html")
            page.wait_for_selector("#composer-input:not([disabled])", timeout=20000)
            send(page, USER_MESSAGE)
            page.wait_for_selector(".action .btn--primary", timeout=60000)
            page.wait_for_timeout(600)
            page.evaluate("document.querySelector('.action').scrollIntoView({block: 'center'})")
            rec.snap(page, "mobile-coach", "Coach", "Le coach sur téléphone : carte d'approbation au premier plan.", mvp,
                     {"carte": B(".action"), "appliquer": B(".action .btn--primary"), "diff": B(".diff")})
            ctx.close()
        finally:
            svc.stop()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default="", help="noms séparés par des virgules (défaut : tout)")
    ap.add_argument("--out", type=Path, default=REPO / "docs/video/shots")
    args = ap.parse_args()
    only = {n.strip() for n in args.only.split(",") if n.strip()}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright manquant : uv run --with playwright scripts/video_capture.py", file=sys.stderr)
        return 2
    if not (shutil.which("cwebp") or shutil.which("ffmpeg")):
        print("cwebp ou ffmpeg requis (brew install webp).", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="arc-video-") as tmpname:
        tmp = Path(tmpname)
        ws = tmp / "workspace"
        log("workspace de démonstration…")
        demo.build_demo(ws)
        chat_port = free_port()
        start_chat(ws, chat_port, tmp).stop()          # écrit le [chat] du workspace avant le tableau de bord
        dash = Service([sys.executable, str(REPO / "scripts/arc_serve.py"), "--workspace", str(ws), "--today", TODAY,
                        "--memory", "--port", "0"])
        base = dash.url.rstrip("/")
        rec = Recorder(args.out, tmp)
        try:
            with sync_playwright() as pw:
                browser = launch(pw)
                log("tableau de bord (bureau)…")
                capture_dashboard(rec, browser, base, only)
                log("tableau de bord (mobile)…")
                capture_mobile_dashboard(rec, browser, base, only)
                log("bloc (variante du workspace)…")
                capture_bloc(rec, browser, tmp, only)
                log("chat…")
                capture_chat(rec, browser, base, ws, chat_port, tmp, only)
                browser.close()
        finally:
            dash.stop()
        if only:      # fusion avec le manifeste existant
            old = args.out / "manifest.json"
            if old.exists():
                kept = [e for e in json.loads(old.read_text(encoding="utf-8"))["shots"] if e["name"] not in only]
                rec.entries = kept + rec.entries
        rec.write_manifest()
    total = sum(p.stat().st_size for p in args.out.glob("*.webp"))
    log(f"{len(rec.entries)} captures, {total / 1e6:.1f} Mo dans {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
