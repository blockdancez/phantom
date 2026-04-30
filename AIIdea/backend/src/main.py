import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Hydrate os.environ from .env *before* anything else looks at the
# environment. pydantic-settings would read .env into the Settings model,
# but it does NOT export those values back into os.environ — so any module
# that calls os.environ.get(...) directly (the AIJuicer integration, the
# OpenAI key bridge below) would otherwise see only what the parent shell
# exported. Loading here once unifies both paths.
try:
    from dotenv import load_dotenv  # python-dotenv ships with pydantic-settings
    _repo_env = Path(__file__).resolve().parent.parent.parent / ".env"
    _backend_env = Path(__file__).resolve().parent.parent / ".env"
    if _backend_env.is_file():
        load_dotenv(_backend_env, override=False)
    if _repo_env.is_file():
        load_dotenv(_repo_env, override=False)
except ImportError:
    pass

from src.envelope import EnvelopeMiddleware, register_exception_handlers
from src.logging_setup import setup_logging
from src.middleware import RequestIdMiddleware
from src.api.router import api_router


@lru_cache
def _get_settings():
    from src.config import Settings
    return Settings()


_settings = _get_settings()
setup_logging(_settings.log_level)

# Sync LLM provider keys from Settings into os.environ at startup.
# langchain-openai / langchain-anthropic clients only look up keys from the
# process environment, not from our pydantic Settings object, so we bridge the
# two here. This means .env (loaded by Settings) becomes the single source of
# truth for provider keys — no call site needs to pass api_key= explicitly.
if _settings.openai_api_key:
    os.environ.setdefault("OPENAI_API_KEY", _settings.openai_api_key)
if _settings.anthropic_api_key:
    os.environ.setdefault("ANTHROPIC_API_KEY", _settings.anthropic_api_key)

# Feature-3 / feature-4 require LLM calls. Per the plan, a missing
# OPENAI_API_KEY must fail loudly at boot rather than silently degrade when
# the first ``process`` / ``analyze`` trigger fires in production.
# Set AI_IDEA_FINDER_SKIP_KEY_CHECK=1 to bypass (useful for tests / lint runs).
if not os.environ.get("AI_IDEA_FINDER_SKIP_KEY_CHECK"):
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. The processing + analysis pipelines "
            "require a valid OpenAI key. Set it in .env or the shell, or set "
            "AI_IDEA_FINDER_SKIP_KEY_CHECK=1 to bypass."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.scheduler.jobs import create_scheduler
    scheduler = create_scheduler()
    try:
        scheduler.start()
    except Exception:
        # Per feature-2 spec: scheduler startup failure must not silently
        # degrade — surface it to the operator instead of booting without
        # any pipeline.
        raise
    app.state.scheduler = scheduler

    aijuicer_task = None
    try:
        from src.integrations.aijuicer import start_consumer_in_background
        aijuicer_task = start_consumer_in_background()
    except Exception:
        import structlog
        structlog.get_logger().exception("AIJuicer consumer 启动失败")

    try:
        yield
    finally:
        if aijuicer_task is not None and not aijuicer_task.done():
            aijuicer_task.cancel()
            import asyncio as _asyncio
            try:
                await _asyncio.wait_for(aijuicer_task, timeout=2.0)
            except (_asyncio.TimeoutError, _asyncio.CancelledError, Exception):
                pass
        scheduler.shutdown(wait=False)
        app.state.scheduler = None


app = FastAPI(title="AI Idea", lifespan=lifespan)

# CORS: accept any origin on loopback (the regex matches localhost /
# 127.0.0.1 with an optional port). This avoids hard-coding port numbers,
# so whatever port FRONTEND_PORT the operator chose will be permitted.
_extra_origins = os.environ.get("CORS_EXTRA_ORIGINS")
_allow_origins = (
    [o.strip() for o in _extra_origins.split(",") if o.strip()]
    if _extra_origins
    else []
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Envelope runs *before* RequestId in dispatch order — but since middleware
# is applied in reverse add order, we add EnvelopeMiddleware first (innermost)
# and RequestIdMiddleware last (outermost) so the request_id is set before
# the envelope middleware reads it.
app.add_middleware(EnvelopeMiddleware)
app.add_middleware(RequestIdMiddleware)

register_exception_handlers(app)

# Static mount for product-experience screenshots. Files land here from the
# product_experience agent's take_screenshot tool; the frontend product
# detail page renders <img src="/static/screenshots/<rel>"> against this.
_screenshot_dir = (
    Path(__file__).resolve().parent.parent / "data" / "product_screenshots"
)
_screenshot_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/screenshots",
    StaticFiles(directory=str(_screenshot_dir)),
    name="product-screenshots",
)

# Static mount for codex-runner experience artifacts. The codex agent writes
# REPORT.md + screenshots/*.png into <data/codex_experience>/<report_id>/...;
# the frontend ScreenshotGallery references them via /static/codex/<path>.
_codex_dir = (
    Path(__file__).resolve().parent.parent / "data" / "codex_experience"
)
_codex_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/static/codex",
    StaticFiles(directory=str(_codex_dir)),
    name="codex-experience",
)

app.include_router(api_router)
