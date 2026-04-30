import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Idea
from app.schemas import IdeaCreate, IdeaRegenerate, IdeaResponse, IdeaListResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


@router.post("", response_model=IdeaResponse, status_code=201)
async def create_idea(
    body: IdeaCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    idea = Idea(content=body.content)
    db.add(idea)
    await db.commit()
    await db.refresh(idea)

    logger.info("创建创意", idea_id=str(idea.id))

    background_tasks.add_task(process_idea, str(idea.id))

    return idea


@router.get("", response_model=IdeaListResponse)
async def list_ideas(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Idea).order_by(Idea.created_at.desc()))
    ideas = result.scalars().all()
    return IdeaListResponse(ideas=ideas, total=len(ideas))


@router.get("/{idea_id}", response_model=IdeaResponse)
async def get_idea(idea_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Idea).where(Idea.id == idea_id))
    idea = result.scalar_one_or_none()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.post("/{idea_id}/regenerate", response_model=IdeaResponse)
async def regenerate_idea(
    idea_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    body: IdeaRegenerate = IdeaRegenerate(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Idea).where(Idea.id == idea_id))
    idea = result.scalar_one_or_none()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    if idea.status in ("researching", "writing"):
        raise HTTPException(status_code=409, detail="任务进行中，请稍后再试")

    idea.status = "researching"
    await db.commit()
    await db.refresh(idea)

    logger.info(
        "提交重新生成请求",
        idea_id=str(idea.id),
        has_instruction=bool(body.rerun_instruction),
    )

    background_tasks.add_task(
        process_idea_regenerate, str(idea.id), body.rerun_instruction
    )
    return idea


async def process_idea(idea_id: str) -> None:
    from app.agent.orchestrator import run_agent
    await run_agent(idea_id)


async def process_idea_regenerate(idea_id: str, rerun_instruction: str | None) -> None:
    from app.agent.orchestrator import run_agent
    await run_agent(idea_id, rerun_instruction=rerun_instruction)
