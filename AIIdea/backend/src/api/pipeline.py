"""Pipeline trigger + status endpoints (feature-1 / feature-2 / feature-3 / feature-4).

Also exposes ``POST /api/pipeline/experience-url`` for the "user types in a
product URL and gets a fresh codex experience" flow (no candidate-pool
detour). Returns a ``report_id`` immediately and runs the long codex
session as an asyncio background task — the row starts with
``status='running'`` and gets updated in-place when codex finishes.


``POST /api/pipeline/trigger/{job_id}`` handles four flavors of job:

- **Registered cron jobs** (``collect_data``, ``process_data``, ``analyze_data``)
  are nudged forward via ``APScheduler.modify(next_run_time=now)``; the endpoint
  returns immediately with ``started_at`` / ``next_run_time``. A module-level
  lock tracks which scheduled jobs are currently executing so a second trigger
  returns ``PIPELINE002`` instead of racing.

- **Per-source collect jobs** (``collect_hackernews``, ``collect_reddit``,
  ``collect_producthunt``, ``collect_github_trending``, ``collect_twitter``,
  ``collect_rss``) run the specific collector inline with exponential backoff
  on rate-limit / transient failures (per feature-1 spec) and return the
  inserted row count. A separate lock prevents duplicate concurrent runs
  of the same per-source job.

- **Inline processing** (``process``) — runs the Enrich → Analyze → Persist
  pipeline synchronously and returns ``{processed: N}`` (feature-3).

- **Inline analysis** (``analyze``) — runs the LangGraph agent synchronously
  with a 180-second timeout. Returns ``{generated: 0|1}``. On timeout or
  mid-run failure the call still writes a partial ``AnalysisResult`` with
  ``overall_score=0`` and a trace marker so the operator can see the agent
  got stuck (feature-4).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.collectors.base import BaseCollector
from src.collectors.github_trending import GitHubTrendingCollector
from src.collectors.hackernews import HackerNewsCollector
from src.collectors.ingester import ingest_items
from src.collectors.producthunt import ProductHuntCollector
from src.collectors.reddit import RedditCollector
from src.collectors.rss_collector import RSSCollector
from src.collectors.twitter_trends import TwitterTrendsCollector
from src.db import get_async_session_factory
from src.exceptions import APIError, ErrorCode

router = APIRouter()
logger = structlog.get_logger()


# Registered APScheduler job IDs — may be triggered via this endpoint but run
# under the scheduler's normal interval schedule afterwards.
_SCHEDULED_JOB_IDS: frozenset[str] = frozenset(
    {
        "collect_data",
        "process_data",
        "analyze_data",
        "experience_products",
        "discover_products",
    }
)

# Per-source collector factories. Keys are the public job IDs; values build a
# fresh collector on each invocation so concurrent runs don't share state.
_PER_SOURCE_COLLECTORS: dict[str, type[BaseCollector]] = {
    "collect_hackernews": HackerNewsCollector,
    "collect_reddit": RedditCollector,
    "collect_producthunt": ProductHuntCollector,
    "collect_github_trending": GitHubTrendingCollector,
    "collect_twitter": TwitterTrendsCollector,
}

# Human-readable canonical error messages, byte-identical to the plan's
# contract — the reviewer flagged the previous free-form phrasings as an
# unstable client contract.
_MSG_UNKNOWN_JOB = "unknown job_id"
_MSG_JOB_ALREADY_RUNNING = "job already running"
_MSG_SCHEDULER_DOWN = "scheduler is not running"


def _rss_collector_factory() -> BaseCollector:
    # RSS source comes from sources_registry so the collector is assembled at
    # runtime rather than at import.
    from src.collectors.sources_registry import SOURCES

    feeds: dict[str, str] = {}
    for s in SOURCES:
        if not s.enabled or s.kind != "rss":
            continue
        key = s.name[4:] if s.name.startswith("rss:") else s.name
        feeds[key] = s.url
    return RSSCollector(feeds=feeds)


_RSS_JOB_ID = "collect_rss"

# Inline processing + analysis job IDs — run synchronously inside the HTTP
# handler (feature-3 / feature-4). Distinct from the scheduled
# ``process_data`` / ``analyze_data`` entries which only nudge APScheduler.
_INLINE_PROCESS_JOB_ID = "process"
_INLINE_ANALYZE_JOB_ID = "analyze"

# Running-lock aliases: a request to ``/trigger/process`` and a background
# ``process_data`` cron tick are two names for the same work. We store one
# running entry per logical job in ``_running_scheduled`` and resolve either
# spelling to that single key so concurrent triggers — inline vs scheduled,
# either direction — both trip the PIPELINE002 guard.
_RUNNING_KEY_ALIASES: dict[str, str] = {
    "process": "process_data",
    "analyze": "analyze_data",
}


def _running_key(job_id: str) -> str:
    return _RUNNING_KEY_ALIASES.get(job_id, job_id)

# Max seconds a single /trigger/analyze call is allowed to run before we
# abandon the LangGraph agent and write a timeout trace. Per feature-4:
# "单次分析超时（> 180s）→ 中断并置 agent_trace 的最后一步为 `timeout`".
_ANALYZE_TIMEOUT_SECONDS = 180


def list_triggerable_ids() -> list[str]:
    return sorted(
        set(_SCHEDULED_JOB_IDS)
        | set(_PER_SOURCE_COLLECTORS.keys())
        | {_RSS_JOB_ID, _INLINE_PROCESS_JOB_ID, _INLINE_ANALYZE_JOB_ID}
    )


# Locks: one for per-source collectors (which run inline in the handler),
# one for scheduled jobs (tracked across async triggers + the scheduled
# callback via scheduler/jobs.py). Both are small sets of strings.
_running_per_source: set[str] = set()
_per_source_lock = asyncio.Lock()

# Tracked by scheduler/jobs.py record_start / record_finish too — see
# src.scheduler.runs. We separately track "running" at the trigger layer so
# back-to-back API triggers can short-circuit before touching the scheduler.
_running_scheduled: set[str] = set()
_scheduled_lock = asyncio.Lock()


def mark_scheduled_running(job_id: str) -> bool:
    """Try to mark a scheduled job as running. Returns False if already running.

    Accepts either the inline ID (``process`` / ``analyze``) or the scheduled
    ID (``process_data`` / ``analyze_data``) — both collapse to the same
    underlying key so cross-path triggers see one another.
    """
    key = _running_key(job_id)
    if key in _running_scheduled:
        return False
    _running_scheduled.add(key)
    return True


def clear_scheduled_running(job_id: str) -> None:
    _running_scheduled.discard(_running_key(job_id))


def is_scheduled_running(job_id: str) -> bool:
    return _running_key(job_id) in _running_scheduled


# Exponential backoff parameters for per-source collectors. Feature-1 calls
# for rate-limit retries on HN / Reddit / PH; we apply the same policy to all
# per-source collectors to keep the surface small.
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 1.0


def _is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 425, 429, 500, 502, 503, 504)
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    return False


async def _collect_with_backoff(
    collector: BaseCollector,
    job_id: str,
    label: str,
    *,
    max_attempts: int = _MAX_ATTEMPTS,
    base_backoff_seconds: float = _BASE_BACKOFF_SECONDS,
    sleep=asyncio.sleep,
) -> list[dict]:
    """Run ``collector.collect(limit=30)`` with exponential backoff on 429 /
    transient network errors. Non-retriable failures bubble out unchanged."""

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await collector.collect(limit=30)
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_rate_limited(exc):
                raise
            delay = base_backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "per_source_collect_backoff",
                job_id=job_id,
                source=label,
                attempt=attempt,
                delay_seconds=delay,
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            await sleep(delay)
    # Defensive: loop invariant guarantees we either returned or raised above.
    assert last_exc is not None
    raise last_exc


class TriggerResponse(BaseModel):
    status: str
    job_id: str
    started_at: datetime
    next_run_time: datetime | None = None
    inserted: int | None = None
    source: str | None = None
    processed: int | None = None
    generated: int | None = None
    duration_ms: int | None = None
    detail: str | None = None


async def _run_inline_process(batch_size: int = 50) -> int:
    """Execute one processing batch inline and return the number of
    SourceItem rows that got ``processed=True``. Thin wrapper around
    ``processors.pipeline.run_processing_pipeline`` — kept here so the
    trigger endpoint stays in the API layer while the service layer owns
    the business logic, and so tests can monkeypatch the module-level
    factory / pipeline symbols deterministically.
    """
    # Deferred import so src.api.pipeline keeps a small surface and test
    # fixtures can monkeypatch src.processors.pipeline without touching
    # this module.
    from src.processors.pipeline import run_processing_pipeline

    factory = get_async_session_factory()
    async with factory() as session:
        processed = await run_processing_pipeline(session, batch_size=batch_size)
    return processed


async def _run_inline_analyze_once() -> tuple[int, str]:
    """Execute one analysis run inline.

    Returns (generated_count, status_detail). ``generated_count`` is 0 or 1
    depending on whether the agent produced a usable AnalysisResult; the
    ``status_detail`` string describes what happened (``"written"``,
    ``"skipped_no_lineage"``, ``"skipped_bail"``, ``"skipped_empty"``).

    On mid-run exception or timeout we still persist a partial
    AnalysisResult with ``overall_score=0`` and an ``agent_trace`` that
    marks the failed / timed-out step, per feature-4's error matrix.
    """
    from src.models.analysis_result import AnalysisResult

    factory = get_async_session_factory()
    async with factory() as session:
        try:
            raw_report, trace, message_count = await _run_agent_with_timeout(session)
        except asyncio.TimeoutError:
            logger.error(
                "内联分析超时",
                timeout_seconds=_ANALYZE_TIMEOUT_SECONDS,
            )
            record = AnalysisResult(
                idea_title="(分析超时)",
                overall_score=0.0,
                product_idea=None,
                target_audience=None,
                use_case=None,
                pain_points=None,
                key_features=None,
                source_quote=None,
                user_story=None,
                source_item_id=None,
                reasoning=None,
                source_item_ids=[],
                agent_trace={
                    "trace": [{"role": "system", "content": "timeout"}],
                    "last_step": "timeout",
                    "timeout_seconds": _ANALYZE_TIMEOUT_SECONDS,
                },
            )
            session.add(record)
            await session.commit()
            return 0, "timeout"
        except Exception as exc:
            logger.exception("内联分析失败")
            record = AnalysisResult(
                idea_title="(分析失败)",
                overall_score=0.0,
                product_idea=None,
                target_audience=None,
                use_case=None,
                pain_points=None,
                key_features=None,
                source_quote=None,
                user_story=None,
                source_item_id=None,
                reasoning=None,
                source_item_ids=[],
                agent_trace={
                    "trace": [
                        {
                            "role": "system",
                            "content": f"failed: {type(exc).__name__}: {exc}",
                        }
                    ],
                    "last_step": "failed",
                    "error_type": type(exc).__name__,
                },
            )
            session.add(record)
            await session.commit()
            return 0, "failed"

        # Guard 1: empty / trivially-short final message.
        if len(raw_report.strip()) < 80:
            logger.info(
                "内联分析跳过",
                reason="empty_report",
                length=len(raw_report),
            )
            return 0, "skipped_empty"

        # Guard 2: agent bail markers.
        bail_markers = (
            "NO_VIABLE_IDEA_FOUND",
            "NO_CONSUMER_ANCHOR_FOUND",
            "调整搜索策略",
            "建议调整搜索",
        )
        if any(marker in raw_report for marker in bail_markers):
            logger.info(
                "内联分析跳过",
                reason="agent_bailed",
                head=raw_report[:120],
            )
            return 0, "skipped_bail"

        # Guard 3: structured extraction + required-field check.
        from src.agent.extractor import extract_agent_report

        try:
            report = await extract_agent_report(raw_report)
        except Exception:
            logger.exception("内联分析抽取失败")
            return 0, "skipped_extraction_failed"

        if not report.source_quote and not report.user_story:
            logger.info(
                "内联分析跳过",
                reason="no_lineage",
                title=report.idea_title[:80],
            )
            return 0, "skipped_no_lineage"

        # Project-positioning guard: see scheduler.jobs._run_analysis_impl
        # for the rationale. AI Idea analyzes internet/AI/SaaS
        # product ideas only; physical goods, offline services, and pure
        # life-hack tips get dropped.
        if not report.is_digital_product:
            logger.info(
                "内联分析跳过",
                reason="non_digital_product",
                title=(report.idea_title or "")[:80],
                form=report.digital_product_form,
            )
            return 0, "skipped_non_digital_product"

        # Per feature-4: missing idea_title or overall_score → don't insert.
        if not report.idea_title or report.overall_score is None:
            logger.error(
                "内联分析缺必填字段",
                idea_title_present=bool(report.idea_title),
            )
            return 0, "skipped_missing_fields"

        from src.scheduler.jobs import _parse_source_item_uuid  # noqa: PLC0415

        overall_score = float(report.overall_score)

        # Defensive de-dup + signal_type cap (mirrors scheduler.jobs).
        anchor_uuid = _parse_source_item_uuid(report.source_item_id)
        if anchor_uuid is not None:
            from sqlalchemy import select as _select
            from src.models.source_item import SourceItem as _SourceItem

            existing = (
                await session.execute(
                    _select(AnalysisResult.id)
                    .where(AnalysisResult.source_item_id == anchor_uuid)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                logger.info(
                    "内联分析跳过",
                    reason="duplicate_anchor",
                    source_item_id=str(anchor_uuid),
                )
                return 0, "skipped_duplicate_anchor"

            anchor_signal = (
                await session.execute(
                    _select(_SourceItem.signal_type).where(
                        _SourceItem.id == anchor_uuid
                    )
                )
            ).scalar_one_or_none()
            if anchor_signal in ("launch", "story", "news"):
                capped = min(overall_score, 5.0)
                if capped < overall_score:
                    logger.info(
                        "内联分析评分被压制",
                        reason=f"anchor_signal_{anchor_signal}",
                        original=overall_score,
                        capped=capped,
                    )
                    overall_score = capped

        from src.scheduler.jobs import _resolve_unique_project_name  # noqa: PLC0415
        project_name = await _resolve_unique_project_name(
            session, getattr(report, "project_name", None)
        )

        record = AnalysisResult(
            idea_title=report.idea_title,
            overall_score=overall_score,
            project_name=project_name,
            product_type=report.digital_product_form,
            product_idea=report.product_idea,
            target_audience=report.target_audience,
            use_case=report.use_case,
            pain_points=report.pain_points,
            key_features=report.key_features,
            source_quote=report.source_quote,
            user_story=report.user_story,
            source_item_id=_parse_source_item_uuid(report.source_item_id),
            reasoning=report.reasoning,
            source_item_ids=[],
            agent_trace={
                "raw_report": raw_report,
                "trace": trace,
                "message_count": message_count,
            },
        )
        session.add(record)
        await session.commit()
        idea_snapshot = {
            "project_name": record.project_name,
            "product_type": record.product_type,
            "idea_title": record.idea_title,
            "overall_score": record.overall_score,
            "product_idea": record.product_idea,
            "user_story": record.user_story,
            "target_audience": record.target_audience,
            "use_case": record.use_case,
            "pain_points": record.pain_points,
            "key_features": record.key_features,
            "source_quote": record.source_quote,
            "reasoning": record.reasoning,
            "source_id": str(record.id),
        }
        logger.info(
            "内联分析已入库",
            score=overall_score,
            title=report.idea_title[:60],
        )
        try:
            from src.integrations.aijuicer import maybe_publish_idea
            maybe_publish_idea(idea_snapshot)
        except Exception:
            logger.exception("AIJuicer idea 提交异常")
        return 1, "written"


async def _run_agent_with_timeout(session) -> tuple[str, list, int]:
    """Run the LangGraph agent under an ``asyncio.wait_for`` umbrella so the
    caller can distinguish timeout from generic failure."""
    from src.agent.graph import run_analysis_agent  # local import keeps
    # test-time monkeypatching simple (patch src.agent.graph.run_analysis_agent).

    result = await asyncio.wait_for(
        run_analysis_agent(session),
        timeout=_ANALYZE_TIMEOUT_SECONDS,
    )
    raw_report = result.get("analysis", "") or ""
    trace = result.get("trace", []) or []
    message_count = int(result.get("message_count", 0) or 0)
    return raw_report, trace, message_count


async def _run_per_source_collector(job_id: str) -> tuple[int, str]:
    if job_id == _RSS_JOB_ID:
        collector = _rss_collector_factory()
        label = "rss"
    else:
        factory = _PER_SOURCE_COLLECTORS[job_id]
        collector = factory()
        label = job_id[len("collect_") :]

    try:
        raw_items = await _collect_with_backoff(collector, job_id, label)
    except Exception as exc:
        logger.error(
            "per_source_collect_failed",
            job_id=job_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise APIError(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=f"collector '{label}' failed",
            http_status=503,
        ) from exc
    finally:
        await collector.close()

    factory = get_async_session_factory()
    async with factory() as session:
        inserted = await ingest_items(session, raw_items)
    logger.info(
        "per_source_collect_done",
        job_id=job_id,
        source=label,
        fetched=len(raw_items),
        inserted=inserted,
    )
    return inserted, label


@router.post("/pipeline/trigger/{job_id}", response_model=TriggerResponse)
async def trigger_job(job_id: str, request: Request) -> TriggerResponse:
    logger.info("管线手动触发", job_id=job_id)

    now = datetime.now(timezone.utc)

    if job_id in _SCHEDULED_JOB_IDS:
        scheduler = getattr(request.app.state, "scheduler", None)
        if scheduler is None or not scheduler.running:
            raise APIError(
                code=ErrorCode.SCHEDULER_DOWN,
                message=_MSG_SCHEDULER_DOWN,
                http_status=503,
            )
        job = scheduler.get_job(job_id)
        if job is None:
            raise APIError(
                code=ErrorCode.UNKNOWN_JOB,
                message=_MSG_UNKNOWN_JOB,
                http_status=404,
            )
        async with _scheduled_lock:
            if is_scheduled_running(job_id):
                raise APIError(
                    code=ErrorCode.JOB_ALREADY_RUNNING,
                    message=_MSG_JOB_ALREADY_RUNNING,
                    http_status=400,
                )
            try:
                job.modify(next_run_time=now)
            except Exception as exc:
                raise APIError(
                    code=ErrorCode.JOB_ALREADY_RUNNING,
                    message=_MSG_JOB_ALREADY_RUNNING,
                    http_status=400,
                ) from exc
        refreshed = scheduler.get_job(job_id)
        logger.info(
            "pipeline_trigger_scheduled",
            job_id=job_id,
            next_run_time=(
                refreshed.next_run_time.isoformat()
                if refreshed and refreshed.next_run_time
                else None
            ),
        )
        return TriggerResponse(
            status="triggered",
            job_id=job_id,
            started_at=now,
            next_run_time=(refreshed.next_run_time if refreshed else now),
        )

    if job_id == _RSS_JOB_ID or job_id in _PER_SOURCE_COLLECTORS:
        async with _per_source_lock:
            if job_id in _running_per_source:
                raise APIError(
                    code=ErrorCode.JOB_ALREADY_RUNNING,
                    message=_MSG_JOB_ALREADY_RUNNING,
                    http_status=400,
                )
            _running_per_source.add(job_id)
        try:
            inserted, source_label = await _run_per_source_collector(job_id)
        finally:
            async with _per_source_lock:
                _running_per_source.discard(job_id)
        return TriggerResponse(
            status="completed",
            job_id=job_id,
            started_at=now,
            inserted=inserted,
            source=source_label,
        )

    if job_id == _INLINE_PROCESS_JOB_ID:
        async with _scheduled_lock:
            if is_scheduled_running(job_id):
                raise APIError(
                    code=ErrorCode.JOB_ALREADY_RUNNING,
                    message=_MSG_JOB_ALREADY_RUNNING,
                    http_status=400,
                )
            mark_scheduled_running(job_id)
        started = datetime.now(timezone.utc)
        try:
            processed_count = await _run_inline_process()
        except Exception as exc:
            logger.exception("内联处理失败")
            raise APIError(
                code=ErrorCode.SERVICE_UNAVAILABLE,
                message="processing pipeline failed",
                http_status=503,
            ) from exc
        finally:
            async with _scheduled_lock:
                clear_scheduled_running(job_id)
        duration_ms = int(
            (datetime.now(timezone.utc) - started).total_seconds() * 1000
        )
        logger.info(
            "内联处理结束",
            job_id=job_id,
            processed=processed_count,
            duration_ms=duration_ms,
        )
        return TriggerResponse(
            status="completed",
            job_id=job_id,
            started_at=started,
            processed=processed_count,
            duration_ms=duration_ms,
        )

    if job_id == _INLINE_ANALYZE_JOB_ID:
        async with _scheduled_lock:
            if is_scheduled_running(job_id):
                raise APIError(
                    code=ErrorCode.JOB_ALREADY_RUNNING,
                    message=_MSG_JOB_ALREADY_RUNNING,
                    http_status=400,
                )
            mark_scheduled_running(job_id)
        started = datetime.now(timezone.utc)
        try:
            generated, detail = await _run_inline_analyze_once()
        finally:
            async with _scheduled_lock:
                clear_scheduled_running(job_id)
        duration_ms = int(
            (datetime.now(timezone.utc) - started).total_seconds() * 1000
        )
        logger.info(
            "内联分析结束",
            job_id=job_id,
            generated=generated,
            detail=detail,
            duration_ms=duration_ms,
        )
        return TriggerResponse(
            status="completed",
            job_id=job_id,
            started_at=started,
            generated=generated,
            duration_ms=duration_ms,
            detail=detail,
        )

    raise APIError(
        code=ErrorCode.UNKNOWN_JOB,
        message=_MSG_UNKNOWN_JOB,
        http_status=404,
    )


# ---------------- Manual "experience this URL" entry point ----------------

import re
from urllib.parse import urlparse


class ExperienceUrlPayload(BaseModel):
    """Body for POST /api/pipeline/experience-url."""

    url: str
    name: str | None = None
    requires_login: bool = False


class ExperienceUrlResponse(BaseModel):
    report_id: str
    status: str  # always "running" — completion happens async in background


def _normalize_manual_slug(host: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-") or "manual"
    return f"manual-{base}"


async def _run_codex_for_manual(
    *,
    report_id: str,
    url: str,
    name: str,
    slug: str,
    requires_login: bool,
) -> None:
    """Background worker: spawn codex, parse, then UPDATE the existing row
    (already inserted with status='running' before the API returned)."""
    from pathlib import Path

    from src.config import Settings
    from src.models.product_experience_report import ProductExperienceReport
    from src.product_experience import codex_runner as codex_runner_mod
    from src.product_experience.extractor import parse_agent_report

    settings = Settings()  # type: ignore[call-arg]
    parsed = None
    run_result = None
    final_status = "completed"
    failure_reason: str | None = None

    try:
        run_result = await codex_runner_mod.run_codex_experience(
            slug=slug,
            name=name,
            url=url,
            requires_login=requires_login,
            report_id=report_id,
            base_dir=Path(settings.codex_experience_root),
            codex_binary=settings.codex_binary_path,
            timeout_seconds=600,
        )
        if run_result.markdown:
            parsed = parse_agent_report(run_result.markdown)
        else:
            final_status = "failed"
            failure_reason = run_result.trace.get("reason", "no_report")
    except Exception as exc:
        final_status = "failed"
        failure_reason = f"{type(exc).__name__}: {exc}"
        logger.exception("手动体验失败", url=url[:120])

    completed = datetime.now(timezone.utc)
    factory = get_async_session_factory()
    import uuid as _uuid
    async with factory() as session:
        row = await session.get(ProductExperienceReport, _uuid.UUID(report_id))
        if row is None:
            logger.error("手动体验记录缺失", report_id=report_id)
            return
        row.run_completed_at = completed
        row.status = final_status
        row.failure_reason = failure_reason
        row.login_used = run_result.login_status if run_result else "skipped"
        if parsed:
            from src.product_experience.extractor import apply_parsed_to_orm  # noqa: PLC0415
            apply_parsed_to_orm(row, parsed)
        if run_result:
            row.screenshots = run_result.screenshots
            row.agent_trace = run_result.trace
        await session.commit()
        experience_snapshot = {
            "project_name": row.project_name,
            "product_name": row.product_name,
            "product_url": row.product_url,
            "overall_ux_score": row.overall_ux_score,
            "summary_zh": row.summary_zh,
            "feature_inventory": row.feature_inventory,
            "strengths": row.strengths,
            "weaknesses": row.weaknesses,
            "monetization_model": row.monetization_model,
            "target_user": row.target_user,
            "source_id": str(row.id),
        }
    logger.info(
        "手动体验结束",
        report_id=report_id,
        status=final_status,
        score=parsed.overall_ux_score if parsed else None,
    )
    try:
        from src.integrations.aijuicer import maybe_publish_experience
        maybe_publish_experience(experience_snapshot)
    except Exception:
        logger.exception("AIJuicer 体验提交异常")


@router.post("/pipeline/experience-url", response_model=ExperienceUrlResponse)
async def trigger_experience_url(
    payload: ExperienceUrlPayload, request: Request
) -> ExperienceUrlResponse:
    """Kick off a codex experience for an arbitrary user-supplied URL.

    Returns ``report_id`` immediately. The codex run happens in the
    background; the frontend should redirect the user to
    ``/products/<report_id>`` and let them refresh while status moves from
    ``running`` to ``completed``/``failed``.
    """
    from uuid import UUID, uuid4

    from src.models.product_experience_report import ProductExperienceReport

    parsed_url = urlparse(payload.url.strip())
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise APIError(
            code=ErrorCode.PRODUCT_EXPERIENCE_URL_INVALID,
            message="url must start with http:// or https:// and have a host",
            http_status=400,
        )

    name = (payload.name or parsed_url.netloc).strip()
    slug = _normalize_manual_slug(parsed_url.netloc)
    report_id = str(uuid4())
    now = datetime.now(timezone.utc)

    from src.scheduler.jobs import (  # noqa: PLC0415
        _resolve_unique_project_name,
        _slugify_for_project_name,
    )

    factory = get_async_session_factory()
    async with factory() as session:
        raw_pname = _slugify_for_project_name(slug=slug, name=name)
        project_name = await _resolve_unique_project_name(
            session, raw_pname, model=ProductExperienceReport
        )
        row = ProductExperienceReport(
            id=UUID(report_id),
            product_slug=slug,
            product_url=payload.url.strip(),
            product_name=name,
            project_name=project_name,
            run_started_at=now,
            status="running",
            login_used="skipped",
        )
        session.add(row)
        await session.commit()

    asyncio.create_task(
        _run_codex_for_manual(
            report_id=report_id,
            url=payload.url.strip(),
            name=name,
            slug=slug,
            requires_login=payload.requires_login,
        )
    )
    logger.info(
        "手动体验已排队",
        report_id=report_id,
        url=payload.url[:120],
        requires_login=payload.requires_login,
    )

    return ExperienceUrlResponse(report_id=report_id, status="running")
