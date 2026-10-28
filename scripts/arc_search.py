#!/usr/bin/env python3
"""Recherche plein texte dans l'historique du workspace — fonctions **pures**.

Aucun SQLite ici : l'index (table FTS5 `doc_chunk`, suivi `search_file`) et la requête vivent dans
`scripts/arc_index.py` (`index_search`, `search`). Ce module découpe les textes en passages, lit les
conversations du chat et construit l'expression `MATCH` d'une question en langage naturel.

Pourquoi un index plein texte et pas des embeddings ni un graphe : sur un workspace réel (≈ 900 fichiers,
≈ 0,9 M de jetons, 31 questions), BM25 sur des passages retrouve le bon fichier au moins aussi souvent qu'un
grep choisi par l'agent (77 % contre 71 % dans les 5 premiers) en lui rendant ≈ 25 fois moins de texte à lire
(≈ 1 000 jetons contre ≈ 24 000 pour les fichiers entiers). Les embeddings multilingues légers n'apportaient
rien seuls et peu en hybride ; les relations (séance ↔ chaussure, décision ↔ séance, santé ↔ douleur) sont déjà
dans les tables de l'index. Voir `docs/search.md`.

Ce que la recherche ne fait pas : elle ne remplace ni les commandes d'analyse (`decisions`, `prevention`,
`history-summary`…) ni la lecture du fichier trouvé. Les dates (« depuis quand… ») se lisent dans les tables.

Bibliothèque standard uniquement (CONTRIBUTING.md).
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import List, Optional, Tuple

# Taille maximale d'un passage (caractères). Un passage = une section Markdown (titre de niveau 1 à 3),
# coupée aux paragraphes au-delà. Approximation du projet : assez long pour garder le contexte d'une
# section, assez court pour qu'une réponse de 8 passages reste sous ≈ 3 000 jetons.
CHUNK_MAX_CHARS = 1200
# Texte rendu par résultat : le passage tronqué, pour que l'agent n'ouvre le fichier que si besoin.
RESULT_TEXT_CHARS = 800
DEFAULT_LIMIT = 8
MAX_LIMIT = 30
# Un mot plus long est cherché par son préfixe (`tendinite` → `tendin*`) : racinisation grossière, mais
# indépendante de la langue (le français n'a pas de racinisateur dans SQLite).
PREFIX_LEN = 6

SOURCES = ("workspace", "resources", "chat")

_STOPWORDS_FR = """
a à ai ait au aux avais avait avant avec avez avoir c ça ce ceci cela celle celles celui ces cet cette
comme comment d dans de des depuis dois doit donc du elle elles en est et été être eu fait faire faut
fin début il ils j je l la le les leur leurs lui m ma mais me même mes moi moins mon n ne ni nos notre
nous on ont ou où par pas pendant peu peut plus plutôt pour pourquoi qu quand que quel quelle quelles
quels qui quoi s sa sans se selon ses si son sont sous sur t ta te tes toi ton tous tout toute toutes
très tu un une vers vos votre vous y
""".split()
_STOPWORDS_EN = """
a about after an and are as at be been before but by can could did do does for from had has have how
i if in into is it its me my no not of on or our should so than that the their them then there these
they this to was we were what when where which who why will with would you your
""".split()
STOPWORDS = frozenset(_STOPWORDS_FR + _STOPWORDS_EN)

_ARC_BLOCK = re.compile(r"```arc[ \t]*\n(.*?)```", re.S)
_HEADING = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t#]*$")
_DATE_IN_NAME = re.compile(r"(?:^|/)(\d{4}-\d{2}-\d{2})[^/]*$")
_PHRASE = re.compile(r'"([^"]+)"')
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def fold(text: str) -> str:
    """Minuscules sans accents : la forme que voit le tokenizer `unicode61 remove_diacritics 2`."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def date_from_path(rel: str) -> Optional[str]:
    """`medical/2026-10-01_health.md` → `2026-10-01` ; None sans date en tête du nom."""
    match = _DATE_IN_NAME.search(rel)
    return match.group(1) if match else None


def _compact_arc(match: "re.Match") -> str:
    """Bloc ```arc → ses seules valeurs scalaires (résumé, nom, lieu…), jamais les séries."""
    body = match.group(1)
    try:
        data = json.loads(body)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    keep = [f"{k}: {v}" for k, v in data.items()
            if k not in ("arc", "kind") and isinstance(v, (str, int, float)) and not isinstance(v, bool)]
    return "\n".join(keep)[:CHUNK_MAX_CHARS // 2]


# Un reste plus court est rattaché au morceau précédent : un passage de quelques mots ne dit rien de son
# sujet et BM25 (normalisation par la longueur) le classerait trop haut.
CHUNK_MIN_CHARS = 200


def _hard_split(para: str, max_chars: int) -> List[str]:
    """Paragraphe trop long → morceaux coupés au dernier blanc avant `max_chars`, jamais au milieu d'un mot."""
    pieces = []
    while len(para) > max_chars:
        cut = para.rfind(" ", 0, max_chars)
        cut = cut if cut > max_chars // 2 else max_chars
        pieces.append(para[:cut].rstrip())
        para = para[cut:].lstrip()
    if para:
        pieces.append(para)
    return pieces


def _split_long(text: str, max_chars: int) -> List[str]:
    """Coupe aux paragraphes ; un paragraphe trop long est coupé aux blancs."""
    pieces: List[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        for part in _hard_split(para, max_chars):
            if current and len(current) + len(part) + 2 > max_chars:
                pieces.append(current)
                current = part
            else:
                current = f"{current}\n\n{part}" if current else part
    if current:
        if pieces and len(current) < CHUNK_MIN_CHARS:
            pieces[-1] = f"{pieces[-1]}\n\n{current}"
        else:
            pieces.append(current)
    return pieces


def chunk_markdown(text: str, max_chars: int = CHUNK_MAX_CHARS) -> Tuple[str, List[Tuple[str, str]]]:
    """Markdown → (titre du document, [(titre de section, passage), …]).

    Le bloc ```arc est réduit à ses valeurs scalaires (il porte souvent `summary`/`name`/`location`).
    """
    text = _ARC_BLOCK.sub(_compact_arc, text.replace("\r\n", "\n"))
    title = ""
    heading = ""
    sections: List[Tuple[str, List[str]]] = []
    lines: List[str] = []
    for line in text.split("\n"):
        match = _HEADING.match(line)
        if match:
            sections.append((heading, lines))
            heading, lines = match.group(2).strip(), []
            if not title:
                title = heading
            continue
        lines.append(line)
    sections.append((heading, lines))
    chunks: List[Tuple[str, str]] = []
    for head, body in sections:
        for piece in _split_long("\n".join(body), max_chars):
            chunks.append((head, piece))
    return title, chunks


def chat_turns(jsonl: str, max_chars: int = CHUNK_MAX_CHARS) -> List[Tuple[Optional[str], str]]:
    """Journal d'une session du chat (`.arc/chat/sessions/<id>.jsonl`) → [(date, échange), …].

    Un échange = le message de l'athlète et la réponse écrite du coach qui suit ; les appels d'outils et les
    approbations ne sont pas indexés (leur résultat est déjà dans les fichiers du workspace). Un échange long
    est coupé comme un passage Markdown.
    """
    turns: List[Tuple[Optional[str], str]] = []
    day: Optional[str] = None
    user = ""
    reply: List[str] = []
    part: Optional[str] = None

    def flush() -> None:
        if not user and not reply:
            return
        text = f"Athlète : {user}".strip()
        answer = "".join(reply).strip()
        if answer:
            text += f"\n\nCoach : {answer}"
        for piece in _split_long(text, max_chars):
            turns.append((day, piece))

    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        etype = event.get("type")
        if etype == "user_message":
            flush()
            ts = str(event.get("ts") or "")
            day = ts[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", ts) else day
            user, reply, part = str(data.get("text") or "").strip(), [], None
        elif etype == "text_delta":
            pid = data.get("part")
            if reply and pid and pid != part:
                reply.append("\n\n")              # nouveau bloc de texte (après un outil) : on ne colle pas
            part = pid or part
            reply.append(str(data.get("text") or ""))
    flush()
    return turns


def build_match(query: str) -> str:
    """Question en langage naturel → expression FTS5 `MATCH` (termes en OU, classés par BM25).

    Les mots vides (fr/en) sont retirés, les accents ignorés, les mots longs cherchés par préfixe ; une
    expression entre guillemets reste une phrase exacte. Chaîne vide si rien de cherchable ne reste.
    La syntaxe FTS5 brute n'est jamais transmise : chaque terme est mis entre guillemets.
    """
    terms: List[str] = []
    seen = set()

    def add(term: str) -> None:
        if term not in seen:
            seen.add(term)
            terms.append(term)

    for phrase in _PHRASE.findall(query):
        words = [fold(w) for w in _WORD.findall(phrase)]
        if words:
            add('"' + " ".join(words) + '"')
    rest = _PHRASE.sub(" ", query)
    for word in _WORD.findall(rest):
        lowered = word.lower()
        if lowered in STOPWORDS or len(lowered) < 2:
            continue
        folded = fold(word)
        add(f'"{folded[:PREFIX_LEN]}"*' if len(folded) > PREFIX_LEN else f'"{folded}"')
    return " OR ".join(terms)


def parse_kinds(value: Optional[str]) -> Optional[List[str]]:
    """`--kind activity,health` → ["activity", "health"] ; None sans filtre."""
    if not value:
        return None
    kinds = [k.strip() for k in value.split(",") if k.strip()]
    return kinds or None


def truncate(text: str, max_chars: int = RESULT_TEXT_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= max_chars else text[:max_chars].rstrip() + " …"


def format_text(result: dict) -> str:
    """Rendu `--text` : une ligne d'en-tête par résultat puis l'extrait."""
    if result.get("status") != "ok":
        return result.get("reason") or result.get("status") or ""
    lines = [f"{len(result['results'])} résultat(s) pour « {result['query']} »"]
    for hit in result["results"]:
        where = hit["path"] + (f" — {hit['heading']}" if hit.get("heading") else "")
        meta = " · ".join(x for x in (hit.get("date"), hit.get("kind")) if x)
        lines.append(f"\n## {where}" + (f" ({meta})" if meta else ""))
        lines.append(hit["text"])
    return "\n".join(lines)
