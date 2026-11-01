#!/usr/bin/env python3
"""Backend « mock » du chat coach : tours scriptés, déterministes, sans modèle ni réseau.

Sert aux tests du service et au développement de l'interface (`[chat].backend =
"mock"`). Chaque tour joue le même scénario en français :

  1. `text_delta` (introduction) ;
  2. `tool_start` / `tool_end` pour une lecture (`fs.read`, autorisée) ;
  3. `file_written` pour un fichier de décision — annoncé seulement, RIEN n'est écrit sur disque ;
  4. si le message parle de planification (« planifi », « garmin », « séance ») : appel
     `mcp:garmin.schedule_workouts` passé par `ctx.decide` puis `ctx.request_approval`,
     avec réaction à allow / deny / pending ;
  5. `usage` (coût faible) puis `done`.

Un message contenant « fatigu » joue la démonstration des captures de la doc (bilan matinal,
trace, carte d'approbation). Un message contenant « lent » fait attendre le tour (annulable) : c'est ce qui permet de
tester le 409 (tour déjà en cours) et l'interruption. Un message `[approbation] …` (reprise
après approbation tardive) exécute directement l'appel pré-approuvé.

Réglages optionnels dans `[chat]` : `mock_cost_eur` (défaut 0.01), `mock_slow_s` (défaut 5).

## Scénario rejoué (`mock_scenario`) — vidéos et captures

`[chat].mock_scenario = "<fichier JSON>"` (chemin absolu, ou relatif au workspace, ou relatif à la
racine du dépôt) fait rejouer des tours scriptés par le backend `mock`. Le fichier est lu une seule
fois au démarrage : une erreur (fichier absent, JSON invalide, regex invalide, étape inconnue) arrête
le service avec un message qui nomme le fichier et l'étape fautive. Aucune donnée n'est lue sur disque
pendant un tour : tout est dans le scénario, donc rejouable à l'identique.

```json
{"version": 1, "chunk_chars": 7, "chunk_delay_s": 0.03,
 "turns": [{"match": "vid[ée].*seuil", "cost_eur": 0.02, "steps": [
     {"text": "Je regarde ton bilan.", "part": "n1"},
     {"tool": {"id": "d1", "name": "fs.read", "summary": "Lecture de …", "result": "…", "delay_s": 0.6}},
     {"marker": "typing"},
     {"file_written": "planning/….md"},
     {"pause_s": 0.4},
     {"approval": {"tool": "mcp:garmin.schedule_workouts", "input": {}, "summary": "…", "diff": [],
                   "run": {"summary": "…", "result": "…"},
                   "allow": [{"text": "Fait."}], "deny": [{"text": "Rien ne change."}],
                   "pending": [{"text": "En attente de ta confirmation."}]}}]}]}
```

- `match` : expression régulière (`re.search`, casse ignorée) appliquée au message de l'athlète ; le
  premier tour qui correspond est joué. Aucune correspondance : comportement habituel du mock.
- `text` : émis par morceaux de `chunk_chars` caractères, `chunk_delay_s` secondes entre deux morceaux
  (le texte « se tape » ; valeurs par défaut du fichier, surchargeables par étape). `part` ouvre un
  nouveau bloc côté page (comme `text_delta.part`).
- `tool` : `tool_start`, attente `delay_s`, puis `tool_end` (`ok`, `result`).
- `file_written`, `pause_s`, `marker` (point d'arrêt nommé, sans effet par défaut).
- `approval` : passe par la politique (`ctx.decide`) puis l'approbation de l'athlète — le même chemin
  que `_call_schedule` — et joue `allow` / `deny` / `pending` selon la décision (`pending` termine le
  tour en attente d'approbation).
- `[chat].mock_scenario_speed` (défaut 1) divise tous les délais ; `[chat].mock_scenario_hold =
  "<marqueur>"` suspend le tour au marqueur nommé (jusqu'à interruption) : c'est ce qui permet de
  capturer une réponse « à mi-parcours » de façon déterministe.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Callable, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from arc_chat_backend import BackendError, ChatBackend, TurnContext  # noqa: E402

TOOL = "mcp:garmin.schedule_workouts"
# Contenu FIXE : l'approbation tardive ne vaut que pour cette charge exacte (payload_hash).
TOOL_INPUT = {"workouts": [{"date": "2026-10-01", "name": "EF 45 min", "duration_min": 45}]}
SUMMARY = "Jeudi 1er octobre : footing EF 45 min"
DIFF = [
    {"op": "-", "text": "Jeudi : fractionné 8 × 400 m"},
    {"op": "+", "text": "Jeudi : EF 45 min"},
    {"op": " ", "text": "Vendredi : repos"},
]
DECISION_PATH = "planning/2026-10-01_decision_mock.md"

# Démonstration (captures de la doc, workspace `tests/lib/synthetic.py` au 2026-09-29 : côtes
# prévues ce jour-là). Charge distincte du scénario des tests.
DEMO_INPUT = {"workouts": [{"date": "2026-09-29", "name": "EF 45 min", "duration_min": 45},
                           {"date": "2026-10-01", "name": "Côtes 8 × 90 s", "duration_min": 60}]}
DEMO_SUMMARY = "Mardi 29 septembre : footing EF 45 min, côtes jeudi"
DEMO_DIFF = [
    {"op": "-", "text": "Mardi : côtes 8 × 90 s"},
    {"op": "+", "text": "Mardi : EF 45 min"},
    {"op": " ", "text": "Mercredi : repos"},
    {"op": "+", "text": "Jeudi : côtes 8 × 90 s (si le bilan du matin remonte)"},
]


ENGINE = Path(__file__).resolve().parent.parent
HOLD_MAX_S = 3600.0
STEP_KINDS = ("text", "tool", "file_written", "pause_s", "marker", "approval")


def _fail(source: str, where: str, message: str) -> None:
    raise BackendError(f"Scénario du chat ({source}) — {where} : {message}")


def _number(source: str, where: str, value, default: Optional[float] = None) -> float:
    if value is None:
        return default if default is not None else 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        _fail(source, where, f"nombre positif attendu, {value!r} trouvé")
    return float(value)


def _check_steps(source: str, where: str, steps) -> None:
    if not isinstance(steps, list):
        _fail(source, where, "liste d'étapes attendue")
    for i, step in enumerate(steps):
        here = f"{where}[{i}]"
        if not isinstance(step, dict):
            _fail(source, here, "objet attendu")
        kinds = [k for k in STEP_KINDS if k in step]
        if len(kinds) != 1:
            _fail(source, here, f"une seule clé parmi {', '.join(STEP_KINDS)} attendue (trouvé : {sorted(step)})")
        kind = kinds[0]
        if kind == "text":
            if not isinstance(step["text"], str) or not step["text"]:
                _fail(source, here, "`text` : chaîne non vide attendue")
            _number(source, here + ".chunk_delay_s", step.get("chunk_delay_s"))
            if "chunk_chars" in step and (not isinstance(step["chunk_chars"], int) or step["chunk_chars"] < 1):
                _fail(source, here + ".chunk_chars", "entier ≥ 1 attendu")
        elif kind == "tool":
            tool = step["tool"]
            if not isinstance(tool, dict) or not all(isinstance(tool.get(k), str) and tool.get(k)
                                                       for k in ("id", "name", "summary")):
                _fail(source, here, "`tool` : objet avec `id`, `name`, `summary` (textes) attendu")
            _number(source, here + ".delay_s", tool.get("delay_s"))
        elif kind == "file_written":
            if not isinstance(step["file_written"], str) or not step["file_written"]:
                _fail(source, here, "`file_written` : chemin attendu")
        elif kind == "pause_s":
            _number(source, here, step["pause_s"])
        elif kind == "marker":
            if not isinstance(step["marker"], str) or not step["marker"]:
                _fail(source, here, "`marker` : nom attendu")
        elif kind == "approval":
            appr = step["approval"]
            if not isinstance(appr, dict) or not isinstance(appr.get("tool"), str) \
                    or not isinstance(appr.get("input"), dict) or not isinstance(appr.get("summary"), str):
                _fail(source, here, "`approval` : `tool`, `input` (objet) et `summary` attendus")
            diff = appr.get("diff", [])
            if not isinstance(diff, list) or not all(
                    isinstance(d, dict) and d.get("op") in ("-", "+", " ") and isinstance(d.get("text"), str)
                    for d in diff):
                _fail(source, here + ".diff", "liste de {\"op\": \"-\"|\"+\"|\" \", \"text\": …} attendue")
            for branch in ("allow", "deny", "pending"):
                _check_steps(source, f"{here}.{branch}", appr.get(branch, []))


def load_scenario(raw: str, workspace: Path) -> dict:
    """Charge et valide un scénario (voir l'en-tête du module). Lève `BackendError` (message français
    qui nomme le fichier et l'étape) ; renvoie le scénario avec ses expressions régulières compilées."""
    path = Path(raw).expanduser()
    candidates = [path] if path.is_absolute() else [Path(workspace) / path, ENGINE / path]
    found = next((c for c in candidates if c.is_file()), None)
    if found is None:
        raise BackendError(f"Scénario du chat introuvable : {raw!r} (cherché : "
                           f"{', '.join(str(c) for c in candidates)}).")
    source = found.name
    try:
        data = json.loads(found.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackendError(f"Scénario du chat ({source}) illisible : {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("turns"), list) or not data["turns"]:
        _fail(source, "racine", "objet avec une liste `turns` non vide attendu")
    chunk_chars = data.get("chunk_chars", 7)
    if not isinstance(chunk_chars, int) or isinstance(chunk_chars, bool) or chunk_chars < 1:
        _fail(source, "chunk_chars", "entier ≥ 1 attendu")
    delay = _number(source, "chunk_delay_s", data.get("chunk_delay_s"), 0.03)
    turns = []
    for i, turn in enumerate(data["turns"]):
        where = f"turns[{i}]"
        if not isinstance(turn, dict) or not isinstance(turn.get("match"), str):
            _fail(source, where, "objet avec `match` (expression régulière) attendu")
        try:
            pattern = re.compile(turn["match"], re.IGNORECASE)
        except re.error as exc:
            _fail(source, where + ".match", f"expression régulière invalide ({exc})")
        _check_steps(source, where + ".steps", turn.get("steps"))
        if not turn["steps"]:
            _fail(source, where + ".steps", "au moins une étape attendue")
        if "cost_eur" in turn:
            _number(source, where + ".cost_eur", turn["cost_eur"])
        turns.append({"pattern": pattern, "steps": turn["steps"], "cost_eur": turn.get("cost_eur")})
    return {"source": source, "chunk_chars": chunk_chars, "chunk_delay_s": delay, "turns": turns}


def match_turn(scenario: dict, message: str) -> Optional[dict]:
    """Premier tour du scénario dont l'expression régulière correspond au message, ou `None`."""
    return next((t for t in scenario["turns"] if t["pattern"].search(message)), None)


ATTACHMENT_LINE = re.compile(r"^Pièce jointe : (\S.*?) \((?:gpx|tcx|fit|image)\)[ \t]*\n?", re.MULTILINE)


class MockBackend(ChatBackend):
    name = "mock"

    def __init__(self, workspace: Path, config: dict):
        super().__init__(workspace, config)
        self.scenario: Optional[dict] = None
        raw = str(config.get("mock_scenario") or "").strip()
        if raw:
            self.scenario = load_scenario(raw, workspace)
        speed = config.get("mock_scenario_speed", 1)
        try:
            self.speed = float(speed)
        except (TypeError, ValueError):
            self.speed = 0.0
        if self.speed <= 0:
            raise BackendError(f"[chat].mock_scenario_speed : nombre > 0 attendu, {speed!r} trouvé.")
        self.hold = str(config.get("mock_scenario_hold") or "")

    def run_turn(self, ctx: TurnContext, user_message: str) -> None:
        emit = ctx.emit
        # Pièces jointes (#342) : le service préfixe (ou, après une commande « /… », suffixe) une ligne
        # `Pièce jointe : <chemin> (<type>)` par fichier. Le texte de l'athlète reste ce qui pilote le scénario.
        attached = [m.group(1) for m in ATTACHMENT_LINE.finditer(user_message)]
        if attached:
            user_message = ATTACHMENT_LINE.sub("", user_message).strip()
        text = user_message.lower()
        cost = float(self.config.get("mock_cost_eur", 0.01))

        def finish(reason: str) -> None:
            emit("usage", {"input_tokens": 120, "output_tokens": 40, "cache_read_tokens": 0, "cost_eur": cost})
            emit("done", {"reason": reason})

        if user_message.startswith("[approbation]"):
            emit("text_delta", {"text": "Reprise après approbation. "})
            demo = DEMO_SUMMARY in user_message
            if self._call_schedule(ctx, *((DEMO_INPUT, DEMO_SUMMARY, DEMO_DIFF) if demo else ())) != "allow":
                emit("text_delta", {"text": "Appel non autorisé par la politique."})
            finish("end_turn")
            return

        scripted = match_turn(self.scenario, user_message) if self.scenario else None
        if scripted is not None:
            if scripted["cost_eur"] is not None:
                cost = float(scripted["cost_eur"])
            self._play(ctx, scripted["steps"], finish)
            return

        if "fatigu" in text:
            self._demo_morning_check(ctx, finish)
            return

        if attached:
            emit("tool_start", {"id": "a1", "name": "fs.read", "summary": f"Lecture de {attached[0]}"})
            emit("tool_end", {"id": "a1", "ok": True, "summary": "Fichier lu"})
            emit("text_delta", {"text": f"J'ai bien reçu {len(attached)} pièce(s) jointe(s) : {', '.join(attached)}."})
            finish("end_turn")
            return

        emit("text_delta", {"text": "Je regarde ton plan de la semaine. "})
        emit("tool_start", {"id": "t1", "name": "fs.read", "summary": "Lecture de planning/active_objective.md"})
        emit("tool_end", {"id": "t1", "ok": True, "summary": "Objectif lu"})
        emit("text_delta", {"text": "Voici mon analyse. "})
        emit("file_written", {"path": DECISION_PATH})

        if "bilan" in text:
            # Réponse riche (titre, tableau, bloc ```arc recopié comme le ferait un modèle
            # trop littéral) : sert à vérifier le rendu de la page sans modèle.
            for chunk in ("\n\n## Bilan de la semaine\n\n", "| Jour | Séance | Durée |\n|---|---|---|\n",
                          "| Lun | EF | 45 min |\n| Mer | Fractionné | 1 h 05 |\n\n",
                          "```arc\n{\"type\": \"week\", \"load\": 412}\n```\n\n",
                          "**Prochaine étape** : sortie longue samedi."):
                emit("text_delta", {"text": chunk})
            finish("end_turn")
            return

        if "lent" in text:
            emit("text_delta", {"text": "Je réfléchis longuement… "})
            slow = float(self.config.get("mock_slow_s", 5))
            if ctx.cancelled.wait(slow):
                emit("done", {"reason": "interrupted"})
                return

        if any(word in text for word in ("planifi", "garmin", "séance", "seance")):
            outcome = self._call_schedule(ctx)
            if outcome == "pending":
                emit("text_delta", {"text": "La proposition attend ta confirmation (page ou notification)."})
                finish("pending_approval")
                return
            if outcome == "allow":
                emit("text_delta", {"text": "C'est fait : la séance est au calendrier."})
            else:
                emit("text_delta", {"text": "D'accord, je ne modifie rien."})
        else:
            emit("text_delta", {"text": "Rien à modifier pour l'instant."})
        finish("end_turn")

    # -- scénario rejoué -------------------------------------------------------------------

    def _sleep(self, ctx: TurnContext, seconds: float) -> bool:
        """Attend `seconds` (divisé par `mock_scenario_speed`) ; `True` si le tour est annulé."""
        return ctx.cancelled.wait(seconds / self.speed) if seconds > 0 else ctx.cancelled.is_set()

    def _play(self, ctx: TurnContext, steps: List[dict], finish: Callable[[str], None]) -> None:
        reason = self._play_steps(ctx, steps)
        if reason == "interrupted":
            ctx.emit("done", {"reason": "interrupted"})
        else:
            finish(reason)

    def _play_steps(self, ctx: TurnContext, steps: List[dict]) -> str:
        """Joue les étapes ; renvoie la raison de fin (`end_turn`, `pending_approval`, `interrupted`)."""
        emit = ctx.emit
        sc = self.scenario
        for step in steps:
            if "text" in step:
                size = step.get("chunk_chars", sc["chunk_chars"])
                delay = step.get("chunk_delay_s", sc["chunk_delay_s"])
                text = step["text"]
                for start in range(0, len(text), size):
                    payload = {"text": text[start:start + size]}
                    if step.get("part"):
                        payload["part"] = step["part"]
                    emit("text_delta", payload)
                    if self._sleep(ctx, delay):
                        return "interrupted"
            elif "tool" in step:
                tool = step["tool"]
                emit("tool_start", {"id": tool["id"], "name": tool["name"], "summary": tool["summary"]})
                if self._sleep(ctx, tool.get("delay_s", 0)):
                    return "interrupted"
                emit("tool_end", {"id": tool["id"], "ok": bool(tool.get("ok", True)),
                                  "summary": tool.get("result", "")})
            elif "file_written" in step:
                emit("file_written", {"path": step["file_written"]})
            elif "pause_s" in step:
                if self._sleep(ctx, step["pause_s"]):
                    return "interrupted"
            elif "marker" in step:
                if self.hold and step["marker"] == self.hold:
                    ctx.cancelled.wait(HOLD_MAX_S)
                    return "interrupted"
            elif "approval" in step:
                appr = step["approval"]
                run = appr.get("run") or {}
                outcome = self._call_schedule(
                    ctx, appr["input"], appr["summary"], appr.get("diff", []), tool=appr["tool"],
                    run_summary=run.get("summary", "Planification de la séance"),
                    run_result=run.get("result", "Séance planifiée (simulation)"))
                reason = self._play_steps(ctx, appr.get(outcome, []))
                if reason != "end_turn":
                    return reason
                if outcome == "pending":
                    return "pending_approval"
        return "end_turn"

    def _demo_morning_check(self, ctx: TurnContext, finish) -> None:
        """Scénario de démonstration (captures de la doc) : bilan matinal, trace, proposition.

        Valeurs fictives, cohérentes entre elles ; aucune donnée lue sur disque.
        """
        emit = ctx.emit
        steps = (
            ("d1", "skill", "Chargement de la compétence today", "Terminé"),
            ("d2", "fs.read", "Lecture de planning/Semaine_2026-09-28.md", "Séance du jour : côtes 8 × 90 s"),
            ("d3", "mcp:garmin.get_hrv_data", "Garmin : get_hrv_data", "HRV 52 ms (base 7 j : 63 ms)"),
            ("d4", "mcp:garmin.get_rhr_day", "Garmin : get_rhr_day", "FC de repos 54 bpm (+5)"),
            ("d5", "mcp:garmin.get_training_readiness", "Garmin : get_training_readiness", "Readiness 38 (faible)"),
            ("d6", "web.fetch", "Consultation de wttr.in (météo du lieu d'entraînement)", "16 °C, averses en soirée"),
        )
        emit("text_delta", {"text": "Je fais ton bilan du matin avant de décider.", "part": "n1"})
        for sid, name, summary, result in steps[:2]:
            emit("tool_start", {"id": sid, "name": name, "summary": summary})
            emit("tool_end", {"id": sid, "ok": True, "summary": result})
        emit("text_delta", {"text": "Séance exigeante prévue : je vérifie HRV, FC de repos et readiness.",
                            "part": "n2"})
        for sid, name, summary, result in steps[2:]:
            emit("tool_start", {"id": sid, "name": name, "summary": summary})
            emit("tool_end", {"id": sid, "ok": True, "summary": result})
        emit("file_written", {"path": "planning/2026-09-29_decision_readiness-basse.md"})
        for chunk in (
            "**Bilan du matin** — les trois signaux vont dans le même sens que ton ressenti :\n\n",
            "| Indicateur | Ce matin | Repère |\n|---|---|---|\n",
            "| HRV | 52 ms | base 63 ms |\n| FC de repos | 54 bpm | +5 bpm |\n| Readiness | 38 | faible |\n\n",
            "Des côtes sur cette fatigue apportent peu et coûtent cher en récupération. ",
            "**Je te propose** une sortie en endurance fondamentale de 45 min aujourd'hui, ",
            "et de décaler les côtes à jeudi si le bilan remonte.\n\n",
            "Créneau conseillé : **12 h 15 – 13 h 00** (sec, 16 °C).",
        ):
            emit("text_delta", {"text": chunk, "part": "r1"})
        outcome = self._call_schedule(ctx, DEMO_INPUT, DEMO_SUMMARY, DEMO_DIFF)
        if outcome == "pending":
            emit("text_delta", {"text": "La proposition attend ta confirmation (page ou notification).",
                                "part": "r2"})
            finish("pending_approval")
            return
        emit("text_delta", {"text": "C'est fait : la séance est au calendrier." if outcome == "allow"
                            else "D'accord, je garde le plan tel quel.", "part": "r2"})
        finish("end_turn")

    def _call_schedule(self, ctx: TurnContext, tool_input: dict = TOOL_INPUT, summary: str = SUMMARY,
                       diff: list = DIFF, tool: str = TOOL, run_summary: str = "Planification de la séance",
                       run_result: str = "Séance planifiée (simulation)") -> str:
        """Passe l'appel par la politique puis l'approbation ; renvoie allow | deny | pending."""
        verdict = ctx.decide(tool, tool_input)
        if verdict == "ask":
            verdict = ctx.request_approval(tool, tool_input, summary, diff)
        if verdict == "allow":
            ctx.emit("tool_start", {"id": "t2", "name": tool, "summary": run_summary})
            ctx.emit("tool_end", {"id": "t2", "ok": True, "summary": run_result})
            return "allow"
        return "pending" if verdict == "pending" else "deny"
