# Coach chat — implementation spec (shared by all contributors)

Companion of `deploy/chat/PLAN.md` (the *why*). This file is the *contract*: names,
paths, config keys, protocol. The interface code is `scripts/arc_chat_backend.py` —
**do not change its public names without updating this file**.

## Repo conventions (restated)
- Python **stdlib only**, except `scripts/arc_chat_claude.py` (imports `claude_agent_sdk`
  lazily; everything must import and test without it installed).
- French for docs, comments, user-facing strings; file names in English.
- Scripts are flat in `scripts/` (`arc_*.py`), shell helpers in `scripts/*.sh` sourcing
  `scripts/lib/config.sh`. bash 3.2 + BSD sed compatible (macOS CI). shellcheck `-S warning`.
- Tests: `unittest`, `python3 tests/run_tests.py --tier a|b|d` must stay green.
  Tier D = pure Python units (`tests/data/`), tier A = sandbox integration
  (`tests/install/`, `tests/lib/sandbox.py`), tier B = lint (`tests/lint/`).
  No live network or LLM in tests: use fakes / local HTTP servers on port 0.
- Goldens only regenerated intentionally (`ARC_UPDATE_GOLDEN=1`), diff must be additive.
- Config resolution: `config/workspace.toml` then `config/workspace.user.toml` key by key
  (`scripts/coach_config.py`: `read_toml`, `config_paths`, `set_toml_key`;
  bash: `toml_get section key default` from `scripts/lib/config.sh`).
- Secrets never in TOML: API keys live in `~/.config/ai-running-coach/llm.env`
  (mode 600, `KEY=value` lines), loaded by the chat service and daily-sync only.

## Files and owners

| Area | Files | Owner |
|---|---|---|
| Contract | `scripts/arc_chat_backend.py`, this file | lead (already written) |
| Chat service core | `scripts/arc_chat.py` (HTTP/SSE server, sessions, auth, CSRF, rate limit, budget, approvals, ntfy), `scripts/arc_chat_policy.py`, `scripts/arc_chat_mock.py`, `config/chat-policy.toml`, `tests/data/test_arc_chat_*.py` (core), `tests/install/test_chat_service.py` | agent **core** |
| Backends | `scripts/arc_chat_claude.py`, `scripts/arc_chat_opencode.py`, `scripts/arc_chat_tools.py`, `tests/data/test_arc_chat_claude.py`, `tests/data/test_arc_chat_opencode.py`, `tests/data/fixtures/chat/*` | agent **backends** |
| Frontend | `web/chat.html`, `web/js/chat.js`, `web/css/chat.css`, nav item in `web/js/app.js`, `chat_enabled` in `arc_index.settings()`, local `/api/chat/*` proxy in `scripts/arc_serve.py`, delete `web/chat-prototype.*`, related tests + goldens | agent **frontend** |
| Ops / cron | `config/workspace.toml` (`[chat]` + `[sync]` additions), `scripts/daily-sync.sh` (`opencode` runner, API-key mode, budget), `scripts/coach-chat.sh` (service), `install.sh` (`--llm`, `--chat`, budget flags), `scripts/coach_doctor.py` checks, `deploy/chat/traefik/*`, `.gitignore` if needed, their tests, docs for cron/install (`docs/mobile.md`, `docs/configuration.md` `[sync]`/`[chat]` keys) | agent **ops** |
| Chat docs | `docs/dashboard/chat.md`, mkdocs nav, README/index mentions | lead, after integration |

Never edit a file owned by another agent; if you need a change there, write it down in
your final report.

## Configuration keys

```toml
[chat]
enabled = false
backend = "claude"                 # "claude" | "opencode" | "mock"
model = "claude-sonnet-5-5"        # opencode: provider/model id, e.g. "openrouter/deepseek/deepseek-v4.1-flash"
base_url = ""                      # opencode + OpenAI-compatible endpoint other than OpenRouter
api_key_env = "ANTHROPIC_API_KEY"  # NAME of the variable in llm.env / environment
port = 8766                        # chat service, 127.0.0.1 unless listen is set
listen = "127.0.0.1"
auth = "local"                     # "local" (loopback only, no identity header) | "proxy"
auth_header = "X-authentik-username"   # proxy mode: header set by forward-auth (Authelia: "Remote-User")
allowed_users = []                 # proxy mode; empty = any authenticated user
trusted_proxies = ["127.0.0.1"]    # proxy mode: source IPs allowed to connect
allowed_hosts = []                 # Host header allowlist (empty = derived from public_url + loopback)
public_url = ""                    # e.g. "https://coach.example.com" — needed for ntfy buttons
daily_budget_eur = 2.0
usd_eur_rate = 0.92                # providers report USD
max_turns = 30
rate_limit_per_min = 6             # turns per user per minute
approval_wait_s = 600              # in-turn wait before a proposal becomes "pending"
approval_ttl_s = 86400             # pending proposal lifetime
ntfy_approvals = true              # push an "Ouvrir" button (needs [notifications] + public_url)
ntfy_quick_approve = true          # also "Appliquer / Refuser" buttons (single-use tokens) — only sent when [notifications].ntfy_token_file is set
ntfy_token_ttl_s = 1800

[sync]                             # existing keys unchanged; additions:
runner = "claude"                  # + "opencode"
model = ""                         # opencode (required) / claude API mode (optional --model)
base_url = ""
api_key_env = ""                   # set → API mode (claude: ANTHROPIC_API_KEY; opencode: OPENROUTER_API_KEY…)
daily_budget_eur = 0.5             # enforced only when the runner reports cost
```

Default models when `install.sh --llm` writes them: `--llm openrouter` → chat + sync
`openrouter/deepseek/deepseek-v4.1-flash` (exact id verified at implementation, keep one
constant); `--llm anthropic` → chat `claude-sonnet-5-5`, sync `claude-haiku-4-5`.

## HTTP API (chat service, all under `/api/chat`)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/chat/status` | `{enabled, backend, model, user, budget: {spent_eur, limit_eur}, ntfy: bool}` |
| GET | `/api/chat/healthz` | `{ok, backend_check}` — no auth required only from loopback |
| GET | `/api/chat/sessions` | list `{id, title, created, updated, cost_eur, pending_approvals}` newest first |
| POST | `/api/chat/sessions` | `{}` → `{id}` |
| GET | `/api/chat/sessions/{id}` | meta + full event log (to redraw after reload) |
| POST | `/api/chat/sessions/{id}/messages` | body `{"text": str}` → **SSE stream** of events until `done`/`error` |
| POST | `/api/chat/sessions/{id}/interrupt` | cancels running turn |
| GET | `/api/chat/approvals/{approval_id}` | pending approval detail (deep link `chat.html#approval=<id>`) |
| POST | `/api/chat/approvals/{approval_id}` | body `{"decision": "allow"|"deny"}` |
| POST | `/api/chat/approve/{token}/{allow|deny}` | ntfy quick action; token auth, no SSO (dedicated Traefik router) |

- Every POST requires header `X-ARC-Chat: 1`; if `Origin` is present it must match the
  request Host; if `Sec-Fetch-Site` is present it must be `same-origin` (except the
  `/approve/{token}` route, which requires `X-ARC-Chat: 1` only — ntfy sets it via
  `headers.X-ARC-Chat=1`). No CORS headers ever.
- Host header checked against `allowed_hosts` (+ loopback names in local mode).
- `auth = "local"`: service refuses to start if `listen` is not loopback.
  `auth = "proxy"`: peer IP must be in `trusted_proxies`; `auth_header` must be present
  (and in `allowed_users` when non-empty) on every route except `/approve/{token}` and
  loopback `/healthz`. Missing → 401 JSON `{"error": "…"}`.
- One running turn per session (409 otherwise). Budget reached → SSE `error` + `done`
  `{"reason": "budget"}` without calling the backend. Rate limit → 429.
- SSE: `Content-Type: text/event-stream`, `Cache-Control: no-store`,
  `X-Accel-Buffering: no`; a `: ping` comment every 15 s.

## Persistence (`<workspace>/.arc/chat/`, gitignored, disposable)
- `sessions/<id>.json` — meta `{id, title, created, updated, backend, model, backend_state, cost_eur}`
- `sessions/<id>.jsonl` — one event per line `{"ts", "type", "data"}` incl. `user_message`
  (type `user_message`, `{"text"}`; stored only, never streamed).
- `approvals.json` — `{approval_id: {session_id, tool, input, hash, summary, diff, status,
  created, expires_at, token_hashes: {allow: sha256, deny: sha256}}}`.
- `spend-YYYY-MM-DD.json` — `{"chat_eur": float}` (the cron writes `sync_eur` in
  `<workspace>/logs/.sync-spend-YYYY-MM-DD`, owned by ops).
- Session ids and approval ids: `secrets.token_urlsafe(12)`; tokens `token_urlsafe(24)`.

## Approval flow
1. Backend calls `ctx.decide(tool, input)` → policy says `ask` for Garmin/intervals writes.
2. `ctx.request_approval(tool, input, summary, diff)` → service creates the approval,
   emits `approval_request`, sends ntfy after 60 s if still undecided (or immediately if no
   SSE client is attached), then waits up to `approval_wait_s`.
3. Decision in page / ntfy → `approval_resolved` + returns `allow`/`deny` to the backend.
4. Timeout → returns `pending`; backend tells the model the change awaits approval;
   turn ends with `done {"reason": "pending_approval"}`.
5. Later decision on a pending approval: `deny` → recorded; `allow` → the service
   **resumes the session** with a new turn whose user message is
   `"[approbation] L'athlète a approuvé la proposition <id> (<summary>). Exécute exactement cet appel maintenant."`
   and the policy auto-allows only the matching `payload_hash` for that turn.
   The resume is queued per session and drained when the session's turn slot is released
   (and at service start for `allowed` approvals whose `resume` is still `queued`). If it
   cannot run (budget, backend error, the model did not make the approved call) the approval
   becomes `unexecuted`, an `error` event is logged, `approval_resolved` carries
   `"unexecuted"` and ntfy sends "Proposition approuvée mais non exécutée : <summary>".
   Interrupting a turn while an approval waits sets it to `cancelled` (event decision
   `"cancelled"`), not `denied`. Whoever expires a record logs `approval_resolved: expired`.
   `ctx.config["turn_budget_eur"]` (float) is the remaining daily budget at turn start.
6. ntfy message (via `[notifications]`, reuse `scripts/notify.sh` config semantics:
   `ntfy_url`, `ntfy_topic`, `ntfy_token_file`): title "Coach : confirmation demandée",
   body = `summary` only (no health values), `Actions` header:
   `view, Ouvrir, <public_url>/chat.html#approval=<id>` and, if quick approve,
   `http, Appliquer, <public_url>/api/chat/approve/<allow_token>/allow, method=POST, headers.X-ARC-Chat=1, clear=true; http, Refuser, …/deny, …`.
   Tokens single-use (both burned on first use), expire after `ntfy_token_ttl_s`, only
   sha256 stored, bound to approval id + payload hash.

## Policy (`config/chat-policy.toml`, `scripts/arc_chat_policy.py`)
`decide(tool, input) -> "allow" | "ask" | "deny"` on canonical names:
- `fs.read`, `fs.list`: allow inside the workspace, deny outside and for secret-looking
  paths (`config/workspace.user.toml`, `.env`, `*.token`, `.garminconnect`).
- `fs.write`: allow only under `activities/ medical/ nutrition/ planning/ rapports/ gear/`
  (+ `.arc/chat/` never through the model); deny elsewhere.
- `shell`: allow only commands matching an allowlisted script prefix
  (`python3 scripts/arc_index.py`, `python3 scripts/arc_log.py`,
  `python3 scripts/arc_race_pacing.py`, `python3 scripts/analyze_gpx.py`,
  `python3 scripts/compare_course.py`, `python3 scripts/download_fit.py`, …) with no shell
  metacharacters (`; | & $ \` > < ( ) \n`); deny otherwise.
  Shell hardening: no `\ ~ * ? [ ] { } ! #` either; every option must be declared for the
  script in `[shell.scripts."scripts/x.py"]` (`flags`, `value_options`, `read_options`,
  `output_options`, `multi_value_options` for argparse `nargs="*"/"+"`; unknown option → deny;
  a value starting with `-` → deny; `--workspace` is never accepted); every path-like argument must resolve inside the
  workspace (no absolute path, no secret, no `.arc/`) and output options must land under
  `[fs].write_dirs`. `coach_doctor.py` is not allowlisted (reads Garmin tokens).
- `fs.list`: `path` as `fs.read`, plus the `glob` key (string or list) is checked against
  `secret_patterns` (either direction fnmatch, real expansion under data dirs; brace expansion
  over 64 items or nesting over 3 → deny, never truncated); comparisons are case-insensitive
  (`casefold`). `pattern` (search regex) is not a path, but a content search (`pattern` present)
  must target a directory of `[fs].write_dirs` or `[fs].search_dirs`.
- `web.fetch`: allow listed domains (`wttr.in`, `overpass-api.de`, `nominatim.openstreetmap.org`)
  — http(s) only, parsed with `urlsplit`, no `\`, `%` or userinfo in the authority, ASCII host,
  default port, hostname equal to or a true subdomain of a listed domain; deny otherwise. `web.search`: deny.
- `task`, `skill`: allow (agents limited by `[agents].enabled` already).
- `mcp:garmin.*` / `mcp:intervals.*`: reads allow; writes **ask** (explicit list:
  `schedule_workout(s)`, `schedule_week`, `delete_workout(s)`, `unschedule_workout`,
  `upload_workout(s)`, `upload_course`, `delete_course`, `create_*_workout`, `add_*`,
  `set_*`, `log_*`, `create_custom_food`, `update_custom_food`, `delete_*`,
  `add_or_update_event`, `create_event`, `bulk_create_events`, `update_event`,
  `delete_event(s)*`, `request_reload`; intervals fork (#165): every `icu_create_*`,
  `icu_update_*`, `icu_delete_*`, `icu_bulk_*`, `icu_add_*`, `icu_apply_*`,
  `icu_duplicate_*`; reads `icu_get_*`/`icu_search_*`/`icu_list_*`, while
  `icu_download_*` — which writes a local file — asks); unknown tool on those servers → ask.
- `other:*` → deny. Pre-approved hashes (resume) → allow.

## Backend adapters (details for agent backends)
- `claude`: Claude Agent SDK (Python `claude-agent-sdk`). Options: `cwd=workspace`,
  `setting_sources=["project"]`, `model`, permission callback → `ctx.decide` /
  `ctx.request_approval`, partial messages → `text_delta`, `resume` with the SDK session id
  stored in `ctx.backend_state["sdk_session_id"]`, cost from the result message
  (USD → EUR via `usd_eur_rate`) → `usage`. Append `SYSTEM_ADDENDUM` to the system prompt.
  API key from env (`api_key_env`, loaded from llm.env by the service). Verify every name
  against the official SDK docs/source — never guess.
- `opencode`: spawn and supervise `opencode serve` (127.0.0.1, free port, cwd = workspace,
  generated project-local config under `.arc/chat/opencode/` with provider/model/base_url,
  MCP garmin from the workspace install, permissions `ask` for everything the policy may
  ask so the adapter receives permission events). Use its HTTP API: create/reuse session
  (`ctx.backend_state["opencode_session_id"]`), send prompt, consume its event stream,
  answer permission requests after `ctx.decide`/`request_approval`, map text/tool/usage
  events. Pin a tested OpenCode version constant. Verify endpoints against official docs
  / source — never guess.
- Both: map native tool names → canonical names; emit `file_written` for successful
  `fs.write`; `tool_start/tool_end` summaries in French, short; honour `ctx.cancelled`.
