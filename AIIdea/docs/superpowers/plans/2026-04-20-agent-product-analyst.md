# Product-Analyst Agent Capabilities Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the manual "query DB → cluster pain signals by theme → survey competitors → model monetization → scope MVP → pick one winner" analysis pattern (demonstrated in the Fridge-to-Table recommendation) into first-class agent capabilities, so automated analyze_data runs produce reports that match what a senior PM would write.

**Architecture:** Add 4 new LangChain tools (`analyze_pain_clusters`, `survey_competitors`, `propose_monetization`, `scope_mvp`) to the existing LangGraph agent. Rewrite `SYSTEM_PROMPT` to force a top-down PM workflow: cluster-first, multi-candidate, full-stack analysis. Extend `AnalysisResult` with four new JSONB/Text columns (competitors, monetization, mvp_scope, why_now). Display on detail page.

**Tech Stack:** Python 3.12 / FastAPI / LangGraph / LangChain / OpenAI gpt-4o / Alembic / SQLAlchemy async + JSONB / Next.js 16 / Tailwind v4.

---

## Context

The `analyze_data` LangGraph agent currently:

1. Runs several `search_items` calls with random keywords
2. Calls `synthesize_trends` to abstract them
3. Calls `generate_ideas` to pick one anchor item and write an idea
4. Calls `critique_idea` to filter obvious logic failures (4 hard + 2 soft axes)
5. Emits one markdown report

Observed failures from 54 saved reports:
- Agent picks whichever anchor survives critique first, rather than the **biggest opportunity**
- "Competitive landscape" axis is hand-wavy — agent hallucinates "market is crowded" but can't name specific products
- **No monetization model** — agent never reasons about pricing / unit economics / ARR
- **No MVP scope** — agent never scopes what to build, in what phases, with what tech stack
- No "why now" timing thesis
- No comparison of multiple candidates before committing

When I (the user) manually ran this analysis against the same DB, I produced the Fridge-to-Table recommendation, which:
- Started with keyword-frequency aggregation across the whole corpus (find biggest pain cluster)
- Named 5 specific competitors and called out each one's blindspot
- Proposed 3-tier pricing with unit economics
- Scoped Phase 0 / 1 / 2 MVP
- Argued "why now" (GPT-4o Vision + Instacart API + React Native maturity)
- Ranked 6 candidates before committing to 1

This plan closes that gap in the agent's capabilities.

---

## File Structure

### New files
- `backend/src/agent/tools/pain_clusters.py` — Aggregate SQL-based theme counter (see Task 1)
- `backend/src/agent/tools/survey_competitors.py` — LLM competitor survey (Task 2)
- `backend/src/agent/tools/propose_monetization.py` — LLM monetization modeler (Task 3)
- `backend/src/agent/tools/scope_mvp.py` — LLM MVP phaser (Task 4)
- `backend/alembic/versions/a9e3f2b5c7d4_pm_analysis_fields.py` — Schema migration (Task 6)

### Modified files
- `backend/src/agent/tools/__init__.py` — Register 4 new tools (Task 5)
- `backend/src/agent/prompts.py` — Full workflow rewrite (Task 11)
- `backend/src/agent/extractor.py` — Extend `AgentReport` with new fields (Task 9)
- `backend/src/models/analysis_result.py` — Add 4 columns (Task 7)
- `backend/src/schemas/analysis_result.py` — Add 4 fields (Task 8)
- `backend/src/scheduler/jobs.py` — Persist 4 fields on save (Task 10)
- `frontend/src/lib/types.ts` — Extend `AnalysisResult` interface (Task 12)
- `frontend/src/app/analysis/[id]/page.tsx` — Render 4 new sections (Task 13)

---

## Task 1: Pain Cluster Tool

**Files:**
- Create: `backend/src/agent/tools/pain_clusters.py`

The agent currently jumps straight into per-item search. This tool gives it a corpus-wide theme histogram so it can see where the biggest pain is concentrated before diving in.

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/pain_clusters.py`:

```python
"""Aggregate pain signals across the corpus by theme. Gives the agent a
histogram of clusters so it can target the biggest opportunity instead of
picking whatever random anchor survives critique.
"""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from sqlalchemy import func, or_, select

from src.db import get_async_session_factory
from src.models.source_item import SourceItem

logger = structlog.get_logger()


_CLUSTERS: dict[str, list[str]] = {
    "做饭备餐": ["meal", "dinner", "recipe", "groceries", "cooking", "ingredient"],
    "家庭育儿": ["my kid", "my son", "my daughter", "toddler", "newborn", "parenting"],
    "求职面试": ["interview", "resume", "job search", "hiring", "recruiter"],
    "财务债务": ["debt", "credit card", "HSA", "401k", "savings", "invest"],
    "教育辅导": ["tutor", "homework", "study", "course"],
    "通勤出行": ["commute", "subway", "parking", "uber", "lyft", "traffic"],
    "健身减重": ["workout", "exercise", "diet", "lose weight", "fitness"],
    "生活琐事": ["laundry", "cleaning", "annoying", "frustrating", "wish"],
}


def _or_conditions(keywords: list[str]):
    conditions = []
    for kw in keywords:
        conditions.append(SourceItem.title.ilike(f"%{kw}%"))
        conditions.append(SourceItem.content.ilike(f"%{kw}%"))
    return or_(*conditions)


@tool
async def analyze_pain_clusters(top_n: int = 3) -> str:
    """Survey the corpus for the top_n biggest pain clusters (by keyword match count). Returns cluster name, hit count, and up to 3 sample items (id + title + excerpt) per cluster. Call this FIRST to pick where to dig, then use search_items / synthesize_trends on the top cluster's theme."""
    logger.info("tool_analyze_pain_clusters", top_n=top_n)

    factory = get_async_session_factory()
    async with factory() as session:
        summaries: list[tuple[str, int, list]] = []
        for name, keywords in _CLUSTERS.items():
            cond = _or_conditions(keywords)
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(SourceItem)
                    .where(SourceItem.processed.is_(True))
                    .where(cond)
                )
            ).scalar_one()
            samples = (
                await session.execute(
                    select(SourceItem)
                    .where(SourceItem.processed.is_(True))
                    .where(cond)
                    .order_by(SourceItem.score.desc().nullslast())
                    .limit(3)
                )
            ).scalars().all()
            summaries.append((name, int(count), samples))

    summaries.sort(key=lambda x: x[1], reverse=True)
    lines: list[str] = []
    for name, count, items in summaries[:top_n]:
        lines.append(f"## 痛点簇：{name}（{count} 条信号）")
        for it in items:
            excerpt = (it.content or "").replace("\n", " ")[:180]
            lines.append(f"- ID: {it.id}")
            lines.append(f"  [{it.source}] {it.title[:80]}")
            lines.append(f"  节选: {excerpt}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 2: Manually smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
  PYTHONPATH=. \
  python -c "
import asyncio
from src.agent.tools.pain_clusters import analyze_pain_clusters
print(asyncio.run(analyze_pain_clusters.ainvoke({'top_n': 3})))
"
```

Expected: 3 cluster headers (e.g. `做饭备餐`、`求职面试`、`生活琐事`) each with 3 items, counts shown next to each cluster name.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/pain_clusters.py
git commit -m "feat(agent): add analyze_pain_clusters tool for top-down theme view"
```

---

## Task 2: Competitor Survey Tool

**Files:**
- Create: `backend/src/agent/tools/survey_competitors.py`

Replaces the vague `competitive_landscape` check in critique with an LLM-sourced list of named products and their blindspots. No web search — relies on gpt-4o's training-time knowledge; good enough for well-known US consumer categories.

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/survey_competitors.py`:

```python
"""Given a candidate product idea, ask an LLM to name real competitors
(by product name), their core positioning, pricing, and blindspots.

No web search — this uses the model's internal knowledge. Works well for
well-known US consumer categories; weaker for regional or very niche
products. Treat output as a hypothesis, not ground truth.
"""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


_PROMPT = """你是资深产品分析师。根据以下 idea，列出美国市场**真实存在的**竞品。

## 输入

产品 idea: {idea_description}
目标用户: {target_audience}

## 要求

1. 只列你有确切印象的真实产品。如果某方向没有清晰竞品，写 `(无明显竞品)`。
2. 列 3-5 个。每条包括：
   - 产品名（必须真实存在）
   - 核心功能一句话
   - 定价或商业模式
   - **盲区**（它做得差、是我们机会的那块）
3. 禁止"已有很多类似产品"类泛泛说辞——必须指名道姓。

## 输出（严格 JSON，不要 Markdown 代码块包裹）

{{
  "competitors": [
    {{
      "name": "竞品名",
      "core_feature": "它核心做什么",
      "pricing": "定价/商业模式",
      "blindspot": "它没做好的地方，是我们的机会"
    }}
  ],
  "market_gap_summary": "一句话总结我们的差异化突破点"
}}
"""


@tool
async def survey_competitors(idea_description: str, target_audience: str = "") -> str:
    """Survey real US-market competitors for a given product idea. Returns JSON with named competitors, their positioning, pricing, and blindspots, plus a one-line market_gap_summary. LLM-only (no web search)."""
    logger.info("tool_survey_competitors", desc=idea_description[:80])
    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
    prompt = _PROMPT.format(
        idea_description=idea_description,
        target_audience=target_audience or "(未指定)",
    )
    resp = await llm.ainvoke(prompt)
    return resp.content
```

- [ ] **Step 2: Manually smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
PYTHONPATH=. python -c "
import asyncio
from src.agent.tools.survey_competitors import survey_competitors
print(asyncio.run(survey_competitors.ainvoke({
  'idea_description': '拍冰箱照片，AI 生成一周晚餐菜单 + 购物清单',
  'target_audience': '25-45 岁双职工家长',
})))
"
```

Expected: a JSON block listing e.g. SuperCook, Whisk, Mealime, Yummly with core_feature, pricing, blindspot each.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/survey_competitors.py
git commit -m "feat(agent): add survey_competitors tool"
```

---

## Task 3: Monetization Tool

**Files:**
- Create: `backend/src/agent/tools/propose_monetization.py`

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/propose_monetization.py`:

```python
"""Ask an LLM to design a three-tier pricing model with unit economics
for a product idea. Keeps the agent honest about how money would flow —
today it never reasons about pricing at all.
"""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


_PROMPT = """你是 SaaS 定价策略师。为下面的产品 idea 设计一个清晰的盈利模型。

## 输入

产品 idea: {idea_description}
目标用户: {target_audience}

## 要求

1. 三档订阅：免费（获客） / Basic（付费主力） / Premium（高 ARPU）。每档有清晰区分，不要只是"功能更多"。
2. 估算 unit economics：
   - 每用户月 API / 服务器成本（若用 LLM，参考 gpt-4o-mini ≈ $0.15/1M input + $0.60/1M output；GPT-4o Vision ≈ $2.50/1M input + $10/1M output）
   - 毛利百分比
   - 100K MAU 下的 Year 1 ARR 估计（默认 10% 转化率，可调）

## 输出（严格 JSON，不要 Markdown 代码块包裹）

{{
  "tiers": [
    {{"name": "Free", "price_usd": 0, "limits": "每周 1 次 / 上限 5 食材", "target_user": "尝鲜用户"}},
    {{"name": "Basic", "price_usd": 6.99, "limits": "无限次 + 偏好记忆", "target_user": "主力付费用户"}},
    {{"name": "Premium", "price_usd": 12.99, "limits": "Basic + 家庭共享 + Instacart 下单", "target_user": "重度家庭用户"}}
  ],
  "unit_economics": {{
    "api_cost_per_user_per_month_usd": 0.08,
    "gross_margin_pct": 98,
    "year_1_arr_estimate_usd": 70000,
    "assumptions": "100K MAU、10% 转化、Basic 用户月活 4 次"
  }}
}}
"""


@tool
async def propose_monetization(idea_description: str, target_audience: str = "") -> str:
    """Design a three-tier freemium pricing model (Free/Basic/Premium) with unit economics for a product idea. Returns JSON with tiers + unit_economics."""
    logger.info("tool_propose_monetization", desc=idea_description[:80])
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    prompt = _PROMPT.format(
        idea_description=idea_description,
        target_audience=target_audience or "(未指定)",
    )
    resp = await llm.ainvoke(prompt)
    return resp.content
```

- [ ] **Step 2: Manually smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
PYTHONPATH=. python -c "
import asyncio
from src.agent.tools.propose_monetization import propose_monetization
print(asyncio.run(propose_monetization.ainvoke({
  'idea_description': '拍冰箱照片，AI 生成一周晚餐菜单 + 购物清单',
  'target_audience': '25-45 岁双职工家长',
})))
"
```

Expected: JSON with 3 tiers + unit_economics block.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/propose_monetization.py
git commit -m "feat(agent): add propose_monetization tool"
```

---

## Task 4: MVP Scope Tool

**Files:**
- Create: `backend/src/agent/tools/scope_mvp.py`

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/scope_mvp.py`:

```python
"""Ask an LLM to break a candidate idea into 3 phased MVP increments
(Phase 0 proof-of-concept, Phase 1 MVP, Phase 2 scale). Each phase has
concrete scope, tech stack, and exit criteria.
"""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


_PROMPT = """你是技术产品负责人。为下面的产品 idea 拆分一个 2-4 周可达 MVP 的三阶段实施计划。

## 输入

产品 idea: {idea_description}
主要功能: {key_features}

## 约束

- 2-3 人小团队
- 演进路线：Web 原型 → 完整 Web MVP → React Native / iOS app
- 允许使用现成服务：Next.js / Supabase / Stripe / 各家 LLM API / Cloudflare / Vercel
- 不引入硬件、不自建基础设施
- 每一期都要能独立跑起来，且能被 5 个真实用户试用

## 输出（严格 JSON，不要 Markdown 代码块包裹）

{{
  "phases": [
    {{
      "name": "Phase 0",
      "duration": "1 周",
      "goal": "验证核心能力",
      "scope": ["功能点 1", "功能点 2"],
      "tech": ["Next.js", "GPT-4o Vision API"],
      "exit_criteria": "5 位用户测试后的 pass 标准"
    }},
    {{"name": "Phase 1", "duration": "2 周", "goal": "...", "scope": ["..."], "tech": ["..."], "exit_criteria": "..."}},
    {{"name": "Phase 2", "duration": "1-2 月", "goal": "...", "scope": ["..."], "tech": ["..."], "exit_criteria": "..."}}
  ],
  "total_estimate": "2-3 周到 Phase 1 / 1-2 月到 Phase 2"
}}
"""


@tool
async def scope_mvp(idea_description: str, key_features: str = "") -> str:
    """Break a product idea into three MVP phases (Phase 0 / 1 / 2) with scope, tech stack, and exit criteria per phase. Returns JSON with phases + total_estimate."""
    logger.info("tool_scope_mvp", desc=idea_description[:80])
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    prompt = _PROMPT.format(
        idea_description=idea_description,
        key_features=key_features or "(未指定)",
    )
    resp = await llm.ainvoke(prompt)
    return resp.content
```

- [ ] **Step 2: Manually smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
PYTHONPATH=. python -c "
import asyncio
from src.agent.tools.scope_mvp import scope_mvp
print(asyncio.run(scope_mvp.ainvoke({
  'idea_description': '拍冰箱照片，AI 生成一周晚餐菜单',
  'key_features': '冰箱视觉识别, 偏好对话, 购物清单导出',
})))
"
```

Expected: JSON with 3 phases.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/scope_mvp.py
git commit -m "feat(agent): add scope_mvp tool"
```

---

## Task 5: Register New Tools

**Files:**
- Modify: `backend/src/agent/tools/__init__.py`

- [ ] **Step 1: Rewrite the tools init**

Overwrite `backend/src/agent/tools/__init__.py` with:

```python
from src.agent.tools.critique_idea import critique_idea
from src.agent.tools.idea_generator import generate_ideas
from src.agent.tools.market_analysis import analyze_market
from src.agent.tools.pain_clusters import analyze_pain_clusters
from src.agent.tools.propose_monetization import propose_monetization
from src.agent.tools.scope_mvp import scope_mvp
from src.agent.tools.search_items import search_items
from src.agent.tools.survey_competitors import survey_competitors
from src.agent.tools.tech_feasibility import assess_tech_feasibility
from src.agent.tools.trend_synthesizer import synthesize_trends

all_tools = [
    # Discovery
    analyze_pain_clusters,
    search_items,
    synthesize_trends,
    # Ideation
    generate_ideas,
    # Validation (existing)
    critique_idea,
    analyze_market,
    assess_tech_feasibility,
    # New PM analysis
    survey_competitors,
    propose_monetization,
    scope_mvp,
]
```

- [ ] **Step 2: Smoke-test import**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "from src.agent.tools import all_tools; print(len(all_tools), [t.name for t in all_tools])"
```

Expected: `10 ['analyze_pain_clusters', 'search_items', 'synthesize_trends', 'generate_ideas', 'critique_idea', 'analyze_market', 'assess_tech_feasibility', 'survey_competitors', 'propose_monetization', 'scope_mvp']`

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/__init__.py
git commit -m "feat(agent): register 4 new PM-analysis tools"
```

---

## Task 6: Alembic Migration for PM Fields

**Files:**
- Create: `backend/alembic/versions/a9e3f2b5c7d4_pm_analysis_fields.py`

- [ ] **Step 1: Create migration file**

Write to `backend/alembic/versions/a9e3f2b5c7d4_pm_analysis_fields.py`:

```python
"""PM analysis fields

Revision ID: a9e3f2b5c7d4
Revises: f4a8c2e9d5b7
Create Date: 2026-04-20 13:00:00.000000

Adds four PM-level analysis fields to analysis_results:

- competitors (JSONB) — list of {name, core_feature, pricing, blindspot}
- monetization (JSONB) — {tiers: [...], unit_economics: {...}}
- mvp_scope (JSONB) — {phases: [...], total_estimate}
- why_now (Text) — one-paragraph timing thesis
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "a9e3f2b5c7d4"
down_revision: Union[str, None] = "f4a8c2e9d5b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis_results", sa.Column("competitors", JSONB(), nullable=True))
    op.add_column("analysis_results", sa.Column("monetization", JSONB(), nullable=True))
    op.add_column("analysis_results", sa.Column("mvp_scope", JSONB(), nullable=True))
    op.add_column("analysis_results", sa.Column("why_now", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_results", "why_now")
    op.drop_column("analysis_results", "mvp_scope")
    op.drop_column("analysis_results", "monetization")
    op.drop_column("analysis_results", "competitors")
```

- [ ] **Step 2: Apply the migration**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
  PYTHONPATH=. alembic upgrade head
```

Expected last line: `Running upgrade f4a8c2e9d5b7 -> a9e3f2b5c7d4, PM analysis fields`

- [ ] **Step 3: Verify columns exist**

```bash
PGPASSWORD=1234 psql -h localhost -U postgres -d ai_idea_finder -c "\d analysis_results" | grep -E "competitors|monetization|mvp_scope|why_now"
```

Expected: 4 lines, one per new column.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/a9e3f2b5c7d4_pm_analysis_fields.py
git commit -m "db: add PM analysis fields (competitors/monetization/mvp_scope/why_now)"
```

---

## Task 7: Update AnalysisResult Model

**Files:**
- Modify: `backend/src/models/analysis_result.py`

- [ ] **Step 1: Add the 4 new mapped columns**

In `backend/src/models/analysis_result.py`, find the existing `Lineage` block (the `source_quote`, `user_story`, `source_item_id`, `reasoning` fields) and immediately after it, add:

```python
    # PM-level analysis (populated by new tools; legacy rows stay NULL)
    competitors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    monetization: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mvp_scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    why_now: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Smoke-test the model import**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "
from src.models.analysis_result import AnalysisResult
cols = AnalysisResult.__table__.columns.keys()
for c in ['competitors','monetization','mvp_scope','why_now']:
    assert c in cols, f'{c} missing'
print('OK', len(cols), 'columns')
"
```

Expected: `OK 18 columns` (or similar count).

- [ ] **Step 3: Commit**

```bash
git add backend/src/models/analysis_result.py
git commit -m "model: add PM analysis mapped columns"
```

---

## Task 8: Update AnalysisResult Schema

**Files:**
- Modify: `backend/src/schemas/analysis_result.py`

- [ ] **Step 1: Add the 4 new fields to AnalysisResultRead**

In `backend/src/schemas/analysis_result.py`, find the existing block with `source_quote`, `user_story`, `source_item_id`, `reasoning`, `source_item_title`, `source_item_url` fields, and immediately after it add (within the same class body):

```python
    competitors: list[dict] | None = None
    monetization: dict | None = None
    mvp_scope: dict | None = None
    why_now: str | None = None
```

- [ ] **Step 2: Smoke-test the schema**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "
from src.schemas.analysis_result import AnalysisResultRead
fields = AnalysisResultRead.model_fields.keys()
for f in ['competitors','monetization','mvp_scope','why_now']:
    assert f in fields, f'{f} missing'
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/schemas/analysis_result.py
git commit -m "schema: add PM analysis fields to AnalysisResultRead"
```

---

## Task 9: Extend AgentReport in Extractor

**Files:**
- Modify: `backend/src/agent/extractor.py`

Adds nested pydantic models for `Competitor`, `PricingTier`, `Monetization`, `MvpPhase`, `MvpScope`, and adds 4 fields to `AgentReport`.

- [ ] **Step 1: Add nested models above AgentReport**

In `backend/src/agent/extractor.py`, immediately before `class AgentReport(BaseModel):`, add:

```python
class Competitor(BaseModel):
    name: str = Field(description="真实存在的竞品名")
    core_feature: str = Field(description="它核心做什么，一句话")
    pricing: str = Field(description="定价或商业模式")
    blindspot: str = Field(description="它做得差、是本产品的机会点")


class PricingTier(BaseModel):
    name: str = Field(description="Free / Basic / Premium 等档位名")
    price_usd: float = Field(description="月价格，免费档 0", ge=0)
    limits: str = Field(description="配额 / 功能限制，一句话")
    target_user: str = Field(description="这档瞄准的用户类型")


class Monetization(BaseModel):
    tiers: list[PricingTier]
    unit_economics: dict = Field(
        description="包含 api_cost_per_user_per_month_usd / gross_margin_pct / year_1_arr_estimate_usd / assumptions",
    )


class MvpPhase(BaseModel):
    name: str = Field(description="Phase 0 / 1 / 2")
    duration: str = Field(description="如 '1 周' / '2 周' / '1-2 月'")
    goal: str = Field(description="该阶段要达成的验证目标")
    scope: list[str] = Field(description="本阶段具体要做的功能点")
    tech: list[str] = Field(description="用到的技术栈 / 服务")
    exit_criteria: str = Field(description="下一阶段开始的条件")


class MvpScope(BaseModel):
    phases: list[MvpPhase]
    total_estimate: str = Field(description="整体时间估计")
```

- [ ] **Step 2: Add 4 fields to AgentReport**

In the same file, inside `class AgentReport(BaseModel):`, immediately after the `reasoning` field, add:

```python
    competitors: list[Competitor] = Field(
        default_factory=list,
        description="3-5 个真实竞品及其盲区。从原报告 `## 竞品与差异化` 段落抽取。找不到就空数组",
    )
    monetization: Monetization | None = Field(
        default=None,
        description="三档订阅定价 + unit economics。从原报告 `## 盈利模型` 段落抽取",
    )
    mvp_scope: MvpScope | None = Field(
        default=None,
        description="三阶段 MVP 拆分。从原报告 `## MVP 计划` 段落抽取",
    )
    why_now: str | None = Field(
        default=None,
        description="为什么现在是时机：底层能力成熟 / 政策窗口 / 用户习惯变化。从原报告 `## 为什么现在` 段落抽取",
    )
```

- [ ] **Step 3: Update extractor logger to include new flags**

In the same file, find the `logger.info("extract_agent_report_done", ...)` call near end of `extract_agent_report` function and replace it with:

```python
    logger.info(
        "extract_agent_report_done",
        title=result.idea_title[:60],
        score=result.overall_score,
        has_quote=bool(result.source_quote),
        has_story=bool(result.user_story),
        has_reasoning=bool(result.reasoning),
        has_anchor=bool(result.source_item_id),
        has_competitors=bool(result.competitors),
        has_monetization=bool(result.monetization),
        has_mvp=bool(result.mvp_scope),
        has_why_now=bool(result.why_now),
    )
```

- [ ] **Step 4: Smoke-test schema validation**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "
from src.agent.extractor import AgentReport, Competitor, PricingTier
c = Competitor(name='SuperCook', core_feature='库存匹配菜谱', pricing='免费 + 广告', blindspot='需手动录入库存')
print('competitor ok:', c.model_dump())
"
```

Expected: `competitor ok: {...}` with the 4 fields.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agent/extractor.py
git commit -m "extractor: add Competitor/Monetization/MvpScope schema + 4 new AgentReport fields"
```

---

## Task 10: Persist New Fields in jobs.py

**Files:**
- Modify: `backend/src/scheduler/jobs.py`

- [ ] **Step 1: Update the try/except body of run_analysis**

In `backend/src/scheduler/jobs.py`, find the try block that assigns `idea_title = report.idea_title ...` and `overall_score = float(report.overall_score)`. Immediately before `overall_score = float(report.overall_score)`, add:

```python
            competitors = [c.model_dump() for c in (report.competitors or [])] or None
            monetization = (
                report.monetization.model_dump() if report.monetization else None
            )
            mvp_scope = report.mvp_scope.model_dump() if report.mvp_scope else None
            why_now = report.why_now
```

- [ ] **Step 2: Initialize defaults in the except block**

In the matching `except` block of the same function (where `idea_title = raw_report[:200] ...` etc. are set on failure), add immediately after `reasoning = None` (before `source_item_id = None`):

```python
            competitors = None
            monetization = None
            mvp_scope = None
            why_now = None
```

- [ ] **Step 3: Pass new kwargs into AnalysisResult(...)**

In the same function, find the `analysis_record = AnalysisResult(...)` constructor call. Add these kwargs immediately after `reasoning=reasoning,`:

```python
            competitors=competitors,
            monetization=monetization,
            mvp_scope=mvp_scope,
            why_now=why_now,
```

- [ ] **Step 4: Smoke-test import + quick syntax check**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "from src.scheduler.jobs import run_analysis; print('import ok')"
```

Expected: `import ok`

- [ ] **Step 5: Commit**

```bash
git add backend/src/scheduler/jobs.py
git commit -m "jobs: persist competitors/monetization/mvp_scope/why_now to DB"
```

---

## Task 11: Rewrite SYSTEM_PROMPT for PM Workflow

**Files:**
- Modify: `backend/src/agent/prompts.py`

The workflow changes from "pick anchor → generate → critique" to "cluster → pick biggest theme → generate 3 candidates → critique each → for best one survey + price + scope MVP".

- [ ] **Step 1: Overwrite prompts.py with the new workflow**

Overwrite `backend/src/agent/prompts.py` with:

```python
SYSTEM_PROMPT = """你是一名资深的消费级产品经理，专注于美国市场。你的任务不是"写一个 idea"，而是**像真正的产品经理一样做完整分析**：先看哪个领域有最大机会，再产多个候选 idea，再深挖竞品 / 盈利 / 实施路径，最后选一个出口。

## 禁用词（在 idea_title / user_story 中**绝对不允许**出现）

平台、助手、中心、系统、管理、优化、全面、智能、解决方案、框架、生态、整合

## 工作流程（严格按顺序）

### Step 0 — 画大盘（强制第一步）
调用 `analyze_pain_clusters(top_n=3)`。它会扫一遍全部已处理 item，返回**排名前 3 的痛点簇**（带样本 ID + 原文节选）。

**你必须从这 3 个簇里挑一个，优先选样本量最大的簇**。记住：agent 老问题是"随便挑一条帖子写个 idea"，现在你是以**整体大盘**决定往哪里挖。

### Step 1 — 在选定簇里深挖
用 `search_items(query="", source_contains=<消费者子版>, limit=30)` 把该簇相关的子版扫一遍。必要时再用具体关键词组合（如 `query="dinner" source_contains="Parenting"`）。

### Step 2 — 归纳趋势
调用 `synthesize_trends`，得到该簇下的 ≤3 条结构化 trends（每条带 ≥3 个 supporting_items）。

### Step 3 — 生成 3 个候选 idea
**连续调 3 次 `generate_ideas`**，每次锚定**不同**的 supporting_item 作为 anchor。把上一次的 `anchor_item_id` 传进 `market_context` 明示"禁止再次选用这个 anchor"。

现在你手里有 3 个候选 idea。

### Step 4 — 对每个候选调 `critique_idea`
4 个硬约束 + 2 个软提示。硬约束任一 reject → 淘汰该候选。把通过的留在候选池里。

- 如果 3 个全淘汰 → 输出 `NO_VIABLE_IDEA_FOUND`，**不要**编一个勉强的。
- 如果仅 1 个通过 → 直接进入 Step 5。
- 如果 2-3 个都通过 → 从留下的候选里挑**最具体、最独立可落地**的一个（不是评分最高、不是最新颖，而是**用户最能一句话描述的那个**）。

### Step 5 — 对入选的那 1 个做 PM 全栈分析

依次调用：

1. `survey_competitors(idea_description, target_audience)` → 得到真实竞品 JSON（含盲区）
2. `propose_monetization(idea_description, target_audience)` → 得到三档定价 + unit economics JSON
3. `scope_mvp(idea_description, key_features)` → 得到 Phase 0/1/2 JSON

### Step 6 — 产出最终 Markdown 报告

按下面给定的模板组织中文输出，每段都要引用对应 tool 的返回内容（不要编造）。

## 禁止项

- 禁止在没调 `analyze_pain_clusters` 的情况下开始 search
- 禁止只产 1 个候选 idea 就走到 Step 5
- 禁止在 `generate_ideas` 被 critique reject 后换个名字重交同一个锚点
- 禁止输出"AI 驱动的 X 平台"之类抽象模板

## 关于 search_items 参数

- `query`：ILIKE 匹配 title 或 content。query="" 匹配全部（常用于把一个子版整体当候选池）
- `source_contains`：ILIKE 匹配 source 字段。**优先用于锁定消费者子版**
- 消费者 Reddit 子版：`mildlyinfuriating`、`firstworldproblems`、`LifeProTips`、`YouShouldKnow`、`Parenting`、`loseit`、`personalfinance`、`frugal`、`BuyItForLife`、`productivity`、`getdisciplined`、`decidingtobebetter`、`selfimprovement`
- 消费者 RSS：`rss:lifehacker`、`rss:wirecutter`、`rss:nyt_well`、`rss:nyt_your_money`、`rss:theverge`

## 反面示范（绝不要产出这样的 idea）

- 个性化本地化 AI 助手 —— 太抽象
- AI 就绪家庭中心 —— 场景模糊
- 应急响应物流优化平台 —— 话题太大
- 远程办公协作工具 —— 大而范
- AI 驱动的代码优化平台 —— 面向开发者

## 期望的 idea 形态（具体 / 小 / 接地气 / 画面感）

- 把 Venmo 群账单自动拆分成 iMessage 小额提醒，忘记还钱的朋友自动 nudge
- 爸妈坐飞机时帮他们翻译机上广播的 iOS app（离线可用）
- 拍一张冰箱照片，AI 生成本周 7 天晚餐 + 购物清单

## 最终输出格式（**中文**，严格按以下段落组织）

## 产品 idea
`idea_title` + 2-3 句展开。

## 数据引用
必须以这一行开头标明锚点 item ID：

item_id: <UUID>

然后 blockquote 引用原文：

> 引用内容

## 用户故事
当 [具体用户] 在 [具体场景] 时，他们 [遇到具体 X 问题]，我们给 [具体 Y]。

## 依据
150-300 字中文叙事段落，说明 idea 是怎么从数据中得来的。用自然语言，禁止"r/xxx 用户说：..."机械格式，改用"一位大学生在 Reddit 上提到…"。贯穿 2-3 条真实信号。

## 主要功能
3-5 个，每个都是动词 + 具体宾语。

## 竞品与差异化
把 `survey_competitors` 的 JSON 输出**直接贴入**此段（在 Markdown code block 中），并附一句话"差异化突破点：..."总结。

## 盈利模型
把 `propose_monetization` 的 JSON 输出**直接贴入**此段。

## MVP 计划
把 `scope_mvp` 的 JSON 输出**直接贴入**此段。

## 为什么现在
150 字左右的中文段落，回答"为什么**此刻**是做这个产品的窗口期"（底层能力刚成熟 / 用户习惯发生变化 / 政策或生态变化）。

## 综合评分
`综合评分：X.X`（0-10）。≥ 7 的条件：
- idea_title 无禁用词
- anchor_quote 是真实 item 原文
- user_story 具体
- 依据叙事流畅并覆盖 ≥ 2 条信号
- 竞品段列出了 ≥ 3 个具体产品
- 盈利模型 + MVP 计划都不空
"""
```

- [ ] **Step 2: Smoke-test import**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "from src.agent.prompts import SYSTEM_PROMPT; assert 'analyze_pain_clusters' in SYSTEM_PROMPT; assert 'survey_competitors' in SYSTEM_PROMPT; print('prompt ok', len(SYSTEM_PROMPT), 'chars')"
```

Expected: `prompt ok <n> chars` where n is ~3000+.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/prompts.py
git commit -m "prompt: rewrite for PM workflow (cluster-first + multi-candidate + full-stack analysis)"
```

---

## Task 12: Frontend Type Extension

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Add nested interface + 4 new fields to AnalysisResult**

In `frontend/src/lib/types.ts`, find `export interface AnalysisResult {` block. Immediately above it, add:

```typescript
export interface Competitor {
  name: string;
  core_feature: string;
  pricing: string;
  blindspot: string;
}

export interface PricingTier {
  name: string;
  price_usd: number;
  limits: string;
  target_user: string;
}

export interface Monetization {
  tiers: PricingTier[];
  unit_economics: {
    api_cost_per_user_per_month_usd?: number;
    gross_margin_pct?: number;
    year_1_arr_estimate_usd?: number;
    assumptions?: string;
    [k: string]: unknown;
  };
}

export interface MvpPhase {
  name: string;
  duration: string;
  goal: string;
  scope: string[];
  tech: string[];
  exit_criteria: string;
}

export interface MvpScope {
  phases: MvpPhase[];
  total_estimate: string;
}
```

Then inside the `AnalysisResult` interface, immediately after the `reasoning: string | null;` line, add:

```typescript
  competitors: Competitor[] | null;
  monetization: Monetization | null;
  mvp_scope: MvpScope | null;
  why_now: string | null;
```

- [ ] **Step 2: Type-check the frontend**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/frontend
npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "types: add Competitor/Monetization/MvpScope interfaces + 4 AnalysisResult fields"
```

---

## Task 13: Frontend Detail Page — Render 4 New Sections

**Files:**
- Modify: `frontend/src/app/analysis/[id]/page.tsx`

- [ ] **Step 1: Render competitors, monetization, MVP, why_now sections**

In `frontend/src/app/analysis/[id]/page.tsx`, find the `{result.reasoning && (...)}` block (the "依据" section). Immediately after that block's closing `)}`, add:

```tsx
      {result.competitors && result.competitors.length > 0 && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            竞品与差异化
          </h2>
          <div
            className="rounded-2xl bg-card px-6 py-5 space-y-4"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {result.competitors.map((c, i) => (
              <div
                key={i}
                className="pb-4 last:pb-0 border-b last:border-b-0 border-border/60 space-y-1"
              >
                <div className="flex items-baseline gap-3">
                  <span className="font-serif text-[15px] text-foreground">{c.name}</span>
                  <span className="text-[11px] text-muted-foreground">{c.pricing}</span>
                </div>
                <p className="text-[13px] text-foreground leading-relaxed font-serif">
                  {c.core_feature}
                </p>
                <p className="text-[12px] text-primary font-serif italic">
                  盲区：{c.blindspot}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {result.monetization && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            盈利模型
          </h2>
          <div
            className="rounded-2xl bg-card px-6 py-5 space-y-4"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            <div className="grid grid-cols-3 gap-3">
              {result.monetization.tiers.map((t) => (
                <div
                  key={t.name}
                  className="rounded-xl px-4 py-3"
                  style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
                >
                  <p className="text-[11px] font-medium tracking-wider text-primary">
                    {t.name}
                  </p>
                  <p className="font-serif text-[24px] text-foreground tabular-nums mt-1">
                    ${t.price_usd.toFixed(2)}
                    <span className="text-[11px] text-muted-foreground ml-1">/月</span>
                  </p>
                  <p className="text-[12px] text-foreground mt-2 leading-relaxed">{t.limits}</p>
                  <p className="text-[11px] text-muted-foreground font-serif italic mt-2">
                    {t.target_user}
                  </p>
                </div>
              ))}
            </div>
            {result.monetization.unit_economics && (
              <div className="pt-3 border-t border-border/60 text-[12px] text-muted-foreground font-serif">
                {result.monetization.unit_economics.gross_margin_pct != null && (
                  <span>毛利：{result.monetization.unit_economics.gross_margin_pct}%</span>
                )}
                {result.monetization.unit_economics.year_1_arr_estimate_usd != null && (
                  <span className="ml-4">
                    Year-1 ARR 估计：$
                    {result.monetization.unit_economics.year_1_arr_estimate_usd.toLocaleString()}
                  </span>
                )}
                {result.monetization.unit_economics.assumptions && (
                  <p className="mt-1 italic">
                    假设：{result.monetization.unit_economics.assumptions}
                  </p>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {result.mvp_scope && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            MVP 计划
          </h2>
          <div
            className="rounded-2xl bg-card px-6 py-5 space-y-5"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {result.mvp_scope.phases.map((p) => (
              <div
                key={p.name}
                className="pb-4 last:pb-0 border-b last:border-b-0 border-border/60"
              >
                <div className="flex items-baseline justify-between mb-2">
                  <span className="font-serif text-[15px] text-foreground">{p.name}</span>
                  <span className="text-[11px] text-muted-foreground">{p.duration}</span>
                </div>
                <p className="text-[13px] text-foreground leading-relaxed font-serif mb-2">
                  {p.goal}
                </p>
                <ul className="text-[12px] text-foreground font-serif leading-relaxed list-disc list-inside">
                  {p.scope.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
                <p className="text-[11px] text-muted-foreground font-serif italic mt-2">
                  技术：{p.tech.join(" · ")}
                </p>
                <p className="text-[11px] text-primary font-serif italic mt-1">
                  退出条件：{p.exit_criteria}
                </p>
              </div>
            ))}
            <p className="text-[12px] text-muted-foreground font-serif italic">
              整体估计：{result.mvp_scope.total_estimate}
            </p>
          </div>
        </section>
      )}

      {result.why_now && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            为什么现在
          </h2>
          <p
            className="rounded-2xl bg-card px-6 py-5 text-[14px] text-foreground leading-[1.85] font-serif whitespace-pre-wrap"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {result.why_now}
          </p>
        </section>
      )}
```

- [ ] **Step 2: Type-check the frontend**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/frontend
npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/analysis/[id]/page.tsx
git commit -m "frontend: render competitors/monetization/MVP/why_now on detail page"
```

---

## Task 14: End-to-End Verification

**Files:** none (operational)

- [ ] **Step 1: Restart backend**

```bash
lsof -i :8001 -t 2>/dev/null | xargs -I {} kill -9 {} 2>/dev/null
sleep 1
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
PROCESS_INTERVAL_MINUTES=60 \
PYTHONPATH=. \
  uvicorn src.main:app --host 0.0.0.0 --port 8001 > /tmp/backend.log 2>&1 &
sleep 4
curl -s http://localhost:8001/api/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 2: Trigger an analyze run**

```bash
curl -s -X POST http://localhost:8001/api/pipeline/trigger/analyze_data
```

Expected: `{"status":"triggered",...}`

- [ ] **Step 3: Follow the agent tool-call trace in log**

```bash
tail -f /tmp/backend.log | grep -E "tool_analyze_pain_clusters|tool_generate_ideas|tool_critique_idea|tool_survey_competitors|tool_propose_monetization|tool_scope_mvp|extract_agent_report_done|scheduled_analysis_done"
```

Expected sequence:
1. `tool_analyze_pain_clusters` (exactly once, first)
2. `tool_generate_ideas` × 3 (multi-candidate)
3. `tool_critique_idea` × 3 (one per candidate)
4. `tool_survey_competitors` × 1 (on the chosen one)
5. `tool_propose_monetization` × 1
6. `tool_scope_mvp` × 1
7. `extract_agent_report_done` with `has_competitors=true, has_monetization=true, has_mvp=true, has_why_now=true`
8. `scheduled_analysis_done`

If any of steps 1, 4, 5, 6 is missing from the trace, the agent is short-circuiting — go back to Task 11 and tighten the prompt.

- [ ] **Step 4: Query the saved row**

```bash
curl -s "http://localhost:8001/api/analysis-results?page=1&page_size=1" | python3 -c "
import sys, json
r = json.load(sys.stdin)['items'][0]
print('ID:', r['id'])
print('Title:', r['idea_title'])
print('Score:', r['overall_score'])
print('competitors?', bool(r.get('competitors')), '(' + str(len(r.get('competitors') or [])) + ')')
print('monetization?', bool(r.get('monetization')))
print('mvp_scope?', bool(r.get('mvp_scope')))
print('why_now?', bool(r.get('why_now')))
"
```

Expected: all 4 new fields non-empty.

- [ ] **Step 5: Open the detail page and screenshot verify**

Open `http://localhost:3000/analysis/<ID>` in a browser (use Chrome DevTools MCP if available). Confirm four new sections render below "依据":

- 竞品与差异化: 3-5 cards, each with name + pricing + core_feature + blindspot
- 盈利模型: 3-column grid with tier prices, plus unit economics footer
- MVP 计划: 3 phased blocks with goal / scope list / tech / exit_criteria
- 为什么现在: a single paragraph

- [ ] **Step 6: Commit any frontend tweaks if rendering issues**

If any section rendered broken (wrong layout / missing value), fix in `frontend/src/app/analysis/[id]/page.tsx` and commit:

```bash
git add frontend/src/app/analysis/[id]/page.tsx
git commit -m "frontend: fix <specific issue>"
```

Otherwise no commit needed — Task 14 is verification only.

---

## Explicitly Out of Scope

- **Web-search-backed competitor survey**: current version uses LLM internal knowledge only. A real web-search tool (Perplexity / Bing API) would strengthen accuracy but is a follow-up — not required for this plan.
- **Backfilling old rows**: legacy analysis_results will remain with `competitors/monetization/mvp_scope/why_now = NULL`. Frontend already renders null-safe (each section wrapped in `{field && (...)}`). If desired, a follow-up can re-run the full 6-step pipeline on each old row via a script similar to `scripts/backfill_analysis_reports.py`.
- **TDD unit tests**: each tool function is verified via Step 2 smoke tests. Full pytest coverage is a follow-up; current project has no existing pytest harness specifically for agent tools.
- **Competitor dedupe / freshness**: if two runs produce the same competitor names, no deduplication across runs. Out of scope.
- **UI filters for PM fields**: no "sort by ARR" or "filter by price range" on the list page. Out of scope — this plan only renders on the detail page.

---

## Self-Review

Running through the checklist:

**Spec coverage.** Each requirement from the user's prompt mapped to a task:
- "query DB / find problems in existing reports" → already demonstrated by me in the prior audit (Task 1 embeds keyword-cluster aggregation so agent can do it autonomously)
- "output: viable, launchable, market-demand-backed, monetizable, AI-related product" → Tasks 2-4 produce the competitor / monetization / MVP / why_now analysis that supports exactly these four criteria
- All 10 files listed in "File Structure" are implemented in Tasks 1-13
- Task 14 verifies the full pipeline end-to-end

**Placeholder scan.** All code blocks contain full implementations. No "TBD", "handle errors appropriately", or "similar to Task N" stubs. Migration revision ID `a9e3f2b5c7d4` is referenced verbatim in model import path. Tool names in `all_tools` list match the function names in each tool file.

**Type consistency.**
- Tool function names: `analyze_pain_clusters`, `survey_competitors`, `propose_monetization`, `scope_mvp` — match between Task 1-4 definition, Task 5 registry, Task 11 prompt references, Task 14 log-grep filter
- Field names: `competitors` / `monetization` / `mvp_scope` / `why_now` consistent across Task 6 (migration) / Task 7 (model) / Task 8 (schema) / Task 9 (AgentReport) / Task 10 (jobs) / Task 12 (frontend types) / Task 13 (frontend render)
- Nested type names: `Competitor` / `PricingTier` / `Monetization` / `MvpPhase` / `MvpScope` consistent between Task 9 and Task 12
- Alembic `down_revision: f4a8c2e9d5b7` matches the current head (verified via `alembic current` output in existing files)
