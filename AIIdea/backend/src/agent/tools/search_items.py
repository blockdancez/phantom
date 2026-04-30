import structlog
from langchain_core.tools import tool
from sqlalchemy import select, or_

from src.db import get_async_session_factory
from src.models.analysis_result import AnalysisResult
from src.models.source_item import SourceItem

logger = structlog.get_logger()


# By default search only returns items the analyzer tagged as user-pain or
# user-question signals. Launch posts ("Built X"), nostalgia stories, and
# press-release news are technically processed but make terrible idea
# anchors — agent ends up copying products or building on storytelling.
_DEFAULT_SIGNAL_TYPES = ("pain_point", "question")


@tool
async def search_items(
    query: str,
    category: str = "",
    min_score: float = 0.0,
    limit: int = 20,
    source_contains: str = "",
    include_all_signal_types: bool = False,
) -> str:
    """Search collected source items by keyword. Use source_contains to restrict to specific data sources (e.g. source_contains='mildlyinfuriating' to only match r/mildlyinfuriating, or source_contains='rss:nyt' for NYT feeds). By default only signal_type IN ('pain_point','question') items are returned — set include_all_signal_types=True to also see launch/story/news posts (rarely useful as idea anchors). Items already used as an anchor for a previously-generated AnalysisResult are filtered out so the agent doesn't reanchor the same source twice. Returns formatted text summaries with item IDs so downstream tools can cite them."""
    logger.info(
        "工具_搜索条目",
        query=query,
        category=category,
        min_score=min_score,
        source_contains=source_contains,
        include_all_signal_types=include_all_signal_types,
    )

    # Open a fresh AsyncSession for each call. LangGraph's ToolNode runs tool
    # calls concurrently, but a single AsyncSession cannot be shared across
    # concurrent queries (SQLAlchemy raises InvalidRequestError). Isolating
    # each call prevents the "concurrent operations are not permitted" error.
    factory = get_async_session_factory()
    async with factory() as session:
        stmt = select(SourceItem).where(SourceItem.processed == True)  # noqa: E712

        if not include_all_signal_types:
            stmt = stmt.where(SourceItem.signal_type.in_(_DEFAULT_SIGNAL_TYPES))

        # Exclude items already anchored to a previous AnalysisResult so
        # the agent doesn't re-anchor on a source it's already used.
        anchored_ids = select(AnalysisResult.source_item_id).where(
            AnalysisResult.source_item_id.is_not(None)
        )
        stmt = stmt.where(SourceItem.id.notin_(anchored_ids))

        if min_score > 0:
            stmt = stmt.where(SourceItem.score >= min_score)
        if category:
            stmt = stmt.where(SourceItem.category == category)
        if source_contains:
            stmt = stmt.where(SourceItem.source.ilike(f"%{source_contains}%"))

        stmt = stmt.where(
            or_(
                SourceItem.title.ilike(f"%{query}%"),
                SourceItem.content.ilike(f"%{query}%"),
            )
        ).order_by(SourceItem.score.desc().nullslast()).limit(limit)

        result = await session.execute(stmt)
        items = result.scalars().all()

        if not items:
            return f"No items found matching '{query}'"

        lines = []
        for item in items:
            # item.id is surfaced as "ID:" so trend_synthesizer / idea_generator
            # can cite specific source items by uuid rather than losing the
            # lineage into free-form narrative.
            lines.append(
                f"- ID: {item.id}\n"
                f"  Source: {item.source} | Score: {item.score} | Category: {item.category} | Signal: {item.signal_type}\n"
                f"  Title: {item.title}\n"
                f"  URL: {item.url}\n"
                f"  Tags: {', '.join(item.tags or [])}\n"
                f"  Content: {item.content[:300]}"
            )

        return "\n\n".join(lines)
