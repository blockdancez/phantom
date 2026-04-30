"""AIJuicer requirement node.

Registers this service as the `requirement` step of the 6-step pipeline
(idea → requirement → plan → design → devtest → deploy).

Run: `python -m app.aijuicer_node` (from `backend/`).
"""
from __future__ import annotations

# Logging must be configured BEFORE the SDK is imported: the SDK's loggers
# bind at import time and would otherwise freeze structlog's true defaults
# (column-aligned ConsoleRenderer) instead of our spec'd format.
from app.config import get_settings
from app.logging_setup import setup_logging

setup_logging(get_settings().log_level)

import os
import uuid as uuid_mod
from datetime import datetime, timezone
from pathlib import Path

import structlog
from aijuicer_sdk import Agent, AgentContext, FatalError, RetryableError
from openai import AsyncOpenAI
from sqlalchemy import delete, select

from app.agent.researcher import Researcher
from app.agent.writer import PrdWriter
from app.database import create_engine, create_session_factory
from app.models import Document, Idea

logger = structlog.get_logger()

# Worker is a separate process from FastAPI — never runs lifespan, so we can't
# rely on app.database.SessionLocal. Build our own factory once.
_session_maker = None


def _get_session_maker():
    global _session_maker
    if _session_maker is None:
        _session_maker = create_session_factory(create_engine())
    return _session_maker


async def _load_idea(ctx: AgentContext) -> str:
    """Idea text comes from the upstream `idea` step's artifact."""
    try:
        raw = await ctx.load_artifact("idea", "idea.md")
    except FileNotFoundError as e:
        raise FatalError("upstream idea/idea.md is missing") from e
    text = raw.decode("utf-8").strip()
    if not text:
        raise FatalError("upstream idea/idea.md is empty")
    return text


def _extract_feedback(ctx: AgentContext) -> str | None:
    """AIJuicer webui's RerunDialog writes here: input.user_feedback[step]."""
    fb_map = (ctx.input or {}).get("user_feedback") or {}
    if not isinstance(fb_map, dict):
        return None
    fb = fb_map.get(ctx.step)
    return fb.strip() if isinstance(fb, str) and fb.strip() else None


def _project_dir(ctx: AgentContext) -> Path | None:
    """Resolve <PROJECT_ROOT>/<project_name>; reject empty / suspicious names."""
    name = (ctx.project_name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        logger.warning(
            "project_name 非法，跳过项目目录写入",
            project_name=ctx.project_name,
            workflow_id=ctx.workflow_id,
        )
        return None
    return Path(get_settings().project_root) / name


def _mirror_idea_to_project(ctx: AgentContext, idea_text: str) -> None:
    """Drop the upstream idea.md into the per-project working directory so
    downstream tooling (and humans) can find it on disk. Best-effort: any
    error is logged but never aborts the task."""
    project_dir = _project_dir(ctx)
    if project_dir is None:
        return
    try:
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "idea.md").write_text(idea_text, encoding="utf-8")
        logger.info("已写入项目目录 idea.md", path=str(project_dir / "idea.md"))
    except OSError as e:
        logger.error(
            "项目目录写入失败",
            path=str(project_dir),
            error=str(e),
            exc_info=True,
        )


async def _persist_to_db(
    *,
    workflow_id: str,
    idea_text: str,
    title: str,
    content: str,
    research: dict,
) -> None:
    """Mirror the AIJuicer-generated PRD into local Postgres so the History
    page surfaces it. Schema enforces one Document per Idea, so on rerun we
    replace. Failures are swallowed: the artifact already lives in the
    scheduler and raising would cause an SDK retry that re-bills the LLM call.
    """
    try:
        idea_uuid = uuid_mod.UUID(workflow_id)
    except (ValueError, TypeError):
        logger.warning("workflow_id 非合法 UUID，跳过本地库写入", workflow_id=workflow_id)
        return

    try:
        async with _get_session_maker()() as session:
            existing = (
                await session.execute(select(Idea).where(Idea.id == idea_uuid))
            ).scalar_one_or_none()
            if existing is None:
                session.add(Idea(id=idea_uuid, content=idea_text, status="completed"))
            else:
                existing.content = idea_text
                existing.status = "completed"
                existing.updated_at = datetime.now(timezone.utc)
                await session.execute(
                    delete(Document).where(Document.idea_id == idea_uuid)
                )
            session.add(
                Document(
                    idea_id=idea_uuid,
                    title=title,
                    content=content,
                    research=research,
                )
            )
            await session.commit()
            logger.info("AIJuicer 任务结果已写入本地库", workflow_id=workflow_id, title=title)
    except Exception as e:
        logger.error(
            "写入本地库失败", workflow_id=workflow_id, error=str(e), exc_info=True,
        )


agent = Agent(
    name=os.getenv("AIJUICER_AGENT_NAME", "ai-requirement"),
    step="requirement",
    server=os.getenv("AIJUICER_SERVER"),
    redis_url=os.getenv("AIJUICER_REDIS_URL"),
    concurrency=int(os.getenv("AIJUICER_CONCURRENCY", "1")),
    # We install our own structlog config in main(); don't let the SDK
    # overwrite it with its JSON renderer.
    configure_logging=False,
)


@agent.handler
async def handle(ctx: AgentContext) -> dict:
    feedback = _extract_feedback(ctx)
    is_rerun = ctx.attempt > 1 or feedback is not None

    idea = await _load_idea(ctx)
    _mirror_idea_to_project(ctx, idea)

    # On rerun with feedback, pull the previous PRD so the writer can patch
    # it minimally instead of regenerating from scratch (which makes two
    # consecutive PRDs look completely unrelated).
    previous_prd: str | None = None
    if is_rerun and feedback:
        try:
            prev_bytes = await ctx.load_artifact("requirement", "requirements.md")
            previous_prd = prev_bytes.decode("utf-8")
        except FileNotFoundError:
            pass  # first attempt with no prior artifact — fall back to fresh generate

    logger.info(
        "需求节点开始处理",
        is_rerun=is_rerun,
        has_feedback=feedback is not None,
        edit_mode=previous_prd is not None,
    )

    settings = get_settings()
    writer = PrdWriter(
        openai_client=AsyncOpenAI(api_key=settings.openai_api_key),
        model=settings.openai_model,
    )

    # Skip Tavily on edit mode — research is part of the previous PRD already,
    # and re-querying drifts the competitive framing across reruns.
    if previous_prd is None:
        await ctx.heartbeat("researching")
        researcher = Researcher(tavily_api_key=settings.tavily_api_key)
        research = await researcher.research(idea)
    else:
        research = {"keywords": [], "competitors": []}

    await ctx.heartbeat("writing")
    try:
        prd = await writer.generate(
            idea=idea,
            research=research,
            rerun_instruction=feedback,
            previous_prd=previous_prd,
        )
    except Exception as e:
        raise RetryableError(f"prd generation failed: {e}") from e

    ref = await ctx.save_artifact(
        "requirements.md", prd["content"], content_type="text/markdown",
    )

    await _persist_to_db(
        workflow_id=ctx.workflow_id,
        idea_text=idea,
        title=prd["title"],
        content=prd["content"],
        research=research,
    )

    logger.info(
        "需求节点处理完成",
        title=prd["title"],
        size_bytes=ref.size_bytes,
        is_rerun=is_rerun,
    )
    return {"title": prd["title"], "is_rerun": is_rerun}


def main() -> None:
    logger.info("AIJuicer 节点启动", step="requirement", name=agent.name)
    agent.run()


if __name__ == "__main__":
    main()
