"""AIJuicer integration: publish 高分 idea / experience 到 AIJuicer。

idea / experience 入库且分数 ≥ ``AIJUICER_SCORE_THRESHOLD``（默认 7）时，
渲染成 markdown 直接作为 ``initial_artifacts`` 提交给 AIJuicer。AIJuicer
落盘并跳过 idea step，从 requirement 开始走流水线——AIIdea 不再需要在线
agent 消费 idea task（SDK ≥ 0.7 起支持）。

env:
- ``AIJUICER_ENABLED`` (默认 0)
- ``AIJUICER_SCORE_THRESHOLD`` (默认 7，0-10)
- ``AIJUICER_SERVER`` / ``AIJUICER_REDIS_URL``  SDK 自己读取
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import structlog

logger = structlog.get_logger()


def _enabled() -> bool:
    return os.environ.get("AIJUICER_ENABLED", "0") == "1"


def _threshold() -> float:
    return float(os.environ.get("AIJUICER_SCORE_THRESHOLD", "7"))


# ---------------- markdown rendering ----------------

def _section(lines: list[str], title: str, body: Any) -> None:
    if body:
        lines += ["", f"## {title}", str(body).strip()]


def _render_idea_markdown(idea: dict[str, Any]) -> str:
    lines = [f"# {idea.get('idea_title') or '(无标题)'}"]
    if idea.get("overall_score") is not None:
        lines += ["", f"综合评分：{idea['overall_score']}"]
    _section(lines, "产品 idea", idea.get("product_idea"))
    _section(lines, "用户故事", idea.get("user_story"))
    _section(lines, "目标用户", idea.get("target_audience"))
    _section(lines, "使用场景", idea.get("use_case"))
    _section(lines, "痛点", idea.get("pain_points"))
    _section(lines, "主要功能", idea.get("key_features"))
    _section(lines, "数据引用", idea.get("source_quote"))
    _section(lines, "依据", idea.get("reasoning"))
    return "\n".join(lines).strip() + "\n"


def _render_experience_markdown(report: dict[str, Any]) -> str:
    name = report.get("product_name") or "(未命名产品)"
    lines = [f"# {name} 产品体验报告"]
    if report.get("product_url"):
        lines += ["", f"产品官网：{report['product_url']}"]
    if report.get("overall_ux_score") is not None:
        lines += ["", f"综合体验分：{report['overall_ux_score']}"]
    _section(lines, "概览", report.get("summary_zh"))
    if feats := report.get("feature_inventory"):
        lines += ["", "## 功能盘点"]
        for f in feats:
            lines.append(f"- {f.get('name','')}: {f.get('where_found','')} | {f.get('notes','')}")
    _section(lines, "优点", report.get("strengths"))
    _section(lines, "缺点", report.get("weaknesses"))
    _section(lines, "商业模式", report.get("monetization_model"))
    _section(lines, "目标用户", report.get("target_user"))
    return "\n".join(lines).strip() + "\n"


# ---------------- publisher ----------------

async def _mark_workflow_id(source_type: str, source_id: str, workflow_id: str) -> None:
    """提交成功后回填 aijuicer_workflow_id —— 前端用来打"已入流"徽章。"""
    import uuid as _uuid

    from sqlalchemy import update as _update

    from src.db import get_async_session_factory  # noqa: PLC0415
    from src.models.analysis_result import AnalysisResult  # noqa: PLC0415
    from src.models.product_experience_report import (  # noqa: PLC0415
        ProductExperienceReport,
    )

    model = ProductExperienceReport if source_type == "experience" else AnalysisResult
    try:
        rid = _uuid.UUID(source_id)
    except (ValueError, TypeError, AttributeError):
        return

    factory = get_async_session_factory()
    async with factory() as session:
        await session.execute(
            _update(model)
            .where(model.id == rid)
            .values(aijuicer_workflow_id=workflow_id)
        )
        await session.commit()


async def _publish(name: str, payload: dict[str, Any], idea_markdown: str) -> None:
    """提交 workflow 并把 idea.md 作为 initial artifact 一并落盘——
    AIJuicer 跳过 idea step，从 requirement 起跑。成功后把 workflow_id
    回填到对应 idea / experience 行。"""
    from aijuicer_sdk.transport import SchedulerClient  # noqa: PLC0415

    server = os.environ.get("AIJUICER_SERVER", "http://127.0.0.1:8000")
    client = SchedulerClient(server)
    try:
        wf = await client.create_workflow(
            name=name[:140],
            input=payload,
            approval_policy={},
            initial_artifacts=[
                {
                    "step": "idea",
                    "key": "idea.md",
                    "content": idea_markdown,
                    "content_type": "text/markdown",
                }
            ],
        )
        wf_id = wf.get("id")
        logger.info(
            "AIJuicer 工作流已创建",
            workflow_id=wf_id,
            source_type=payload.get("source_type"),
            source_id=payload.get("source_id"),
        )
        if wf_id and payload.get("source_id"):
            try:
                await _mark_workflow_id(
                    payload.get("source_type") or "idea",
                    payload["source_id"],
                    wf_id,
                )
            except Exception as exc:
                logger.warning(
                    "AIJuicer 回填 workflow_id 失败",
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )
    except Exception as exc:
        logger.warning(
            "AIJuicer 提交失败",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
    finally:
        try:
            await client.close()
        except Exception:
            pass


def _spawn(coro) -> None:
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        asyncio.run(coro)


def maybe_publish_idea(idea: dict[str, Any]) -> None:
    if not _enabled():
        return
    score = idea.get("overall_score")
    if score is None or float(score) < _threshold():
        return
    _spawn(
        _publish(
            f"AI Idea · {idea.get('idea_title') or '(未命名)'}",
            {
                "source_type": "idea",
                "source_id": idea.get("source_id"),
                "project_name": idea.get("project_name"),
                "product_type": idea.get("product_type"),
                "origin": "ai-idea",
            },
            _render_idea_markdown(idea),
        )
    )


def maybe_publish_experience(report: dict[str, Any]) -> None:
    if not _enabled():
        return
    score = report.get("overall_ux_score")
    if score is None or float(score) < _threshold():
        return
    _spawn(
        _publish(
            f"产品体验 · {report.get('product_name') or '(未命名)'}",
            {
                "source_type": "experience",
                "source_id": report.get("source_id"),
                "project_name": report.get("project_name"),
                "product_url": report.get("product_url"),
                "origin": "ai-idea",
            },
            _render_experience_markdown(report),
        )
    )


async def _handle_idea_task(ctx) -> dict[str, Any]:
    """idea step handler——publisher 已经把 idea.md 作为 initial artifact
    塞进 workflow 了，AIJuicer 通常不会派任务过来；agent 主要为了在 UI
    在线名册里露面 + 兜底（万一 publisher 没带 initial_artifacts，仍能
    把 input.text 写成产物推进流水线）。"""
    text = (getattr(ctx, "input", None) or {}).get("text") or "# (空)"
    await ctx.save_artifact("idea.md", text, content_type="text/markdown")
    return {"length": len(text)}


def start_consumer_in_background() -> asyncio.Task | None:
    if not _enabled():
        logger.info("AIJuicer consumer 跳过", enabled=False)
        return None

    async def _run() -> None:
        from aijuicer_sdk import Agent  # noqa: PLC0415

        agent = Agent(
            name="ai-idea",
            step="idea",
            concurrency=1,
            configure_logging=False,
        )
        agent.handler(_handle_idea_task)
        try:
            await agent.arun()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "AIJuicer consumer 异常",
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )

    task = asyncio.create_task(_run(), name="aijuicer-idea-agent")
    logger.info("AIJuicer consumer 已启动", name="ai-idea")
    return task


__all__ = [
    "maybe_publish_idea",
    "maybe_publish_experience",
    "start_consumer_in_background",
]
