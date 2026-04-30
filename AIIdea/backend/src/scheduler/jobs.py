from contextlib import contextmanager
from datetime import datetime

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from structlog.contextvars import bind_contextvars, clear_contextvars

from src.config import Settings
from src.db import get_async_session_factory
from src.collectors.base import BaseCollector
from src.collectors.hackernews import HackerNewsCollector
from src.collectors.rss_collector import RSSCollector
from src.collectors.reddit import RedditCollector
from src.collectors.producthunt import ProductHuntCollector
from src.collectors.github_trending import GitHubTrendingCollector
from src.collectors.twitter_trends import TwitterTrendsCollector
from src.collectors.generic_html import GenericHTMLCollector
from src.collectors.generic_json import GenericJSONCollector
from src.collectors.sources_registry import SOURCES
from src.collectors.ingester import ingest_items
from src.processors.pipeline import run_processing_pipeline
from src.agent.graph import run_analysis_agent
from src.api.pipeline import clear_scheduled_running, mark_scheduled_running
from src.logging_setup import generate_request_id
from src.models.analysis_result import AnalysisResult
from src.scheduler.runs import record_finish, record_start

logger = structlog.get_logger()


@contextmanager
def _cron_log_scope(job_id: str):
    """Bind a request_id + job_id into structlog contextvars for the duration
    of a cron job invocation. Ensures the project's "all logs must carry
    request_id" rule is satisfied for non-HTTP code paths.
    """
    request_id = f"cron-{job_id}-{generate_request_id()[:8]}"
    clear_contextvars()
    bind_contextvars(request_id=request_id, job_id=job_id)
    try:
        yield request_id
    finally:
        clear_contextvars()


def _parse_source_item_uuid(raw: str | None):
    """Parse the LLM-reported source_item_id string into a UUID.

    The agent might emit ``"null"`` / ``"(none)"`` / a malformed string if it
    couldn't locate one. Returning ``None`` in those cases keeps bad rows
    out of the DB while still writing the rest of the report.
    """
    if not raw:
        return None
    import uuid as _uuid
    try:
        return _uuid.UUID(raw.strip())
    except (ValueError, AttributeError):
        logger.info("锚点 source_item_id 非法", raw=raw[:80])
        return None


def _slugify_for_project_name(*, slug: str | None, name: str | None) -> str | None:
    """Derive a 1-3-token kebab slug from a product slug or display name.

    Used for ProductExperienceReport.project_name — the LLM doesn't supply
    one, so we synthesize from existing fields. Strips known prefixes
    (``ph-`` from Product Hunt, ``manual-`` from user-submitted URL),
    drops uuid-looking trailing tokens, then keeps at most 3 segments.
    """
    import re

    candidate: str | None = None
    if slug:
        s = slug.strip().lower()
        # Strip discovery-source prefixes; they're not part of the product name.
        for prefix in ("ph-", "manual-", "toolify-"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        parts = [p for p in s.split("-") if p]
        # Drop trailing uuid-ish tokens (e.g. "logic-a61802c1-1f81-...").
        parts = [p for p in parts if not re.fullmatch(r"[0-9a-f]{8,}", p)]
        # Drop pure-numeric trailing dedupe suffixes ("-2") only if other tokens remain.
        while len(parts) > 1 and parts[-1].isdigit():
            parts.pop()
        if parts:
            candidate = "-".join(parts[:3])

    if not candidate and name:
        # Last-resort: ASCII-fy display name. Non-ASCII glyphs become "-".
        norm = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if norm:
            candidate = "-".join([p for p in norm.split("-") if p][:3])

    if not candidate:
        return None
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+){0,2}", candidate):
        return None
    return candidate[:40].rstrip("-")


async def _resolve_unique_project_name(
    session, raw_name: str | None, *, model=None
) -> str | None:
    """Return a project_name unique within ``model``'s table.

    ``model`` defaults to AnalysisResult (idea path) but ProductExperience
    rows pass the experience model. The candidate is used as-is when free;
    on collision a 4-character lowercase suffix is appended ("-abcd").
    """
    import re
    import secrets
    import string

    from sqlalchemy import select as _select

    if model is None:
        from src.models.analysis_result import AnalysisResult as _Default
        model = _Default

    if not raw_name:
        return None
    candidate = raw_name.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+){0,2}", candidate):
        logger.warning("项目名格式非法", raw=raw_name[:80])
        return None
    if len(candidate) > 40:
        candidate = candidate[:40].rstrip("-")

    alphabet = string.ascii_lowercase + string.digits

    async def _exists(name: str) -> bool:
        return (
            await session.execute(
                _select(model.id).where(model.project_name == name).limit(1)
            )
        ).scalar_one_or_none() is not None

    if not await _exists(candidate):
        return candidate

    base = candidate[:35].rstrip("-")
    for _ in range(5):
        suffix = "".join(secrets.choice(alphabet) for _ in range(4))
        candidate = f"{base}-{suffix}"
        if not await _exists(candidate):
            return candidate
    logger.warning("项目名冲突未解", base=base)
    return candidate


def build_collectors() -> list[BaseCollector]:
    """Build the full collector list for a scheduled collect run.

    Specialized collectors (HN / Reddit / GitHub / PH / Twitter) stay hardcoded.
    Everything else flows through the registry + generic collectors.
    """
    collectors: list[BaseCollector] = [
        HackerNewsCollector(),
        RedditCollector(),
        ProductHuntCollector(),
        GitHubTrendingCollector(),
        TwitterTrendsCollector(),
    ]

    # Aggregate all enabled RSS sources into a single RSSCollector.
    # Registry entries use ``name="rss:xxx"``; strip the prefix because
    # RSSCollector re-prepends ``rss:`` to each feed key.
    rss_feeds: dict[str, str] = {}
    for s in SOURCES:
        if not s.enabled or s.kind != "rss":
            continue
        key = s.name[4:] if s.name.startswith("rss:") else s.name
        rss_feeds[key] = s.url
    if rss_feeds:
        collectors.append(RSSCollector(feeds=rss_feeds))
        logger.info("已加载 RSS 注册", count=len(rss_feeds))

    html_count = 0
    json_count = 0
    for s in SOURCES:
        if not s.enabled:
            continue
        if s.kind == "html":
            collectors.append(GenericHTMLCollector(s))
            html_count += 1
        elif s.kind == "json":
            collectors.append(GenericJSONCollector(s))
            json_count += 1
    logger.info(
        "已加载通用注册",
        html_count=html_count,
        json_count=json_count,
    )
    return collectors


async def collect_all_sources():
    with _cron_log_scope("collect_data"):
        await _collect_all_sources_impl()


async def _collect_all_sources_impl():
    logger.info("采集任务开始")
    mark_scheduled_running("collect_data")
    started_at = record_start("collect_data")
    try:
        collectors = build_collectors()

        all_items = []
        for collector in collectors:
            try:
                items = await collector.collect(limit=30)
                all_items.extend(items)
                logger.info(
                    "采集器完成",
                    collector=collector.__class__.__name__,
                    count=len(items),
                )
            except Exception:
                logger.exception(
                    "采集器失败",
                    collector=collector.__class__.__name__,
                )
            finally:
                await collector.close()

        factory = get_async_session_factory()
        async with factory() as session:
            ingested = await ingest_items(session, all_items)

        logger.info(
            "采集任务结束",
            total_collected=len(all_items),
            ingested=ingested,
        )
    except Exception as exc:
        record_finish(
            "collect_data",
            started_at,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    else:
        record_finish("collect_data", started_at, status="success")
    finally:
        clear_scheduled_running("collect_data")


async def process_collected_data():
    with _cron_log_scope("process_data"):
        await _process_collected_data_impl()


async def _process_collected_data_impl():
    logger.info("处理任务开始")
    mark_scheduled_running("process_data")
    started_at = record_start("process_data")
    try:
        factory = get_async_session_factory()
        async with factory() as session:
            processed = await run_processing_pipeline(session)

        logger.info("处理任务结束", processed=processed)
    except Exception as exc:
        record_finish(
            "process_data",
            started_at,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    else:
        record_finish("process_data", started_at, status="success")
    finally:
        clear_scheduled_running("process_data")


async def run_analysis():
    with _cron_log_scope("analyze_data"):
        await _run_analysis_outer()


async def _run_analysis_outer():
    logger.info("分析任务开始")
    mark_scheduled_running("analyze_data")
    started_at = record_start("analyze_data")

    from src.agent.extractor import extract_agent_report

    try:
        await _run_analysis_impl(extract_agent_report)
    except Exception as exc:
        record_finish(
            "analyze_data",
            started_at,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    else:
        record_finish("analyze_data", started_at, status="success")
    finally:
        clear_scheduled_running("analyze_data")


async def _run_analysis_impl(extract_agent_report) -> None:
    factory = get_async_session_factory()
    async with factory() as session:
        result = await run_analysis_agent(session)

        raw_report = result.get("analysis", "") or ""

        # Guard: agent produced an empty / trivially-short final message.
        # Without raw material, the extractor LLM will hallucinate a generic
        # idea from nothing. Skip immediately.
        if len(raw_report.strip()) < 80:
            logger.info(
                "分析任务跳过",
                reason="empty_report",
                length=len(raw_report),
            )
            return

        # Guard against agent bail-outs. When the critique tool rejects every
        # regeneration, the agent outputs "NO_VIABLE_IDEA_FOUND" (see
        # SYSTEM_PROMPT) — or when search returns nothing it might fall back
        # to "调整搜索策略". Either way, don't pollute the analysis table with
        # non-ideas; log and skip.
        bail_markers = (
            "NO_VIABLE_IDEA_FOUND",
            "NO_CONSUMER_ANCHOR_FOUND",
            "调整搜索策略",
            "建议调整搜索",
        )
        if any(marker in raw_report for marker in bail_markers):
            logger.info(
                "分析任务跳过",
                reason="agent_bailed",
                head=raw_report[:120],
            )
            return

        # Parse the free-form markdown into structured product fields so the
        # DB row has clean searchable columns instead of a markdown blob.
        try:
            report = await extract_agent_report(raw_report)
        except Exception:
            # Per feature-4: "结果不满足最低字段要求 → 不入库，记 error 日志".
            # An extraction failure means we can't guarantee idea_title /
            # overall_score, so the write is aborted.
            logger.exception("分析报告抽取失败")
            return

        # Second-line defense against silent agent bail-outs: if the report
        # has neither a real source_quote nor a user_story, the agent
        # short-circuited without going through generate_ideas + critique.
        if not report.source_quote and not report.user_story:
            logger.info(
                "分析任务跳过",
                reason="no_lineage",
                title=(report.idea_title or "")[:80],
                head=raw_report[:120],
            )
            return

        # Project-positioning guard: this product is "AI Idea",
        # the analysis table is meant for internet/AI/SaaS product ideas.
        # When the agent drifts into physical goods, offline services, or
        # pure life-hack tips (e.g. "anti-squirrel package bag"), drop the
        # row instead of polluting the list. Extractor judges with a second
        # LLM pass on idea_title + product_idea + key_features.
        if not report.is_digital_product:
            logger.info(
                "分析任务跳过",
                reason="non_digital_product",
                title=(report.idea_title or "")[:80],
                form=report.digital_product_form,
            )
            return

        # Feature-4 hard requirement: drop the record when the two required
        # fields are missing. This is the rule the reviewer flagged.
        if not report.idea_title or report.overall_score is None:
            logger.error(
                "分析缺必填字段",
                idea_title_present=bool(report.idea_title),
                score_present=report.overall_score is not None,
            )
            return

        try:
            overall_score = float(report.overall_score)
        except (TypeError, ValueError):
            logger.error(
                "分析评分非法",
                raw=str(report.overall_score)[:40],
            )
            return

        # Defensive de-dup + signal_type cap. Even though search_items now
        # filters anchored items out, the agent could still surface an old
        # cached source via synthesize_trends; bail if we already have a
        # row for this anchor. Also cap the score when the anchor turned
        # out to be a launch/story/news post (the analyzer mis-tagged it
        # or the agent went outside the default signal filter via
        # include_all_signal_types).
        anchor_uuid = _parse_source_item_uuid(report.source_item_id)
        if anchor_uuid is not None:
            from sqlalchemy import select as _select  # local to keep top imports lean
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
                    "分析任务跳过",
                    reason="duplicate_anchor",
                    source_item_id=str(anchor_uuid),
                )
                return

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
                        "分析评分被压制",
                        reason=f"anchor_signal_{anchor_signal}",
                        original=overall_score,
                        capped=capped,
                    )
                    overall_score = capped

        project_name = await _resolve_unique_project_name(
            session, getattr(report, "project_name", None)
        )

        analysis_record = AnalysisResult(
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
                "trace": result.get("trace", []),
                "message_count": result.get("message_count", 0),
            },
        )
        session.add(analysis_record)
        await session.commit()
        # Snapshot fields *inside* the session — accessing attrs after the
        # context closes would re-emit lazy SQL on a closed session.
        idea_snapshot = {
            "project_name": analysis_record.project_name,
            "product_type": analysis_record.product_type,
            "idea_title": analysis_record.idea_title,
            "overall_score": analysis_record.overall_score,
            "product_idea": analysis_record.product_idea,
            "user_story": analysis_record.user_story,
            "target_audience": analysis_record.target_audience,
            "use_case": analysis_record.use_case,
            "pain_points": analysis_record.pain_points,
            "key_features": analysis_record.key_features,
            "source_quote": analysis_record.source_quote,
            "reasoning": analysis_record.reasoning,
            "source_id": str(analysis_record.id),
        }

    logger.info(
        "分析任务结束",
        score=overall_score,
        title=report.idea_title[:60],
        has_quote=bool(report.source_quote),
        has_story=bool(report.user_story),
    )

    # Optional AIJuicer publish — never raises, never blocks.
    try:
        from src.integrations.aijuicer import maybe_publish_idea
        maybe_publish_idea(idea_snapshot)
    except Exception:
        logger.exception("AIJuicer idea 提交异常")


async def run_experience():
    with _cron_log_scope("experience_products"):
        await _run_experience_outer()


async def _run_experience_outer():
    logger.info("产品体验任务开始")
    mark_scheduled_running("experience_products")
    started_at = record_start("experience_products")
    try:
        await _run_experience_impl()
    except Exception as exc:
        record_finish(
            "experience_products",
            started_at,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    else:
        record_finish("experience_products", started_at, status="success")
    finally:
        clear_scheduled_running("experience_products")


async def _run_experience_impl() -> None:
    """Pick the longest-untouched candidate from product_candidates, run the
    experience agent, persist a ProductExperienceReport row.

    Selection: never-experienced candidates first (oldest discovered_at);
    fall back to oldest last_experienced_at. Bounded to one product per tick
    so a slow run can't hog the scheduler.
    """
    from datetime import timezone
    from pathlib import Path
    from uuid import UUID, uuid4

    from sqlalchemy import select

    from src.config import Settings
    from src.models.product_candidate import ProductCandidate
    from src.models.product_experience_report import ProductExperienceReport
    from src.product_experience import codex_runner as codex_runner_mod
    from src.product_experience.extractor import parse_agent_report

    factory = get_async_session_factory()
    async with factory() as session:
        candidate = (
            await session.execute(
                select(ProductCandidate)
                .where(ProductCandidate.last_experienced_at.is_(None))
                .order_by(ProductCandidate.discovered_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if candidate is None:
            candidate = (
                await session.execute(
                    select(ProductCandidate)
                    .order_by(ProductCandidate.last_experienced_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    if candidate is None:
        logger.info("产品体验任务跳过_候选池为空")
        return

    candidate_id = candidate.id
    candidate_slug = candidate.slug
    candidate_name = candidate.name
    candidate_url = candidate.homepage_url

    started = datetime.now(tz=timezone.utc)
    report_id = str(uuid4())
    status = "completed"
    failure_reason: str | None = None
    parsed = None
    run_result = None
    try:
        settings = Settings()  # type: ignore[call-arg]
        run_result = await codex_runner_mod.run_codex_experience(
            slug=candidate_slug,
            name=candidate_name,
            url=candidate_url,
            requires_login=True,
            report_id=report_id,
            base_dir=Path(settings.codex_experience_root),
            codex_binary=settings.codex_binary_path,
            timeout_seconds=600,
        )
        if run_result.markdown:
            parsed = parse_agent_report(run_result.markdown)
        else:
            # codex 起来了但没产报告（超时 / 没写 REPORT.md）。
            # codex_runner 已在 trace 里标了 reason，这里把 status 标 failed
            # 让前端能区分"完成但低分"与"根本没跑成"。
            status = "failed"
            failure_reason = run_result.trace.get("reason", "no_report")
    except Exception as exc:
        status = "failed"
        failure_reason = f"{type(exc).__name__}: {exc}"
        logger.exception("产品体验失败", slug=candidate_slug)

    completed = datetime.now(tz=timezone.utc)

    async with factory() as session:
        raw_pname = _slugify_for_project_name(slug=candidate_slug, name=candidate_name)
        project_name = await _resolve_unique_project_name(
            session, raw_pname, model=ProductExperienceReport
        )
        row = ProductExperienceReport(
            id=UUID(report_id),
            candidate_id=candidate_id,
            product_slug=candidate_slug,
            product_url=candidate_url,
            product_name=candidate_name,
            project_name=project_name,
            run_started_at=started,
            run_completed_at=completed,
            status=status,
            failure_reason=failure_reason,
            login_used=(run_result.login_status if run_result else "skipped"),
            screenshots=run_result.screenshots if run_result else None,
            agent_trace=run_result.trace if run_result else None,
        )
        if parsed is not None:
            from src.product_experience.extractor import apply_parsed_to_orm  # noqa: PLC0415
            apply_parsed_to_orm(row, parsed)
        session.add(row)
        # Bump candidate counters in the same transaction so a crash mid-write
        # doesn't leave the report orphaned from the candidate's tally.
        live = await session.get(ProductCandidate, candidate_id)
        if live is not None:
            live.last_experienced_at = completed
            live.experience_count = (live.experience_count or 0) + 1
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

    try:
        from src.integrations.aijuicer import maybe_publish_experience
        maybe_publish_experience(experience_snapshot)
    except Exception:
        logger.exception("AIJuicer 体验提交异常")

    logger.info(
        "产品体验任务结束",
        slug=candidate_slug,
        status=status,
        login_used=row.login_used,
        score=row.overall_ux_score,
    )


async def run_discover_products():
    with _cron_log_scope("discover_products"):
        await _run_discover_products_impl()


async def _run_discover_products_impl():
    """Cron entry point: refresh the product_candidates pool from all sources."""
    from src.product_discovery.runner import run_discovery_once

    logger.info("产品发现任务开始")
    mark_scheduled_running("discover_products")
    started_at = record_start("discover_products")
    try:
        summary = await run_discovery_once()
    except Exception as exc:
        record_finish(
            "discover_products",
            started_at,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    else:
        record_finish("discover_products", started_at, status="success")
        logger.info("产品发现任务结束", **summary)
    finally:
        clear_scheduled_running("discover_products")


def create_scheduler() -> AsyncIOScheduler:
    # pydantic-settings reads DATABASE_URL from the environment at instantiation;
    # mypy doesn't see that so we silence the call-arg noise at the call site.
    settings = Settings()  # type: ignore[call-arg]
    scheduler = AsyncIOScheduler()
    # Run each job once immediately on startup so the DB is not empty for the
    # first interval period; subsequent runs fall back to the normal schedule.
    now = datetime.now()

    scheduler.add_job(
        collect_all_sources,
        "interval",
        minutes=settings.collect_interval_minutes,
        id="collect_data",
        name="Collect data from all sources",
        next_run_time=now,
    )

    scheduler.add_job(
        process_collected_data,
        "interval",
        minutes=settings.process_interval_minutes,
        id="process_data",
        name="Process and classify collected data",
        next_run_time=now,
    )

    scheduler.add_job(
        run_analysis,
        "interval",
        minutes=settings.analysis_interval_minutes,
        id="analyze_data",
        name="Run AI agent analysis",
        next_run_time=now,
    )

    scheduler.add_job(
        run_discover_products,
        "interval",
        minutes=settings.discover_interval_minutes,
        id="discover_products",
        name="Refresh product candidate pool from discovery sources",
        next_run_time=now,
    )

    scheduler.add_job(
        run_experience,
        "interval",
        minutes=settings.experience_interval_minutes,
        id="experience_products",
        name="Browse a product candidate and produce an experience report",
        next_run_time=now,
    )

    return scheduler
