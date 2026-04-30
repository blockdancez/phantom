import uuid as uuid_mod

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Idea, Document
from app.agent.researcher import Researcher
from app.agent.writer import PrdWriter

logger = structlog.get_logger()


class AgentOrchestrator:
    def __init__(
        self,
        db_session: AsyncSession,
        researcher: Researcher,
        writer: PrdWriter,
    ):
        self.db = db_session
        self.researcher = researcher
        self.writer = writer

    async def process(
        self,
        idea_id: str,
        rerun_instruction: str | None = None,
    ) -> None:
        logger.info(
            "智能体流程开始",
            idea_id=idea_id,
            rerun=bool(rerun_instruction),
        )

        result = await self.db.execute(select(Idea).where(Idea.id == uuid_mod.UUID(idea_id)))
        idea = result.scalar_one_or_none()
        if not idea:
            logger.error("未找到创意", idea_id=idea_id)
            return

        # On rerun with instruction, snapshot the previous PRD before we wipe
        # it so the writer can edit it surgically. Without this, reruns drift.
        previous_prd: str | None = None
        if rerun_instruction:
            prev = await self.db.execute(
                select(Document)
                .where(Document.idea_id == idea.id)
                .order_by(Document.created_at.desc())
            )
            prev_doc = prev.scalars().first()
            if prev_doc:
                previous_prd = prev_doc.content

        try:
            idea.status = "researching"
            await self.db.commit()

            # Skip Tavily on edit mode — already encoded in the previous PRD,
            # and re-querying drifts the framing.
            if previous_prd is None:
                research = await self.researcher.research(idea.content)
            else:
                research = {"keywords": [], "competitors": []}

            idea.status = "writing"
            await self.db.commit()

            prd = await self.writer.generate(
                idea=idea.content,
                research=research,
                rerun_instruction=rerun_instruction,
                previous_prd=previous_prd,
            )

            # Replace prior document(s) so reruns produce a fresh PRD
            # without breaking the one-to-one Idea↔Document invariant.
            await self.db.execute(delete(Document).where(Document.idea_id == idea.id))

            doc = Document(
                idea_id=idea.id,
                title=prd["title"],
                content=prd["content"],
                research=research,
            )
            self.db.add(doc)

            idea.status = "completed"
            await self.db.commit()

            logger.info("智能体流程完成", idea_id=idea_id, doc_title=prd["title"])

        except Exception as e:
            logger.error("智能体流程失败", idea_id=idea_id, error=str(e), exc_info=True)
            idea.status = "failed"
            await self.db.commit()


async def run_agent(idea_id: str, rerun_instruction: str | None = None) -> None:
    from openai import AsyncOpenAI

    from app.config import get_settings
    from app.database import SessionLocal

    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    researcher = Researcher(tavily_api_key=settings.tavily_api_key)
    writer = PrdWriter(openai_client=client, model=settings.openai_model)

    async with SessionLocal() as session:
        orchestrator = AgentOrchestrator(
            db_session=session,
            researcher=researcher,
            writer=writer,
        )
        await orchestrator.process(idea_id, rerun_instruction=rerun_instruction)
