#!/usr/bin/env python3
"""Changer l'IA de la synchronisation automatique en une commande (`arc_llm.py sync`).

`./install.sh --llm <fournisseur>` règle le chat ET la sync, et relance toute l'installation.
Ici, seule la section `[sync]` de `config/workspace.user.toml` change : le chat, le planificateur
(cron, launchd, mode `watch`) et le reste de la configuration ne bougent pas. `daily-sync.sh`
relit `[sync]` à chaque exécution : le passage suivant utilise déjà le nouveau réglage.

  arc_llm.py sync                         état actuel (même chose que `sync status`)
  arc_llm.py sync anthropic [--model M]   runner claude + clé ANTHROPIC_API_KEY (facturé au jeton)
  arc_llm.py sync openrouter [--model M]  runner opencode + clé OPENROUTER_API_KEY
  arc_llm.py sync openrouter-free         idem, modèle gratuit « :free » (quota limité)
  arc_llm.py sync openai --model M [--base-url URL]   runner opencode + clé OPENAI_API_KEY
  arc_llm.py sync claude-subscription     retour à l'abonnement Claude (Claude Code connecté, sans clé)

Options communes : --dry-run (montre sans écrire), --json, --workspace W, --env-file PATH.

Règles :
  - la clé n'est JAMAIS écrite ni affichée : seul son NOM va dans `[sync].api_key_env`, la valeur
    reste dans llm.env (mode 600). Clé absente : refus (code 3), rien n'est écrit — une sync
    branchée sur une clé absente échouerait à chaque passage ;
  - chaque clé modifiée est affichée « ancienne → nouvelle », avec la commande pour revenir ;
  - les abonnements ChatGPT / Copilot restent sur `./install.sh --llm chatgpt|copilot
    --sync-subscription` (connexion et magasin dédié : voir docs/choisir-son-ia.md).

Codes de sortie : 0 appliqué (ou rien à changer), 2 usage, 3 clé absente ou illisible.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import arc_llm

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NO_KEY = 3
CHOICES = ("status", "anthropic", "openrouter", "openrouter-free", "openai", "claude-subscription")
# Clés de [sync] que cette commande possède. Les autres (mode, times, budget…) ne sont jamais touchées.
KEYS = ("runner", "model", "base_url", "api_key_env", "opencode_data_dir")


def _effective_sync(workspace: Path) -> Dict[str, Any]:
    import arc_llm_check
    return arc_llm_check._merged_sections(workspace).get("sync", {})


def _s(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def describe(sync: Dict[str, Any]) -> str:
    """Une ligne lisible : sur quoi tourne la sync aujourd'hui."""
    runner = _s(sync.get("runner")) or "claude"
    key = _s(sync.get("api_key_env"))
    model = _s(sync.get("model"))
    if _s(sync.get("opencode_data_dir")) and not key:
        return "abonnement via OpenCode (%s)" % (model or "modèle par défaut")
    if key:
        return "%s, clé API %s (facturé au jeton), modèle %s" % (runner, key, model or "par défaut")
    if runner == "claude":
        return "abonnement Claude (Claude Code connecté), modèle %s" % (model or "par défaut du compte")
    return "%s sans clé du coach (connexion propre à l'outil)" % runner


def choice_of(sync: Dict[str, Any]) -> str:
    """La sous-commande qui recréerait ce réglage, ou "" (réglage fait à la main ou abonnement OpenCode)."""
    runner, key, model = _s(sync.get("runner")) or "claude", _s(sync.get("api_key_env")), _s(sync.get("model"))
    if _s(sync.get("opencode_data_dir")) or _s(sync.get("base_url")):
        return ""
    model_opt = " --model %s" % model if model else ""
    if runner == "claude" and not key:
        return "claude-subscription" + model_opt
    if runner == "claude" and key == "ANTHROPIC_API_KEY":
        return "anthropic" + model_opt
    if runner == "opencode" and key == "OPENROUTER_API_KEY":
        return ("openrouter-free" if arc_llm.is_openrouter_free_model(model) else "openrouter") + model_opt
    if runner == "opencode" and key == "OPENAI_API_KEY" and model:
        return "openai" + model_opt
    return ""


def target(choice: str, model: str, base_url: str) -> Tuple[Optional[Dict[str, str]], str]:
    """Valeurs [sync] visées, ou (None, message d'erreur)."""
    if choice == "claude-subscription":
        if model and "/" in model:
            return None, "--model : identifiant Claude attendu (ex. claude-haiku-4-5), pas « fournisseur/modèle »."
        return {"runner": "claude", "model": model, "base_url": "", "api_key_env": "", "opencode_data_dir": ""}, ""
    entry = arc_llm.provider(choice) or {}
    if choice == "anthropic":
        model = model or entry.get("sync_model") or ""
        if "/" in model:
            return None, "--model : identifiant Claude attendu (ex. claude-haiku-4-5), pas « fournisseur/modèle »."
        return {"runner": "claude", "model": model, "base_url": "", "api_key_env": "ANTHROPIC_API_KEY",
                "opencode_data_dir": ""}, ""
    if choice in ("openrouter", "openrouter-free"):
        model = model or entry.get("sync_model") or ""
        if not model.startswith("openrouter/"):
            model = "openrouter/" + model
        if choice == "openrouter-free" and not arc_llm.is_openrouter_free_model(model):
            return None, "openrouter-free n'accepte qu'un modèle gratuit (identifiant finissant par « :free »)."
        return {"runner": "opencode", "model": model, "base_url": "", "api_key_env": "OPENROUTER_API_KEY",
                "opencode_data_dir": ""}, ""
    if choice == "openai":
        if not model:
            return None, "openai exige --model (ex. --model gpt-4.1-mini ; --base-url pour une autre API compatible OpenAI)."
        if not model.startswith("openai/"):
            model = "openai/" + model
        return {"runner": "opencode", "model": model, "base_url": base_url, "api_key_env": "OPENAI_API_KEY",
                "opencode_data_dir": ""}, ""
    return None, "Fournisseur inconnu : %s" % choice


def plan_changes(current: Dict[str, Any], wanted: Dict[str, str]) -> List[Dict[str, str]]:
    """Clés dont la valeur effective change. Une clé vide déjà absente/vide n'est pas réécrite."""
    out = []
    for key in KEYS:
        old, new = _s(current.get(key)), wanted[key]
        if key == "runner" and not old:
            old = "claude"  # défaut de daily-sync.sh
        if old != new:
            out.append({"key": key, "old": old, "new": new})
    return out


def run(args: argparse.Namespace) -> int:
    from coach_config import config_paths, set_toml_key
    from coach_setup import workspace_root

    out = arc_llm.Out(bool(args.json))
    workspace = workspace_root(args.workspace)
    current = _effective_sync(workspace)
    choice = args.provider or "status"
    if choice == "status":
        msg = "Synchronisation : %s." % describe(current)
        msg_hint = ("\nChanger : python3 scripts/arc_llm.py sync anthropic | openrouter | claude-subscription "
                    "(docs/choisir-son-ia.md#changer-lia-de-la-synchronisation).")
        out.final(True, msg + ("" if args.json else msg_hint), workspace=str(workspace),
                  sync={k: _s(current.get(k)) for k in KEYS}, description=describe(current))
        return EXIT_OK

    wanted, error = target(choice, _s(args.model), _s(args.base_url))
    if wanted is None:
        out.final(False, error, error="usage")
        return EXIT_USAGE
    if args.base_url and choice != "openai":
        out.final(False, "--base-url ne s'utilise qu'avec openai (API compatible OpenAI).", error="usage")
        return EXIT_USAGE

    warnings: List[str] = []
    key_var = wanted["api_key_env"]
    env_file = args.env_file or arc_llm.default_env_file()
    if key_var:
        unreadable = arc_llm.check_env_readable(env_file)
        if unreadable:
            out.final(False, unreadable, error="env_unreadable")
            return EXIT_NO_KEY
        if not arc_llm.read_env_var(env_file, key_var):
            hint = ("python3 scripts/arc_llm.py connect openrouter" if key_var == "OPENROUTER_API_KEY"
                    else "ajoutez la ligne %s=<votre clé> dans %s (chmod 600)" % (key_var, env_file))
            out.final(False, "Clé %s introuvable dans %s : rien n'a été changé. %s, puis relancez cette commande."
                      % (key_var, env_file, hint[0].upper() + hint[1:]), error="key_missing", key_env=key_var,
                      action=hint)
            return EXIT_NO_KEY
        if key_var == "ANTHROPIC_API_KEY" and os.environ.get("ANTHROPIC_API_KEY"):
            warnings.append("ANTHROPIC_API_KEY est exportée dans ce shell : retirez-la de votre profil, elle casse "
                            "Remote Control (docs/mobile.md). La sync la lit dans llm.env.")
    binary = "claude" if wanted["runner"] == "claude" else "opencode"
    # Mêmes dossiers que le PATH de daily-sync.sh (cron/launchd démarrent avec un PATH minimal).
    extra = [os.path.expanduser(d) for d in ("~/.local/bin", "~/.opencode/bin", "~/.claude/bin")]
    search = os.pathsep.join(extra + ["/opt/homebrew/bin", "/usr/local/bin", os.environ.get("PATH", "")])
    if not shutil.which(binary, path=search):
        warnings.append("%s introuvable dans le PATH : la sync en a besoin (voir docs/mobile.md)." % binary)

    changes = plan_changes(current, wanted)
    old_desc = describe(current)
    new_sync = dict(current)
    new_sync.update(wanted)
    new_desc = describe(new_sync)
    if old_desc != new_desc and _s(current.get("api_key_env")) != key_var:
        if key_var and not _s(current.get("api_key_env")):
            budget = _s(current.get("daily_budget_eur")) or "0.5"
            warnings.append("Facturation : abonnement → clé API facturée au jeton ; [sync].daily_budget_eur = %s € "
                            "plafonne la dépense quotidienne." % budget)
        elif not key_var:
            warnings.append("Facturation : clé API → abonnement Claude (limites de votre forfait). Claude Code doit "
                            "être connecté sur cette machine (claude, puis /login).")
    if choice == "openrouter-free" and _s(current.get("mode")) != "watch":
        warnings.append("Essai gratuit : 50 requêtes par jour sans crédits. Passez [sync].mode à \"watch\" pour ne "
                        "lancer le modèle que s'il y a du neuf (puis ./install.sh --daily-sync).")

    user_toml, _ = config_paths(workspace)
    if changes and not args.dry_run:
        for change in changes:
            set_toml_key(user_toml, "sync", change["key"], change["new"])

    lines = []
    if not changes:
        lines.append("Synchronisation déjà sur : %s. Rien à changer." % new_desc)
    else:
        verb = "Serait changé" if args.dry_run else "Changé"
        lines.append("%s dans %s :" % (verb, user_toml))
        lines += ["  [sync].%s : %s → %s" % (c["key"], c["old"] or "(vide)", c["new"] or "(vide)") for c in changes]
        lines.append("Synchronisation : %s." % new_desc)
        if not args.dry_run:
            lines.append("Aucune réinstallation : le prochain passage (cron, launchd ou watch) l'utilise déjà. "
                         "Tester : scripts/daily-sync.sh --dry-run")
        back = choice_of(current)
        lines.append("Revenir : " + ("python3 scripts/arc_llm.py sync %s" % back if back
                                     else "remettez les anciennes valeurs ci-dessus dans %s" % user_toml))
    lines += ["⚠ " + w for w in warnings]
    out.final(True, "\n".join(lines), workspace=str(workspace), dry_run=bool(args.dry_run), changes=changes,
              sync={k: new_sync.get(k, "") for k in KEYS}, description=new_desc, warnings=warnings)
    return EXIT_OK


def add_parser(sub: Any) -> None:
    sy = sub.add_parser("sync", help="changer l'IA de la synchronisation seule (sans toucher au chat)")
    sy.add_argument("provider", nargs="?", choices=CHOICES, help="cible ; sans argument : état actuel")
    sy.add_argument("--model", help="modèle (anthropic : claude-… ; openrouter : ID OpenRouter ; openai : obligatoire)")
    sy.add_argument("--base-url", help="avec openai : API compatible OpenAI autre que api.openai.com")
    sy.add_argument("--dry-run", action="store_true", help="montre les changements sans rien écrire")
    sy.add_argument("--json", action="store_true", help="un objet JSON (jamais de valeur de clé)")
    sy.add_argument("--workspace", help="workspace (défaut : ARC_WORKSPACE ou celui mémorisé)")
    sy.add_argument("--env-file", help="llm.env (défaut : $ARC_LLM_ENV ou ~/.config/ai-running-coach/llm.env)")
    sy.set_defaults(func=run)


if __name__ == "__main__":
    import sys
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_parser(ap.add_subparsers(dest="cmd", required=True))
    sys.exit(run(ap.parse_args(["sync"] + sys.argv[1:])))
