# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Product Requirement Agent — turns a product idea into a Chinese PRD via a research → write pipeline. Two entry surfaces share the same agent code:
- a FastAPI + React UI (`POST /api/ideas`, history page, regenerate dialog), and
- an AIJuicer pipeline node (`requirement` step), so this service can plug into the 6-step pipeline `idea → requirement → plan → design → devtest → deploy`.

Postgres for everything; SQLite (aiosqlite) for tests.

## Commands

### Backend (`backend/`)
- Install: `pip install -r requirements.txt`
- Dev server: `uvicorn app.main:create_app --factory --reload --port 8010` — must use `--factory`; the frontend's Vite proxy expects port **8010**.
- Migrations: `alembic upgrade head` (config in `backend/alembic.ini`).
- All tests: `pytest` (run from `backend/`; `asyncio_mode = "auto"`)
- Single test: `pytest tests/test_writer.py::test_name -v`
- Tests stub `OPENAI_API_KEY` / `TAVILY_API_KEY` and use `sqlite+aiosqlite:///./test.db` via `conftest.py` — no real services needed.

### AIJuicer worker (`backend/`)
- Run: `python -m app.aijuicer_node` (separate long-running process; SDK blocks on Redis Streams).
- Env: `AIJUICER_SERVER`, `AIJUICER_REDIS_URL`, `AIJUICER_AGENT_NAME` (default `ai-requirement`), `AIJUICER_CONCURRENCY` (default 1 — single in-flight task; raise carefully because OpenAI/Tavily rate limits bite first).
- **The worker has no `--reload`.** Edits to `aijuicer_node.py`, `agent/*.py`, `models.py`, `database.py`, etc. require killing and restarting the process — `pkill -f "app.aijuicer_node"`, then re-run.

### Frontend (`frontend/`)
- Install: `npm install` — Node ≥ 22. If Vite crashes on `Cannot find module '@rolldown/binding-darwin-*'`, blow away `node_modules` + `package-lock.json` and reinstall; npm sometimes skips optional native deps.
- Dev: `npm run dev` (Vite on port **3010**, proxies `/api` → `http://localhost:8010`; Playwright E2E uses the same 3010).
- Build: `npm run build`. Lint: `npm run lint`.
- Stack: React 19, React Router 7, Tailwind v4 (with `@theme` tokens in `src/index.css`), TypeScript.

### Required env (`backend/.env`)
`DATABASE_URL`, `OPENAI_API_KEY`, `TAVILY_API_KEY`. Optional `OPENAI_MODEL` (default `gpt-4o`), `PORT`. See `backend/app/config.py` — `Settings` requires `DATABASE_URL` even for the AIJuicer worker entrypoint.

## Architecture

### Two entry paths, one agent core
Both paths reuse `agent/researcher.py` (Tavily) + `agent/writer.py` (OpenAI), and both write the same `Idea` + `Document` rows. Only the scaffolding differs.

**FastAPI path (`POST /api/ideas` and `POST /api/ideas/{id}/regenerate`):**
1. Route persists/loads `Idea`, sets status, schedules a `BackgroundTasks` callback.
2. Callback → `agent.orchestrator.run_agent(idea_id, rerun_instruction=...)` — opens its **own** `SessionLocal` (the request session is gone by then); never pass the request-scoped `AsyncSession` into agent code.
3. `AgentOrchestrator.process()` walks `Idea.status` through `researching → writing → completed` (or `failed`), **deletes any prior `Document` for that idea**, then inserts the new one. Clients poll `GET /api/ideas/{id}` then `GET /api/ideas/{id}/document`.

**AIJuicer path (`app/aijuicer_node.py`, SDK ≥ 0.7):**
1. Handler signature is `async def handle(ctx)` — single argument; `ctx.input` / `ctx.attempt` / `ctx.workflow_id` / `ctx.step` etc. expose everything (no `task` dict).
2. Idea text is read from upstream artifact `await ctx.load_artifact("idea", "idea.md")`. Missing artifact → `FatalError` (no retry). Right after loading, the upstream `idea.md` is mirrored to disk at `<PROJECT_ROOT>/<ctx.project_name>/idea.md` (default `PROJECT_ROOT=/Users/lapsdoor/phantom`, override via env / `Settings.project_root`). Mirror failures log but never abort the task.
3. Rerun feedback is read from `ctx.input.user_feedback[ctx.step]` only — that's where AIJuicer webui's RerunDialog writes. Empty / missing → first run.
4. Same `Researcher` + `PrdWriter` runs.
5. Output is uploaded as `await ctx.save_artifact("requirements.md", ...)` (plural — matches the contract downstream `plan` step expects), then `_persist_to_db()` mirrors it locally so the History page surfaces it alongside UI-submitted PRDs. **`Idea.id` is set to `workflow_id`** so reruns of the same workflow hit the same row. DB failures here are logged-and-swallowed on purpose: the artifact is already with the scheduler and raising would cause an unwanted SDK retry that re-bills the LLM call.

### One Document per Idea (hard invariant)
`Idea.document` is `relationship(uselist=False)` and `GET /api/ideas/{id}/document` uses `scalar_one_or_none()`. Anything that creates a 2nd Document for the same Idea breaks the route at read time. Both rerun paths therefore **delete the old Document before inserting the new one**.

### Worker doesn't share lifespan
`app/database.py` defines `SessionLocal = None` and only hydrates it in `init_db()`, called from FastAPI lifespan. The AIJuicer worker is a separate process that never runs lifespan — so `aijuicer_node.py` builds its own session factory via `_get_session_maker()` (lazy, calls `create_session_factory(create_engine())`). Don't reach for `app.database.SessionLocal` from worker code.

### Writer behavior worth knowing
- System prompt enforces a fixed 9-section Chinese PRD template; tests assert Chinese strings. Preserve this unless explicitly changing the product.
- On rerun (`rerun_instruction` is non-empty), the writer:
  1. Prepends a high-priority directive block at the **top** of the user prompt ("最高优先级，必须严格执行；与反馈冲突的旧写法必须直接覆写").
  2. Appends a self-check footer asking the model to verify each instruction point is reflected.
  3. Suffixes the system prompt with a "this is a rerun" notice.
  4. Drops `temperature` from 0.7 → **0.3** for fidelity.

  Conflicts with hardcoded sections (e.g. "去掉 7. MVP范围") rely on this combination to be respected — fragile area; if reruns start being ignored, check this stack first before assuming a transport bug.
- `_strip_outer_fence()` post-processes every model response to unwrap a single outer ```` ``` ```` (with or without `markdown` lang tag). Without this, gpt-4o occasionally fences the whole document and `.prose pre` paints the entire page black.

### HTTP surface
- Ideas: `POST /api/ideas`, `GET /api/ideas`, `GET /api/ideas/{id}`, `POST /api/ideas/{id}/regenerate`, `GET /api/ideas/{id}/document`
- Documents: `GET /api/documents`, `GET /api/documents/{id}`
- `regenerate` returns 409 if the idea is currently `researching` or `writing`.

### Frontend regenerate UX
`components/RegenerateModal.tsx` is the in-app rerun dialog (used from history list). Buttons inside `<Link>` cards must `e.preventDefault()` + `e.stopPropagation()` to avoid the surrounding navigation taking over.

### Tests
`tests/conftest.py` rebuilds the SQLite schema per test via `Base.metadata.create_all`, then overrides `get_db` on the app instance. When writing route tests, reuse the `app` fixture — instantiating `create_app()` directly loses the override.

## Conventions

- **PRD output is Chinese.** Don't quietly switch languages.
- Semi-structured logging only (see `app/logging_setup.py`). File sink defaults to `/Users/lapsdoor/phantom/logs/ai-requirement.log` (override via `LOG_DIR` / `SERVICE_NAME` env or `Settings.log_dir` / `Settings.service_name`). `request_id` is automatic via middleware + structlog contextvars; include other IDs as kwargs. **Event/description text is Chinese** (e.g. `logger.info("竞品调研开始", idea_id=...)`); kwarg keys remain English for tooling. Always log via the stdlib/structlog pipeline — `print` / `println` is banned for log output.
- Long-running agent work runs in background tasks with their own DB session — never reuse request sessions across the boundary.
- Agent steps and prompt logic live in `app/agent/`. Routes are HTTP-thin; the AIJuicer node is a thin SDK wrapper. Don't put PRD logic in routes or in the worker entrypoint.
