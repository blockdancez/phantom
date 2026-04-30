import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.source_item import SourceItem

logger = structlog.get_logger()


async def ingest_items(session: AsyncSession, raw_items: list[dict]) -> int:
    """Bulk insert raw items, skipping rows that collide on ``url``.

    Logs only one INFO line summarising the batch (count, ingested, skipped);
    per-item duplicate hits go to DEBUG to keep the steady-state log volume
    low. A single Reddit/RSS sweep otherwise produces ~300 noisy lines per
    minute.
    """
    ingested = 0
    skipped = 0

    for raw in raw_items:
        stmt = select(SourceItem).where(SourceItem.url == raw["url"])
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            logger.debug("入库跳过_重复", url=raw["url"])
            skipped += 1
            continue

        item = SourceItem(
            source=raw["source"],
            title=raw["title"],
            url=raw["url"],
            content=raw.get("content", ""),
            raw_data=raw.get("raw_data", {}),
        )
        session.add(item)
        ingested += 1

    await session.commit()
    logger.info(
        "入库完成",
        item_count=len(raw_items),
        ingested=ingested,
        skipped=skipped,
    )
    return ingested
