# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

AI 榨汁机 (project display name) is an AI end-to-end software delivery pipeline scheduler. The core abstraction is a **fixed 6-step pipeline** — Finder → Requirement → Plan → Design → DevTest → Deploy — not a general-purpose DAG. This constraint is load-bearing: the state machine, schema, and services all assume exactly those six steps in that order. (Python package names `scheduler`, `aijuicer_sdk`, `aijuicer_cli`, the `aijuicer` console command, and the `AIJUICER_` env-var prefix are kept as-is to avoid breaking imports and `.env` files — those are internal identifiers, not the user-facing brand.)

Canonical design spec: `docs/superpowers/specs/2026-04-20-aiclusterschedule-design.md` — consult it before making non-trivial changes, especially to the state machine or data model.

Milestone status: all 8 milestones are complete (M1–M8). See README.md for the per-milestone breakdown. What's where:

- `scheduler/` — FastAPI backend, state machine, services, SSE, Prometheus.
- `sdk/aijuicer_sdk/` — Agent Python SDK (decorator, auto-heartbeat, artifact atomic write + register).
- `sdk/examples/` — 6 step agents (`ai_finder` … `ai_deploy`).
- `cli/aijuicer_cli/` — `aijuicer` command (typer).
- `webui/` — Next.js 14 App Router + Tailwind + React Flow + SSE UI.
- `scripts/run_all.sh` — one-shot local launcher (scheduler + 6 agents + webui).

## Common commands

```bash
make install   # pip install -e ".[dev]" + pre-commit install
make migrate   # alembic upgrade head
make run       # uvicorn scheduler.main:app --reload :8000
make test      # pytest -v --cov=scheduler (needs TEST_DATABASE_URL or Docker)
make lint      # ruff check + ruff format --check
make fmt       # ruff format + ruff check --fix
make type      # mypy scheduler
```

Run a single test:
```bash
pytest scheduler/tests/test_state_machine.py::test_next_running_auto -v
pytest scheduler/tests -k approval -v    # pattern match across files
```

Tests default to `testcontainers` (requires Docker). To reuse an existing Postgres (much faster), set:
```bash
export TEST_DATABASE_URL=postgresql+asyncpg://aijuicer:aicluster@localhost:5433/aijuicer
```

The local dev Postgres recipe in README runs on **port 5433** (not 5432) — `.env` must match.

## Configuration

All settings load from env with prefix `AIJUICER_` via `scheduler/config.py` (pydantic-settings, reads `.env`). Required: `AIJUICER_DATABASE_URL`, `AIJUICER_REDIS_URL`, `AIJUICER_ARTIFACT_ROOT`. See `.env.example` for the full set.

## Architecture

### State machine (`scheduler/engine/state_machine.py`)

The heart of the system. All state values are enumerated in `State` and every transition must be validated via `transition()` / `validate_transition()`. `_build_allowed_transitions()` generates the allowed edge set from the `STEPS` tuple; do **not** hand-maintain a parallel list.

Invariant: each workflow has at most one running step at any time. Terminal states are `COMPLETED` and `ABORTED`. `AWAITING_MANUAL_ACTION` is the catch-all for failed steps after retries exhausted — from there, approval service's `rerun` / `skip` / `abort` drive recovery.

Helper entry points the services call into (don't reimplement these inline):
- `starting_state()` — initial state for a new workflow.
- `next_state_on_success(src)` — `<STEP>_RUNNING` → `<STEP>_DONE`.
- `next_state_on_failure(src)` — drives the retry / `AWAITING_MANUAL_ACTION` branch.
- `next_running_state(src, policy)` — auto/manual approval gate: if `policy[<next_step>] == "auto"` go straight to `<NEXT>_RUNNING`, otherwise `AWAITING_APPROVAL_<NEXT>`.

### Services layer (`scheduler/engine/`)

Three services operate on a shared `AsyncSession`:
- `WorkflowService` — create/list/get workflows; `advance_on_step_success` drives RUNNING → DONE → next state.
- `TaskService` — agent-facing lifecycle: `start` / `complete` / `fail` / `heartbeat`. On `fail`, retries (up to `settings.max_retries`) insert a new `StepExecution` row with `attempt + 1`; otherwise transitions workflow to `AWAITING_MANUAL_ACTION` and sets `failed_step`.
- `ApprovalService` — human-in-the-loop: `approve` / `reject` / `abort` / `rerun` / `skip`. `abort` is idempotent (no-op if already `ABORTED`). `skip` requires `AWAITING_MANUAL_ACTION` with `failed_step` set.

**Transaction contract**: services call `session.add(...)` and `await session.flush()` but never `commit()`. The API layer's `get_session` dependency (`scheduler/api/__init__.py`) owns commit/rollback via `Database.session()` context manager. Don't commit inside services.

Every state change also writes a `WorkflowEvent` row for audit. `request_id` is propagated via structlog's contextvar and stored on both `StepExecution.request_id` and `WorkflowEvent.request_id`.

### API layer (`scheduler/api/`)

FastAPI routers mounted in `scheduler/main.py`: `workflows`, `tasks`, `approvals`, `agents`, `artifacts`, `events`. Schemas in `scheduler/api/schemas.py`. Standard exception mapping: `InvalidTransition` → HTTP 409, `ValueError` → HTTP 400. `CORSMiddleware` is permissive (`allow_origins=["*"]`) because the UI and API are intentionally on different ports in local dev — tighten in deployment.

The DB singleton is set at app startup via `set_database(...)` and consumed by the `get_session` dependency. The singleton exists because `get_settings()` is called once at module load; don't re-instantiate `Database` per request.

### Observability (`scheduler/observability/`)

- `RequestIdMiddleware` reads/generates `X-Request-ID`, binds it via `bind_request_id(rid)` → structlog contextvar, echoes it back in the response header.
- `configure_logging` renames structlog's `event` key to `message` for JSON-log consumers and supports `json` / `console` formats. Re-running it is safe (calls `structlog.reset_defaults()`).
- Always use `get_logger(__name__)` + keyword args; do not use `print` (ruff `T20` will fail).

### Storage (`scheduler/storage/`)

SQLAlchemy 2.x async ORM against Postgres (asyncpg driver). Six tables mirror the spec: `workflows`, `step_executions`, `artifacts`, `approvals`, `agents`, `workflow_events`. `JSONB` is used for `input` / `output` / `payload` / `approval_policy`. The `agents.metadata` column is mapped as `metadata_` in Python (SQLAlchemy reserves `metadata`).

Schema changes require an Alembic migration in `alembic/versions/` — don't rely on `Base.metadata.create_all` outside tests.

### Task queue (`scheduler/storage/redis_queue.py`)

`TaskQueue` Protocol with two implementations: `RedisTaskQueue` (prod, Redis Streams — one `tasks:<step>` stream + `agents:<step>` consumer group per step) and `InMemoryTaskQueue` (tests, keeps `(step, payload)` tuples in a list).

**Ordering contract (spec § 3.4, load-bearing)**: service code never calls `xadd` directly. It calls `defer_xadd(session, step, payload)` which parks the payload on `session.info["pending_xadds"]`. `Database.session()` flushes those XADDs **only after** the DB transaction successfully commits — rollback discards them. This gives at-least-once delivery while preventing "orphan queue entries" if the DB write fails.

Startup in `main.py` creates the `RedisTaskQueue`, injects it into `Database`, and calls `ensure_consumer_groups()` (BUSYGROUP is swallowed) so the 6 groups exist before any agent connects.

### Agent SDK (`sdk/aijuicer_sdk/`)

Independent Python package (namespaced `aijuicer_sdk`), installed alongside `scheduler` via the same `pip install -e .[dev]`. Test discovery picks up `sdk/tests/` automatically (added to `testpaths`).

Core pieces:
- `Agent` — decorator-style registration (`@agent.handler`), handles `register` → XREADGROUP fetch loop → worker pool (bounded by `concurrency` semaphore) → `start` / `complete` / `fail` HTTP calls → XACK.
- `AgentContext` — `save_artifact` writes `<artifact_root>/<NN_step>/<key>` with `.tmp → fsync → rename` atomic layout; `load_artifact` reads from the same layout; `heartbeat` proxies to `/api/tasks/<id>/heartbeat`.
- `RetryableError` / `FatalError` — spec § 5.2 classification; unknown exceptions default to retryable.

M2 intentionally defers: artifact metadata POST (M5), HTTP fallback for non-shared FS (M5).

### Resumability (M3 — `scheduler/engine/recovery.py`, `scheduler/workers/heartbeat_monitor.py`)

**Startup recovery**: `run_startup_recovery(database)` scans `step_executions status='pending' AND workflow.status LIKE '%_RUNNING'` and re-registers a `defer_xadd` for each. The rationale: DB commit can succeed but XADD can fail (process crash between the two steps). On restart, this re-enqueues those tasks. Duplicate delivery is handled by `TaskService.start` returning `started=False` when the step is not `pending`; the SDK sees that and XACKs without invoking the handler.

**Heartbeat timeout monitor**: `scheduler/workers/heartbeat_monitor.run_monitor(...)` sweeps every `heartbeat_interval_sec // 2` seconds (default 15s) for `status='running' AND last_heartbeat_at < now() - heartbeat_timeout_sec`. Each timed-out step is passed through `TaskService.fail(retryable=True)`, which reuses the retry / `AWAITING_MANUAL_ACTION` branch — no parallel logic. The monitor is spawned from `main.py` lifespan and cancelled on shutdown.

**SDK auto-heartbeat**: while `_run_one` is executing a handler, it spawns a sibling task that calls `ctx.heartbeat()` every `heartbeat_interval` (default 30s); it's cancelled when the handler returns or raises. Manual `ctx.heartbeat(msg)` still works for progress messages.

### Event bus + SSE (M5 — `scheduler/engine/event_bus.py`, `scheduler/api/events.py`)

In-process pub/sub (single-scheduler deployment). The bus holds `dict[workflow_id, set[Queue]]` and offers `subscribe / unsubscribe / publish`. Backpressure: per-queue cap of 256, overflow drops the event and logs `event_bus.slow_subscriber`.

Integration is **automatic**: a SQLAlchemy `after_flush` listener on `Session` inspects `session.new` for `WorkflowEvent` rows and appends them to `session.info["pending_events"]`. `Database.session()` flushes both `pending_events` (to bus) and `pending_xadds` (to Redis) after a successful commit, events first. So any existing service code that writes a `WorkflowEvent` row automatically broadcasts — no explicit `publish()` call needed.

`GET /api/workflows/{id}/events` (sse-starlette) subscribes, emits a `ready` event, then forwards bus events with `event: <type>\ndata: <json>\n\n` and a `:ping\n\n` keepalive every 15s. Unsubscribes on client disconnect.

### Artifacts API (M6 — `scheduler/api/artifacts.py`, SDK `context.save_artifact`)

- SDK `ctx.save_artifact(key, data, content_type=...)` writes `.tmp → fsync → rename` atomically under `<artifact_root>/<NN_step>/`, computes sha256, then `POST /api/artifacts` with metadata.
- `POST /api/artifacts` is idempotent: uses Postgres `INSERT … ON CONFLICT (uq_artifact_key) DO UPDATE SET path, size_bytes, sha256` so a handler retry that re-writes the same file doesn't leave orphan rows.
- `GET /api/artifacts/{id}/content` enforces path safety (the resolved file must be under the workflow's `artifact_root` — defense against `..` traversal if a handler is buggy). Text / markdown / SVG / JSON / HTML get inlined with the right `Content-Type`; other binaries use `FileResponse` → browser downloads.

### Metrics (M8 — `scheduler/observability/metrics.py`, `/metrics`)

Seven counters/histograms/gauges per spec § 6.2; increments are hooked at:
- `TaskService.complete` → `step_duration_seconds{result=success}` observe.
- `TaskService.fail` → `step_duration_seconds{result=failure}` + `step_retries_total` if retrying + `manual_interventions_total` if exhausted.
- `WorkflowService.advance_on_step_success` → `workflows_total{status=COMPLETED}` on terminal.
- `ApprovalService.reject/abort` → `workflows_total{status=ABORTED}`.
- `heartbeat_monitor.scan_once` → `heartbeat_timeout_total{step}`.
- `agents.register` → `agents_online{step}` (gauge; decrement on offline is M+ work).
- `task_queue_depth{step}` is declared but not yet scraped from Redis — TODO tied to M7+ scale work.

Exposed at `/metrics` with proper `text/plain; version=0.0.4` content type.

### CLI (M4 — `cli/aijuicer_cli/`)

`typer` app with two sub-commands: `workflow …` and `agents …`. Installed as console-script `aijuicer`. All commands are thin wrappers over the same HTTP API the UI uses. Two conventions worth remembering:

1. `--input "@file.json"` reads JSON from a file; `--input '{"topic":"x"}'` takes a literal. Same for `--policy`. Single place: `_load_input` in `main.py`.
2. `aijuicer workflow logs <wf_id>` streams SSE. It uses `httpx.stream(...)` and doesn't try to parse SSE as JSON — just echoes `data:` lines so it composes with `| jq` when events carry JSON.

### Web UI (M5/M6 — `webui/`)

Next.js 14 App Router, Tailwind, React Flow 11 for the 6-step DAG, native `EventSource` for SSE. `NEXT_PUBLIC_API_BASE` (default `http://127.0.0.1:8000`) controls the backend URL. All API calls funneled through `webui/lib/api.ts`. Non-obvious pieces:

- DAG node state derived in `stepState(step, workflow.status, failed_step)` (see `lib/api.ts`). The workflow status encodes current step + phase, so we don't need a separate per-step status field.
- Detail page mixes SSE (`EventSource`) + 3-second polling of `GET /api/workflows/{id}` and `GET /api/workflows/{id}/artifacts`. SSE drives the timeline; state/artifact refresh is polled because SSE only carries events, not full state snapshots.
- Artifact preview dispatches by `content_type + extension`: markdown → `react-markdown`, json → pretty-print, image → `<img>`, html → sandbox iframe, other text → `<pre>`, unknown → download link.
- On macOS + pnpm, Next's native SWC binary can hit "different Team IDs" at `dlopen` when using Node shipped with Codex.app. Use `/opt/homebrew/bin/node` (via `PATH=/opt/homebrew/bin:$PATH`). `scripts/run_all.sh` already sets this for the `pnpm dev` child.

### One-shot launcher (M7 — `scripts/run_all.sh`)

Starts scheduler + 6 agents + (if `webui/node_modules` exists) Next.js dev server; logs go to `var/logs/*.log`; trap on INT/TERM/EXIT kills everything. Uses `wait -n` which means the script will exit as soon as any child dies — intentional so that a single crashed component surfaces fast. Run it in an interactive shell; running under `run_in_background` or similar non-tty contexts triggers the trap immediately.

## Test infrastructure

`scheduler/tests/conftest.py` uses a savepoint-per-test isolation pattern: each test opens an outer transaction + nested SAVEPOINT, so service code that calls `commit()` only commits to the savepoint; teardown rolls back the outer transaction. If you add code that calls `connection.begin()` directly or uses a separate engine, the isolation will leak between tests.

The session-scoped `database` fixture is constructed with an `InMemoryTaskQueue`, so any test that drives a full `Database.session()` (e.g. `test_redis_enqueue.py`, `test_api.py`) can inspect `task_queue.enqueued` to assert XADD payloads without needing a real Redis. Tests that use `db_session` directly (savepoint sessions) never trigger the post-commit XADD flush, which is why the existing service-layer unit tests remain unaffected by M2.

SDK tests live in `sdk/tests/`. They are pure unit tests (AsyncMock transport + tmp_path artifact root), so they run without Docker or a live Redis.

## Code conventions

- Python 3.12, `from __future__ import annotations` everywhere.
- Ruff rule `T20` bans `print` — use the structured logger.
- Mypy is `strict = true` globally; several modules (`storage.*`, `engine.*`, `api.*`, `main`, `tests.*`, `observability.*`) have documented strictness relaxations in `pyproject.toml` — prefer tightening, not expanding, those overrides.
- Line length 100. `alembic/versions/` is excluded from ruff.
