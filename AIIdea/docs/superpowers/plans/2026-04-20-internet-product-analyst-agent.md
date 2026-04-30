# 互联网产品分析专家 Agent 重构计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `analyze_data` agent 从"一条消费者抱怨 → 装 app 解决"范式重构为"**并行扫三种信号（互联网产品动向 + AI 新能力 + 消费者痛点簇）→ 交叉出候选 → 每个候选都过完整的竞品+盈利+MVP 论证**"范式。产出的 idea 必须满足：可实现、可落地、有市场需求、有盈利模式、最好 AI 相关。

**Architecture:** 废弃 `synthesize_trends` / `generate_ideas` / `analyze_market` / `assess_tech_feasibility` 这 4 个旧 tool（黑盒抽象 + LLM hallucination，无实质论证力）。新增 **6 个**产品分析专家导向的 tool：`scan_hot_launches`（产品端）/ `scan_ai_capabilities`（技术端）/ `scan_pain_clusters`（需求端，消费者抱怨聚类）/ `survey_track_competitors`（竞品）/ `propose_niche_cut`（差异化）/ `audit_self_history`（自省）。保留 `search_items` / `critique_idea` / `propose_monetization` / `scope_mvp`。重写 SYSTEM_PROMPT 为 6 步并行候选工作流。

**Tech Stack:** Python 3.12 / FastAPI / LangGraph / LangChain / OpenAI gpt-4o / Alembic / SQLAlchemy async + JSONB / Next.js 16 / Tailwind v4.

---

## Context

用户的反馈："你的分析报告几乎没一个可用的产品 idea"。

**根因不是"分析深度不够"，是方向错了：**

1. 当前 agent 的数据源重心放在 Reddit 消费者子版 + 生活 RSS（lifehacker / nyt_well / wirecutter / mildlyinfuriating / personalfinance 等）
2. 当前 agent 的范式是"**一个消费者抱怨 → 发明一个 app 解决它**"
3. 但这套范式下产出的 idea 大量犯 **solution_fit** 错误（被困扰用户装 app 没法改变陌生人行为）或**太琐碎**（市场太小、不适合互联网产品形态）

**项目应有的样子：**

项目叫 **AI Idea Finder** → 互联网产品分析专家。它应该**三条信号并行扫**：

- **产品端（Supply）**：Product Hunt、Fazier、findly、HackerNews、GitHub Trending、producthunt-RSS —— 市场最近在做什么
- **技术端（Enabler）**：arxiv (cs.AI/cs.LG/cs.CL)、Hugging Face trending、DEV.to (ai/ml/llm)、Smol AI News、Papers with Code、HackerNoon AI —— AI 最近能做什么
- **需求端（Demand）**：Reddit 消费者子版（`r/mildlyinfuriating` / `r/Parenting` / `r/personalfinance` / `r/LifeProTips` 等）+ 生活 RSS（Lifehacker / NYT Well / Wirecutter）—— 真实用户在烦什么

**三条信号交叉** → 3 个候选 idea → 每个候选必须过"竞品调研 → 差异化切入 → critique → 盈利模型 → MVP 计划"全套论证，才能进入最终输出。这保证产出 idea 同时满足**实际 / 可实现 / 有市场 / 有盈利模式 / 可落地**。

消费者痛点**不被当作唯一 anchor**（上一版的问题），而是作为**候选机会之一**，且必须同样通过所有论证门槛 —— 特别是 `critique_idea` 的 solution_fit 硬约束（防止"装 app 解决陌生人行为"那类方向错位）。

---

## File Structure

### New tool files (6)
- `backend/src/agent/tools/scan_hot_launches.py` — **产品端**，聚合近 N 天 Product Hunt / Fazier / HN / findly 新上线产品，按赛道直方图输出
- `backend/src/agent/tools/scan_ai_capabilities.py` — **技术端**，聚合近 N 天 arxiv / HuggingFace / DEV.to AI / Smol AI News 里出现的新 AI 能力，LLM 归纳
- `backend/src/agent/tools/scan_pain_clusters.py` — **需求端**，聚合近 N 天 Reddit 消费者子版 + 生活 RSS 里的高频痛点簇，LLM 归纳成 3-5 个"真实用户群体 + 高频烦恼"
- `backend/src/agent/tools/survey_track_competitors.py` — 给定赛道名，从 DB 里拉该赛道出现过的产品 + 其描述，LLM 整理成竞品表
- `backend/src/agent/tools/propose_niche_cut.py` — 给定赛道 + 竞品 + AI 能力 (+ 可选的消费者痛点)，LLM 产出 5 个差异化切入点
- `backend/src/agent/tools/audit_self_history.py` — 查 `analysis_results` 表近 N 条，LLM 归纳"agent 过去犯什么错"，作为本次运行的反面规避清单

### New migration (1)
- `backend/alembic/versions/b8f2e5a4c3d9_track_niche_capability.py` — 加 `track TEXT` / `ai_capability_used TEXT` / `niche_cut TEXT`

### Modified files
- `backend/src/agent/tools/__init__.py` — 废弃 5 个旧 tool，注册 5 个新 tool，保留 `search_items` / `critique_idea` / `propose_monetization` / `scope_mvp`
- `backend/src/agent/prompts.py` — 全重写，6 步新工作流
- `backend/src/agent/extractor.py` — 给 `AgentReport` 加 `track` / `ai_capability_used` / `niche_cut` 字段
- `backend/src/models/analysis_result.py` — 加 3 列
- `backend/src/schemas/analysis_result.py` — 加 3 字段
- `backend/src/scheduler/jobs.py` — 持久化 3 字段
- `frontend/src/lib/types.ts` — `AnalysisResult` 加 3 字段
- `frontend/src/app/analysis/[id]/page.tsx` — 加"赛道 / AI 新能力 / 差异化切入点"三个卡片

### Deprecated tools (保留文件，只是从 all_tools 移除)
- `backend/src/agent/tools/analyze_pain_clusters.py`
- `backend/src/agent/tools/trend_synthesizer.py`
- `backend/src/agent/tools/idea_generator.py`
- `backend/src/agent/tools/market_analysis.py`
- `backend/src/agent/tools/tech_feasibility.py`

（前三个是上一版加的 / 已经在的；后两个是项目初期就有的 hallucinate-heavy 工具。保留文件不删是为了留历史，但从 all_tools 移除它们就不再被 agent 使用。）

**假设：上一版 `2026-04-20-agent-product-analyst.md` 里的 Task 1-5（`analyze_pain_clusters` / `survey_competitors` / `propose_monetization` / `scope_mvp` / 新 tool 注册）**未执行**。本计划直接基于当前 main 分支状态（tools 目录只有 `critique_idea` / `idea_generator` / `market_analysis` / `search_items` / `tech_feasibility` / `trend_synthesizer`）。若上一版部分已执行，实施本计划时跳过已建好的文件。

---

## Task 1: `scan_hot_launches` Tool

**Files:**
- Create: `backend/src/agent/tools/scan_hot_launches.py`

聚合近 N 天从 Product Hunt / Fazier / findly / HN / rss:producthunt 这些"新产品发布"源采集到的 item。按 category / tag 做直方图，返回 top 5 赛道 + 每赛道 5 条样本（产品名 + 简介）。

**用意：** 让 agent 在开始分析前先看到"最近市场在哪个方向活跃"，而不是随便挑一条 Reddit 抱怨。

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/scan_hot_launches.py`:

```python
"""Aggregate recently-launched internet products from Product Hunt / Fazier /
findly / HackerNews / producthunt-RSS. Returns a histogram of tracks (by
simple keyword bucketing) plus sample products per track, so the agent can
see which directions are actually active in the market this month."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from langchain_core.tools import tool
from sqlalchemy import or_, select

from src.db import get_async_session_factory
from src.models.source_item import SourceItem

logger = structlog.get_logger()


_LAUNCH_SOURCES = (
    "hackernews",
    "producthunt",
    "rss:producthunt",
    "html:fazier",
    "html:findly",
    "rss:shipstry",
    "rss:launch_cab",
    "rss:neeed",
    "rss:betalist",
)

# Coarse keyword → track bucket. Hits on title or content.
_TRACK_BUCKETS: dict[str, list[str]] = {
    "AI coding / dev tools": ["copilot", "code", "ide", "debug", "dev tool", "sdk"],
    "AI agents / automation": ["agent", "autonomous", "automate", "workflow"],
    "AI content / writing": ["writer", "content", "blog", "seo", "copy", "marketing"],
    "AI image / video / creative": ["image", "video", "generate", "design", "avatar", "art"],
    "AI voice / audio": ["voice", "audio", "tts", "speech", "podcast", "transcri"],
    "AI data / analytics": ["analytics", "dashboard", "chart", "bi ", "data viz"],
    "AI sales / growth": ["sales", "lead", "outreach", "crm", "email"],
    "AI customer support": ["support", "chatbot", "helpdesk", "knowledge base"],
    "AI HR / recruiting": ["resume", "hiring", "interview", "recruit"],
    "AI finance / accounting": ["invoice", "accounting", "bookkeep", "tax"],
    "AI legal / compliance": ["legal", "contract", "compliance", "gdpr"],
    "AI education / tutor": ["tutor", "learn", "course", "student", "education"],
    "AI health / fitness": ["health", "fitness", "wellness", "meditation"],
    "AI productivity / pkm": ["note", "notion", "productivity", "pkm", "second brain"],
    "No-code / builder": ["no-code", "nocode", "builder", "maker"],
    "Browser / extension": ["extension", "chrome", "browser"],
    "Developer infra": ["database", "cloud", "deploy", "infrastructure", "kubernetes"],
}


@tool
async def scan_hot_launches(days: int = 30, top_tracks: int = 5) -> str:
    """Aggregate internet products launched in the last `days` days across Product Hunt / Fazier / findly / HN / producthunt-RSS. Returns the top_tracks buckets by count, each with 5 sample products (title + source + excerpt). Call this FIRST in every analyze run so you know what's actually hot, not what the corpus accidentally surfaces."""
    logger.info("tool_scan_hot_launches", days=days, top_tracks=top_tracks)

    since = datetime.now(timezone.utc) - timedelta(days=days)
    factory = get_async_session_factory()
    async with factory() as session:
        stmt = (
            select(SourceItem)
            .where(SourceItem.source.in_(_LAUNCH_SOURCES))
            .where(SourceItem.collected_at >= since)
            .order_by(SourceItem.score.desc().nullslast())
            .limit(500)
        )
        items = (await session.execute(stmt)).scalars().all()

    if not items:
        return "(No launch items found in the last N days. Increase `days` or wait for more data.)"

    bucket_hits: dict[str, list[SourceItem]] = {k: [] for k in _TRACK_BUCKETS}
    bucket_hits["_其他"] = []
    for it in items:
        hay = f"{it.title} {it.content or ''}".lower()
        placed = False
        for bucket, keywords in _TRACK_BUCKETS.items():
            if any(kw in hay for kw in keywords):
                bucket_hits[bucket].append(it)
                placed = True
                break
        if not placed:
            bucket_hits["_其他"].append(it)

    ranked = sorted(
        ((name, hits) for name, hits in bucket_hits.items() if hits and name != "_其他"),
        key=lambda x: len(x[1]),
        reverse=True,
    )

    lines: list[str] = [f"# 近 {days} 天互联网产品发布的赛道分布\n"]
    for name, hits in ranked[:top_tracks]:
        lines.append(f"## {name}（{len(hits)} 条新品）")
        for it in hits[:5]:
            excerpt = (it.content or "").replace("\n", " ")[:120]
            lines.append(f"- [{it.source}] {it.title[:80]}")
            lines.append(f"  ID: {it.id}")
            lines.append(f"  摘要: {excerpt}")
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
from src.agent.tools.scan_hot_launches import scan_hot_launches
print(asyncio.run(scan_hot_launches.ainvoke({'days': 30, 'top_tracks': 5})))
"
```

Expected: 5 track headings (e.g. "AI coding / dev tools") with counts, each followed by 5 bullet lines showing product titles.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/scan_hot_launches.py
git commit -m "feat(agent): add scan_hot_launches tool for internet product track histogram"
```

---

## Task 2: `scan_ai_capabilities` Tool

**Files:**
- Create: `backend/src/agent/tools/scan_ai_capabilities.py`

聚合近 N 天 arxiv (cs.AI/cs.LG/cs.CL) + HuggingFace trending + DEV.to (ai) + Smol AI News + HackerNoon AI 的 item，喂给 LLM 归纳出"最近 AI 新能力清单"。

**用意：** 让 agent 的 idea 能明确说"用到了 XX 新能力"，而不是笼统 "AI 驱动的 X"。

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/scan_ai_capabilities.py`:

```python
"""Aggregate recent AI research / release / newsletter signals and ask an
LLM to extract 'what NEW things can AI do now that it couldn't six months
ago'. Returns a list of concrete capabilities with example citations.

Agent should use this to pair capabilities with market tracks from
scan_hot_launches — 'track X + capability Y' is where good ideas live."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from sqlalchemy import or_, select

from src.db import get_async_session_factory
from src.models.source_item import SourceItem

logger = structlog.get_logger()


_AI_SOURCES = (
    "rss:arxiv_cs_ai",
    "rss:arxiv_cs_lg",
    "rss:arxiv_cs_cl",
    "rss:devto_ai",
    "rss:devto_ml",
    "rss:devto_llm",
    "rss:smol_ai_news",
    "rss:hackernoon_ai",
    "json:huggingface_trending",
    "rss:papers_with_code",
)


_PROMPT = """下面是近期 AI 研究 / 新模型 / 技术博客的摘录。请归纳出 **5-8 个在过去 6 个月内才变得实用的 AI 新能力**（capability），每条说清：

- capability 名（尽量具体，如 "OCR 文档结构化提取到表格" 而不是 "视觉 AI"）
- 它新在哪里（之前做不到或做不好的点）
- 最适合用在什么互联网产品场景
- 引用一个具体 item 的 ID + 一句话依据

## 输出（严格 JSON，不要 Markdown 代码块）

[
  {{
    "capability": "...",
    "novelty": "...",
    "product_scenario": "...",
    "evidence_item_id": "...",
    "evidence_quote": "..."
  }}
]

## 原始语料

{corpus}
"""


@tool
async def scan_ai_capabilities(days: int = 30, sample_size: int = 40) -> str:
    """Survey recent AI research / model releases / AI newsletters from the last `days` days and extract a list of concrete NEW capabilities (each with a short 'what's new' + 'product scenario' + evidence citation). Returns JSON array. Pair results with scan_hot_launches tracks to find opportunity matrices."""
    logger.info("tool_scan_ai_capabilities", days=days, sample_size=sample_size)

    since = datetime.now(timezone.utc) - timedelta(days=days)
    factory = get_async_session_factory()
    async with factory() as session:
        stmt = (
            select(SourceItem)
            .where(SourceItem.source.in_(_AI_SOURCES))
            .where(SourceItem.collected_at >= since)
            .order_by(SourceItem.score.desc().nullslast())
            .limit(sample_size)
        )
        items = (await session.execute(stmt)).scalars().all()

    if not items:
        return "[]  // no recent AI items"

    corpus_parts: list[str] = []
    for it in items:
        excerpt = (it.content or "").replace("\n", " ")[:240]
        corpus_parts.append(f"ID: {it.id}\n[{it.source}] {it.title[:100]}\n摘要: {excerpt}\n")
    corpus = "\n".join(corpus_parts)

    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
    resp = await llm.ainvoke(_PROMPT.format(corpus=corpus))
    return resp.content
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
  PYTHONPATH=. \
  python -c "
import asyncio
from src.agent.tools.scan_ai_capabilities import scan_ai_capabilities
print(asyncio.run(scan_ai_capabilities.ainvoke({'days': 30, 'sample_size': 30})))
"
```

Expected: JSON array with 5-8 entries, each has capability / novelty / product_scenario / evidence_item_id / evidence_quote.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/scan_ai_capabilities.py
git commit -m "feat(agent): add scan_ai_capabilities tool for new AI capability inventory"
```

---

## Task 3: `survey_track_competitors` Tool

**Files:**
- Create: `backend/src/agent/tools/survey_track_competitors.py`

给定一个赛道名（如 "AI sales email"），查 DB 里所有已经出现过的该赛道产品（限制在 launch 源），按产品名去重，返回竞品清单。

**用意：** 与上一版的 `survey_competitors`（LLM 内部知识）不同，这个是 **从本仓库实际采集到的 Product Hunt / Fazier / HN 数据里找**，更"此刻"更新鲜，而且能引用到具体 item。

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/survey_track_competitors.py`:

```python
"""Survey competitors in a given product track using our own Product Hunt /
Fazier / HN / findly item pool. Unlike LLM-internal-knowledge surveys,
this grounds output in actual recently-collected launch signals and can
cite item IDs.
"""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from sqlalchemy import or_, select

from src.db import get_async_session_factory
from src.models.source_item import SourceItem

logger = structlog.get_logger()


_LAUNCH_SOURCES = (
    "hackernews",
    "producthunt",
    "rss:producthunt",
    "html:fazier",
    "html:findly",
    "rss:shipstry",
    "rss:launch_cab",
    "rss:neeed",
    "rss:betalist",
)


_PROMPT = """下面是某赛道的近期互联网产品清单。按产品名去重，整理出 5-8 个有代表性的竞品。每条包含：

- name：产品名
- core_feature：一句话它核心做什么
- differentiator：它宣称的差异点（从 content 里读出）
- blindspot：它明显还没做好的地方，是我们可切入的机会

## 输出（严格 JSON，无 Markdown 代码块）

[
  {{"name": "...", "core_feature": "...", "differentiator": "...", "blindspot": "...", "evidence_item_id": "..."}}
]

## 赛道名

{track_name}

## 原始产品清单

{corpus}
"""


@tool
async def survey_track_competitors(track_keywords: str, limit: int = 40) -> str:
    """Pull recent launch items matching track_keywords (space-separated OR'd, ILIKE on title+content) from our Product Hunt / Fazier / HN / findly pool. Feeds them to an LLM that returns 5-8 representative competitors with core_feature / differentiator / blindspot / evidence_item_id. Use this BEFORE designing a niche cut."""
    logger.info("tool_survey_track_competitors", track_keywords=track_keywords, limit=limit)

    kws = [k.strip() for k in track_keywords.split() if k.strip()]
    if not kws:
        return "[]  // empty track_keywords"

    factory = get_async_session_factory()
    async with factory() as session:
        conditions = []
        for kw in kws:
            conditions.append(SourceItem.title.ilike(f"%{kw}%"))
            conditions.append(SourceItem.content.ilike(f"%{kw}%"))
        stmt = (
            select(SourceItem)
            .where(SourceItem.source.in_(_LAUNCH_SOURCES))
            .where(or_(*conditions))
            .order_by(SourceItem.score.desc().nullslast())
            .limit(limit)
        )
        items = (await session.execute(stmt)).scalars().all()

    if not items:
        return f"[]  // no launch items match track_keywords={track_keywords!r}"

    corpus_parts: list[str] = []
    for it in items:
        excerpt = (it.content or "").replace("\n", " ")[:200]
        corpus_parts.append(f"ID: {it.id}\n[{it.source}] {it.title[:100]}\n摘要: {excerpt}\n")
    corpus = "\n".join(corpus_parts)

    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
    resp = await llm.ainvoke(_PROMPT.format(track_name=track_keywords, corpus=corpus))
    return resp.content
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
  PYTHONPATH=. \
  python -c "
import asyncio
from src.agent.tools.survey_track_competitors import survey_track_competitors
print(asyncio.run(survey_track_competitors.ainvoke({'track_keywords': 'AI agent automation'})))
"
```

Expected: JSON array with competitor entries, each with evidence_item_id pointing to real UUIDs in DB.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/survey_track_competitors.py
git commit -m "feat(agent): add survey_track_competitors tool backed by launch-item pool"
```

---

## Task 4: `propose_niche_cut` Tool

**Files:**
- Create: `backend/src/agent/tools/propose_niche_cut.py`

给定 `track + competitors_json + ai_capability`，LLM 产出 5 个差异化切入点（具体 niche + target user + one-sentence pitch），agent 从里面挑 1 个做 idea。

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/propose_niche_cut.py`:

```python
"""Given a track name, its surveyed competitors, and a specific new AI
capability, produce 5 candidate niche cuts — each a concrete, small, non-
obvious wedge where an AI-first product could win. The agent picks one
and turns it into the final idea.

This replaces the old 'generate_ideas' tool which hallucinated ideas from
an abstracted trend blob. This version is anchored on (1) real competitor
gaps and (2) a specific AI capability that enables a new UX."""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


_PROMPT = """你是资深消费互联网产品经理。给定：

- 赛道：{track}
- 该赛道现有竞品 JSON：{competitors_json}
- 最近成熟的 AI 能力：{ai_capability}

产出 **5 个具体差异化切入点**（不是 5 个 idea，是 5 个"切入点" —— 每个切入点描述"对哪类用户、在什么场景、用这个新 AI 能力提供什么现有竞品没做的体验"）。

## 硬约束

- 每个切入点**必须明确引用一个现有竞品的 blindspot**，说"XX 没做好 A，我们做 B"
- 禁止抽象词：平台 / 助手 / 中心 / 系统 / 管理 / 优化 / 全面 / 智能 / 解决方案 / 框架 / 整合
- 目标用户必须是具体群体，不能是"所有人"/"企业"/"用户"
- 场景必须是具体动作（"每周对账" / "起草一封 cold email"），不能是"提高效率"这类泛词
- 每个切入点必须用到给定的 AI 能力（或其变体），不能跳出该能力范围

## 输出（严格 JSON，无 Markdown 代码块）

[
  {{
    "niche_cut_title": "一句话切入点标题，≤ 25 字",
    "target_user": "具体用户群体",
    "specific_scenario": "具体使用场景",
    "competitor_blindspot_addressed": "对标哪家竞品的哪个短板",
    "ai_capability_leverage": "这个切入点如何用到给定的 AI 能力",
    "one_sentence_pitch": "一句话产品说明"
  }}
]
"""


@tool
async def propose_niche_cut(
    track: str,
    competitors_json: str,
    ai_capability: str,
) -> str:
    """Produce 5 candidate niche-cut opportunities grounded on (track, survey_track_competitors output, a specific new AI capability from scan_ai_capabilities). Each cut names a specific user / specific scenario / which competitor blindspot it attacks / how it uses the AI capability. Agent picks 1 to develop into the final idea."""
    logger.info("tool_propose_niche_cut", track=track[:60])

    llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
    resp = await llm.ainvoke(
        _PROMPT.format(
            track=track,
            competitors_json=competitors_json,
            ai_capability=ai_capability,
        )
    )
    return resp.content
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
  PYTHONPATH=. \
  python -c "
import asyncio
from src.agent.tools.propose_niche_cut import propose_niche_cut
print(asyncio.run(propose_niche_cut.ainvoke({
  'track': 'AI sales email outreach',
  'competitors_json': '[{\"name\":\"Instantly\",\"core_feature\":\"cold email automation\",\"blindspot\":\"generic templates, no personalization beyond {{first_name}}\"}]',
  'ai_capability': 'gpt-4o 能在给定一段 LinkedIn 公开资料的情况下生成 200 字以内 hyper-personalized 邮件（通过率比模板高 3x）',
})))
"
```

Expected: JSON array with 5 niche cuts.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/propose_niche_cut.py
git commit -m "feat(agent): add propose_niche_cut tool replacing generic idea generator"
```

---

## Task 5: `audit_self_history` Tool

**Files:**
- Create: `backend/src/agent/tools/audit_self_history.py`

查 `analysis_results` 表近 N 条报告，取 `idea_title`、`user_story`、`reasoning`，问 LLM："你是一位产品总监，下面是你下属过去几周交的产品提案，总结他常犯的错误模式"。

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/audit_self_history.py`:

```python
"""Audit the agent's own past analysis reports. Dumps the last N rows of
analysis_results to an LLM and asks it to enumerate recurring failure
modes ('this agent keeps proposing XXX, which fails for YYY'). The output
is fed back into the SYSTEM_PROMPT on the next run as a 'do not repeat'
constraint list — cheap metalearning."""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from sqlalchemy import select

from src.db import get_async_session_factory
from src.models.analysis_result import AnalysisResult

logger = structlog.get_logger()


_PROMPT = """你是产品总监。下面是你的下属过去几周提交的产品 idea 报告清单。请归纳出**他反复犯的错误模式**，列成 5-8 条规避清单，供他本次新提案时自查。

## 判断错误的维度

- idea 抽象 / 空心（含"平台/助手/中心"等词）
- 目标用户泛（"所有人" / "中小企业"）
- 方案与痛点错位（被困扰用户装 app 改不了陌生人行为）
- 没有明确 AI 新能力作为支点
- 撞大厂阵地
- 重复同一赛道（如一直在"文档扫描"打转）
- 场景不具体
- 完全抄现有产品且没有差异化

## 输出（严格 JSON，无 Markdown 代码块）

{{
  "failure_patterns": [
    "- 反复提出 XX 型 idea（示例标题：...）。问题：YY。本次避免。",
    ...
  ],
  "banned_idea_titles": ["本次禁止再提的旧 idea 标题列表（用于 dedup）"]
}}

## 历史报告

{history}
"""


@tool
async def audit_self_history(limit: int = 15) -> str:
    """Read the last `limit` rows of analysis_results and have an LLM enumerate recurring failure patterns + a dedup list of idea_title strings to avoid. Call this FIRST in every analyze run so the agent doesn't keep repeating the same mistakes."""
    logger.info("tool_audit_self_history", limit=limit)

    factory = get_async_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(AnalysisResult)
                .order_by(AnalysisResult.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()

    if not rows:
        return '{"failure_patterns": [], "banned_idea_titles": []}'

    history_parts: list[str] = []
    for r in rows:
        history_parts.append(
            f"- {r.idea_title} (score={r.overall_score})\n"
            f"  user_story: {r.user_story or '(无)'}\n"
            f"  reasoning: {(r.reasoning or '(无)')[:300]}"
        )
    history = "\n\n".join(history_parts)

    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    resp = await llm.ainvoke(_PROMPT.format(history=history))
    return resp.content
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
  PYTHONPATH=. \
  python -c "
import asyncio
from src.agent.tools.audit_self_history import audit_self_history
print(asyncio.run(audit_self_history.ainvoke({'limit': 15})))
"
```

Expected: JSON with `failure_patterns` array (5-8 bullet points) and `banned_idea_titles` array.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/audit_self_history.py
git commit -m "feat(agent): add audit_self_history tool for meta-learning from past reports"
```

---

## Task 5b: `scan_pain_clusters` Tool（需求端）

**Files:**
- Create: `backend/src/agent/tools/scan_pain_clusters.py`

聚合近 N 天 Reddit 消费者子版 + 生活 RSS 的 item，按痛点簇分组，LLM 归纳"真实用户群体 + 高频烦恼"，返回 3-5 个候选痛点簇。

**用意：** 保留消费者端信号作为候选 idea 来源之一，与 scan_hot_launches（产品端）、scan_ai_capabilities（技术端）并列。消费者痛点簇也能进入 Step 3 的交叉机会矩阵，但必须过完整的竞品+盈利+MVP 门槛，**不会像旧流程那样直接变成 idea**。

- [ ] **Step 1: Create the tool file**

Write to `backend/src/agent/tools/scan_pain_clusters.py`:

```python
"""Aggregate real consumer complaints from Reddit pain subs + lifestyle
RSS in the last N days. Cluster them into 3-5 pain themes (by keyword
bucketing + LLM summarization). Returns candidate consumer pain clusters
as one of the three input streams feeding the agent's opportunity matrix.

This is *demand-side* signal — not a direct idea anchor. Downstream
`critique_idea`'s solution_fit guardrail still filters out pain points
whose solution requires changing non-users' behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from sqlalchemy import or_, select

from src.db import get_async_session_factory
from src.models.source_item import SourceItem

logger = structlog.get_logger()


_CONSUMER_SOURCES = (
    "reddit:mildlyinfuriating",
    "reddit:firstworldproblems",
    "reddit:LifeProTips",
    "reddit:YouShouldKnow",
    "reddit:Parenting",
    "reddit:loseit",
    "reddit:personalfinance",
    "reddit:frugal",
    "reddit:BuyItForLife",
    "reddit:productivity",
    "reddit:getdisciplined",
    "reddit:decidingtobebetter",
    "reddit:selfimprovement",
    "rss:lifehacker",
    "rss:wirecutter",
    "rss:nyt_well",
    "rss:nyt_your_money",
)


_PROMPT = """下面是近期美国消费者 Reddit + 生活 RSS 抓到的抱怨/痛点语料。请聚类出 **3-5 个最突出的痛点簇**，每簇包含：

- cluster_name：痛点簇名（一句话描述这一类痛点）
- target_user：具体的用户群体（不是"所有人"）
- frequency_signal：粗略说明这一簇有多少条支持（"XX 子版里至少 10 条抱怨类似问题"）
- evidence：2-3 条代表性原文 item_id + 摘录
- is_software_solvable：判断这个痛点本身能否用软件/互联网产品解决（如果需要改变陌生人行为 / 物理世界问题 / 规则改动，标 "no"；如果是信息整理 / 自动化 / 推荐 / 教练 / 沟通起草类，标 "yes"）

## 输出（严格 JSON，无 Markdown 代码块）

[
  {{
    "cluster_name": "...",
    "target_user": "...",
    "frequency_signal": "...",
    "evidence": [
      {{"item_id": "...", "quote": "..."}},
      {{"item_id": "...", "quote": "..."}}
    ],
    "is_software_solvable": "yes 或 no"
  }}
]

## 原始语料

{corpus}
"""


@tool
async def scan_pain_clusters(days: int = 30, sample_size: int = 60) -> str:
    """Survey recent consumer complaints from Reddit pain subs + lifestyle RSS in the last `days` days. Returns 3-5 pain clusters as JSON, each with target_user, frequency_signal, evidence item_ids + quotes, and is_software_solvable flag. Agent should use `is_software_solvable=yes` clusters as demand-side opportunity candidates alongside scan_hot_launches (supply side) and scan_ai_capabilities (tech side)."""
    logger.info("tool_scan_pain_clusters", days=days, sample_size=sample_size)

    since = datetime.now(timezone.utc) - timedelta(days=days)
    factory = get_async_session_factory()
    async with factory() as session:
        stmt = (
            select(SourceItem)
            .where(SourceItem.source.in_(_CONSUMER_SOURCES))
            .where(SourceItem.collected_at >= since)
            .order_by(SourceItem.score.desc().nullslast())
            .limit(sample_size)
        )
        items = (await session.execute(stmt)).scalars().all()

    if not items:
        return "[]  // no recent consumer items"

    corpus_parts: list[str] = []
    for it in items:
        excerpt = (it.content or "").replace("\n", " ")[:200]
        corpus_parts.append(f"ID: {it.id}\n[{it.source}] {it.title[:100]}\n摘录: {excerpt}\n")
    corpus = "\n".join(corpus_parts)

    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    resp = await llm.ainvoke(_PROMPT.format(corpus=corpus))
    return resp.content
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
OPENAI_API_KEY="$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)" \
  PYTHONPATH=. \
  python -c "
import asyncio
from src.agent.tools.scan_pain_clusters import scan_pain_clusters
print(asyncio.run(scan_pain_clusters.ainvoke({'days': 30, 'sample_size': 40})))
"
```

Expected: JSON array of 3-5 clusters, each with target_user / frequency_signal / evidence / is_software_solvable.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/scan_pain_clusters.py
git commit -m "feat(agent): add scan_pain_clusters tool (demand-side signal)"
```

---

## Task 6: Register New Tools, Deprecate Old

**Files:**
- Modify: `backend/src/agent/tools/__init__.py`

保留 `search_items` / `critique_idea`。加入 5 个新 tool。废弃 `trend_synthesizer` / `idea_generator` / `market_analysis` / `tech_feasibility`。另加 `propose_monetization` 和 `scope_mvp`（如果前一版未创建则需先创建，但本计划**假设它们未存在**，在 Task 7 / Task 8 新建）。

- [ ] **Step 1: Check what exists already**

```bash
ls /Users/doorlaps/workspace/claude/phantom/AIIdea/backend/src/agent/tools/
```

Observe which files are present. If `propose_monetization.py` / `scope_mvp.py` already exist from a prior plan execution, skip creating them (Task 7, Task 8). Otherwise, proceed with Task 7, Task 8 before this task.

- [ ] **Step 2: Rewrite __init__.py**

Overwrite `backend/src/agent/tools/__init__.py` with:

```python
# Active tools — roughly in call order of the new parallel-scan workflow.
from src.agent.tools.audit_self_history import audit_self_history
from src.agent.tools.scan_hot_launches import scan_hot_launches
from src.agent.tools.scan_ai_capabilities import scan_ai_capabilities
from src.agent.tools.scan_pain_clusters import scan_pain_clusters
from src.agent.tools.survey_track_competitors import survey_track_competitors
from src.agent.tools.propose_niche_cut import propose_niche_cut
from src.agent.tools.critique_idea import critique_idea
from src.agent.tools.propose_monetization import propose_monetization
from src.agent.tools.scope_mvp import scope_mvp
from src.agent.tools.search_items import search_items

all_tools = [
    # Step 0: meta-learning from past reports
    audit_self_history,
    # Step 1 parallel: scan three input streams (supply + tech + demand)
    scan_hot_launches,
    scan_ai_capabilities,
    scan_pain_clusters,
    # Step 2: competitor survey on chosen track
    survey_track_competitors,
    # Step 3: design niche cut
    propose_niche_cut,
    # Step 4: reality check
    critique_idea,
    # Step 5 (on chosen idea): PM full stack
    propose_monetization,
    scope_mvp,
    # Supplementary: ad-hoc DB queries
    search_items,
]

# Explicitly deprecated tools (still importable for migration ease but not
# wired into the agent):
#   - src.agent.tools.trend_synthesizer.synthesize_trends  (黑盒 abstraction)
#   - src.agent.tools.idea_generator.generate_ideas       (替换为 propose_niche_cut)
#   - src.agent.tools.market_analysis.analyze_market      (hallucination)
#   - src.agent.tools.tech_feasibility.assess_tech_feasibility (hallucination)
```

- [ ] **Step 3: Smoke-test import**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "from src.agent.tools import all_tools; print(len(all_tools), [t.name for t in all_tools])"
```

Expected: `10 ['audit_self_history', 'scan_hot_launches', 'scan_ai_capabilities', 'scan_pain_clusters', 'survey_track_competitors', 'propose_niche_cut', 'critique_idea', 'propose_monetization', 'scope_mvp', 'search_items']`

- [ ] **Step 4: Commit**

```bash
git add backend/src/agent/tools/__init__.py
git commit -m "refactor(agent): wire new 9-tool set, deprecate 4 old hallucination-heavy tools"
```

---

## Task 7: `propose_monetization` Tool (if not already present)

**Files:**
- Create: `backend/src/agent/tools/propose_monetization.py`

Skip this task if the file already exists. Otherwise, create.

- [ ] **Step 1: Check existence**

```bash
ls /Users/doorlaps/workspace/claude/phantom/AIIdea/backend/src/agent/tools/propose_monetization.py 2>/dev/null && echo "EXISTS - skip Task 7" || echo "MISSING - continue"
```

- [ ] **Step 2 (if missing): Create the file**

Write to `backend/src/agent/tools/propose_monetization.py`:

```python
"""Design a three-tier pricing model with unit economics for a given idea."""

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

1. 三档订阅：Free（获客）/ Basic（主力付费）/ Premium（高 ARPU）。每档有清晰区分，不要只是"功能更多"。
2. 估算 unit economics：
   - 每用户月 API / 服务器成本（LLM 参考：gpt-4o-mini ≈ $0.15/1M input + $0.60/1M output；GPT-4o Vision ≈ $2.50/1M input + $10/1M output）
   - 毛利百分比
   - 100K MAU 下的 Year 1 ARR 估计（默认 10% 转化率可调）

## 输出（严格 JSON，无 Markdown 包裹）

{{
  "tiers": [
    {{"name": "Free", "price_usd": 0, "limits": "...", "target_user": "..."}},
    {{"name": "Basic", "price_usd": 6.99, "limits": "...", "target_user": "..."}},
    {{"name": "Premium", "price_usd": 12.99, "limits": "...", "target_user": "..."}}
  ],
  "unit_economics": {{
    "api_cost_per_user_per_month_usd": 0.08,
    "gross_margin_pct": 98,
    "year_1_arr_estimate_usd": 70000,
    "assumptions": "..."
  }}
}}
"""


@tool
async def propose_monetization(idea_description: str, target_audience: str = "") -> str:
    """Design a three-tier freemium pricing model (Free/Basic/Premium) with unit economics for a product idea. Returns JSON with tiers + unit_economics."""
    logger.info("tool_propose_monetization", desc=idea_description[:80])
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    resp = await llm.ainvoke(
        _PROMPT.format(
            idea_description=idea_description,
            target_audience=target_audience or "(未指定)",
        )
    )
    return resp.content
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/propose_monetization.py
git commit -m "feat(agent): add propose_monetization tool"
```

---

## Task 8: `scope_mvp` Tool (if not already present)

**Files:**
- Create: `backend/src/agent/tools/scope_mvp.py`

Same pattern as Task 7.

- [ ] **Step 1: Check existence**

```bash
ls /Users/doorlaps/workspace/claude/phantom/AIIdea/backend/src/agent/tools/scope_mvp.py 2>/dev/null && echo "EXISTS - skip Task 8" || echo "MISSING - continue"
```

- [ ] **Step 2 (if missing): Create the file**

Write to `backend/src/agent/tools/scope_mvp.py`:

```python
"""Break a product idea into 3 phased MVP increments (Phase 0 / 1 / 2).
Each phase is a 1-4 week chunk with concrete scope, tech stack, and exit
criteria."""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


_PROMPT = """你是技术产品负责人。为下面的产品 idea 拆分一个 2-4 周可达 MVP 的三阶段计划。

## 输入

产品 idea: {idea_description}
主要功能: {key_features}

## 约束

- 2-3 人小团队
- 演进路线：Web 原型 → 完整 Web MVP → React Native / iOS app（若适合）
- 允许使用现成服务：Next.js / Supabase / Stripe / 各家 LLM API / Cloudflare / Vercel
- 不引入硬件、不自建基础设施
- 每一期都能独立跑、能让 5 个真实用户试用

## 输出（严格 JSON，无 Markdown 包裹）

{{
  "phases": [
    {{"name": "Phase 0", "duration": "1 周", "goal": "...", "scope": ["..."], "tech": ["..."], "exit_criteria": "..."}},
    {{"name": "Phase 1", "duration": "2 周", "goal": "...", "scope": ["..."], "tech": ["..."], "exit_criteria": "..."}},
    {{"name": "Phase 2", "duration": "1-2 月", "goal": "...", "scope": ["..."], "tech": ["..."], "exit_criteria": "..."}}
  ],
  "total_estimate": "..."
}}
"""


@tool
async def scope_mvp(idea_description: str, key_features: str = "") -> str:
    """Break a product idea into three MVP phases (Phase 0 / 1 / 2) with scope, tech stack, and exit criteria per phase. Returns JSON with phases + total_estimate."""
    logger.info("tool_scope_mvp", desc=idea_description[:80])
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    resp = await llm.ainvoke(
        _PROMPT.format(
            idea_description=idea_description,
            key_features=key_features or "(未指定)",
        )
    )
    return resp.content
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/tools/scope_mvp.py
git commit -m "feat(agent): add scope_mvp tool"
```

---

## Task 9: Alembic Migration for track / ai_capability_used / niche_cut

**Files:**
- Create: `backend/alembic/versions/b8f2e5a4c3d9_track_niche_capability.py`

- [ ] **Step 1: Create migration**

Write to `backend/alembic/versions/b8f2e5a4c3d9_track_niche_capability.py`:

```python
"""track niche capability

Revision ID: b8f2e5a4c3d9
Revises: f4a8c2e9d5b7
Create Date: 2026-04-20 14:00:00.000000

Adds 3 text columns to capture the agent's new lineage:

- track — which market track this idea belongs to (e.g. "AI sales email")
- ai_capability_used — the specific new AI capability leveraged
- niche_cut — narrative of the differentiated angle vs existing competitors
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8f2e5a4c3d9"
down_revision: Union[str, None] = "f4a8c2e9d5b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis_results", sa.Column("track", sa.Text(), nullable=True))
    op.add_column("analysis_results", sa.Column("ai_capability_used", sa.Text(), nullable=True))
    op.add_column("analysis_results", sa.Column("niche_cut", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_results", "niche_cut")
    op.drop_column("analysis_results", "ai_capability_used")
    op.drop_column("analysis_results", "track")
```

- [ ] **Step 2: Apply migration**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
DATABASE_URL="postgresql+asyncpg://postgres:1234@localhost:5432/ai_idea_finder" \
  PYTHONPATH=. alembic upgrade head
```

Expected last line: `Running upgrade f4a8c2e9d5b7 -> b8f2e5a4c3d9, track niche capability`

- [ ] **Step 3: Verify schema**

```bash
PGPASSWORD=1234 psql -h localhost -U postgres -d ai_idea_finder -c "\d analysis_results" | grep -E "track|ai_capability|niche_cut"
```

Expected: 3 lines, one per new column.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/b8f2e5a4c3d9_track_niche_capability.py
git commit -m "db: add track/ai_capability_used/niche_cut fields"
```

---

## Task 10: Update `AnalysisResult` Model

**Files:**
- Modify: `backend/src/models/analysis_result.py`

- [ ] **Step 1: Add 3 mapped columns**

In `backend/src/models/analysis_result.py`, find the block with `source_item_id` / `reasoning` fields. Immediately after the `reasoning:` line, add:

```python
    # Market-trend lineage (new workflow)
    track: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_capability_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    niche_cut: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "
from src.models.analysis_result import AnalysisResult
cols = set(AnalysisResult.__table__.columns.keys())
for c in ['track','ai_capability_used','niche_cut']:
    assert c in cols, c
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/models/analysis_result.py
git commit -m "model: add track/ai_capability_used/niche_cut"
```

---

## Task 11: Update `AnalysisResultRead` Schema

**Files:**
- Modify: `backend/src/schemas/analysis_result.py`

- [ ] **Step 1: Add 3 fields**

In `backend/src/schemas/analysis_result.py`, inside the `AnalysisResultRead` class body, add (directly after existing `reasoning: str | None = None` or similar line):

```python
    track: str | None = None
    ai_capability_used: str | None = None
    niche_cut: str | None = None
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "
from src.schemas.analysis_result import AnalysisResultRead
for f in ['track','ai_capability_used','niche_cut']:
    assert f in AnalysisResultRead.model_fields, f
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/schemas/analysis_result.py
git commit -m "schema: add track/ai_capability_used/niche_cut to AnalysisResultRead"
```

---

## Task 12: Extend `AgentReport` in Extractor

**Files:**
- Modify: `backend/src/agent/extractor.py`

- [ ] **Step 1: Add 3 fields to AgentReport**

In `backend/src/agent/extractor.py`, inside the `class AgentReport(BaseModel):` body, directly after the `reasoning` field, add:

```python
    track: str | None = Field(
        default=None,
        description="所在赛道（来自 scan_hot_launches 的 bucket 名）。从原报告 `## 赛道` 段落抽取。没有就留空",
    )
    ai_capability_used: str | None = Field(
        default=None,
        description="所用的 AI 新能力（来自 scan_ai_capabilities 的一条 capability）。从原报告 `## AI 新能力` 段落抽取。没有就留空",
    )
    niche_cut: str | None = Field(
        default=None,
        description="差异化切入点叙事（目标用户 + 场景 + 对标 blindspot + 一句话突破点）。从原报告 `## 差异化切入点` 段落抽取。没有就留空",
    )
```

- [ ] **Step 2: Update the done log to include new flags**

In the same file, find `logger.info("extract_agent_report_done", ...)` and add three new kwargs to it:

```python
        has_track=bool(result.track),
        has_ai_capability=bool(result.ai_capability_used),
        has_niche=bool(result.niche_cut),
```

- [ ] **Step 3: Update the extract prompt to ask for these sections**

Find `_EXTRACT_PROMPT = """..."""` and append to its instructions list (before the `原始报告：` delimiter):

```
- `track` / `ai_capability_used` / `niche_cut` 分别从原报告的 `## 赛道` / `## AI 新能力` / `## 差异化切入点` 段落抽取。没有就留 null，禁止编造
```

- [ ] **Step 4: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "
from src.agent.extractor import AgentReport
for f in ['track','ai_capability_used','niche_cut']:
    assert f in AgentReport.model_fields, f
print('OK')
"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/src/agent/extractor.py
git commit -m "extractor: extract track/ai_capability_used/niche_cut from agent report"
```

---

## Task 13: Rewrite SYSTEM_PROMPT

**Files:**
- Modify: `backend/src/agent/prompts.py`

- [ ] **Step 1: Overwrite with new 6-step workflow**

Overwrite `backend/src/agent/prompts.py` with:

```python
SYSTEM_PROMPT = """你是**互联网产品分析专家**。任务是从三条并行采集的信号（产品发布 + AI 新能力 + 消费者痛点）中，找出一个**切合实际、可实现、有市场需求、有盈利模式、可落地、最好 AI 相关**的产品 idea。

**不是"找一条消费者抱怨直接变 app"**（上一版的问题）。是"**三条信号交叉 → 多个候选 → 每个候选过完整论证 → 选一个最强**"。

## 禁用词（在 idea_title / niche_cut_title / 用户故事中**绝对不允许**出现）

平台、助手、中心、系统、管理、优化、全面、智能、解决方案、框架、生态、整合

## 工作流程（严格按顺序）

### Step 0 — 自查历史（强制第一步）

调用 `audit_self_history(limit=15)`。返回你过去 15 条 idea 的失败模式总结 + 禁止重复的旧 idea 标题列表。**记在心里**，本次产出不要再犯同样错误、不要再提同一个 idea 的换皮版。

### Step 1 — 并行扫三条信号

依次（或并行）调三个扫描 tool：

- `scan_hot_launches(days=30, top_tracks=5)` — **产品端（Supply）**：近 30 天互联网产品发布的 5 个热门赛道 + 样本产品
- `scan_ai_capabilities(days=30, sample_size=40)` — **技术端（Enabler）**：5-8 个近期成熟的具体 AI 能力
- `scan_pain_clusters(days=30, sample_size=60)` — **需求端（Demand）**：3-5 个消费者真实痛点簇，每簇标了 `is_software_solvable`

**忽略 `is_software_solvable = no` 的痛点簇**（这些是"陌生人吵我"那类软件治不了的）。

### Step 2 — 交叉出 3 个候选机会

在心里把三条信号交叉，凑出 **3 个候选机会**。每个候选至少占到两条信号：

- 候选 A：某个 hot track + 某个新 AI 能力（产品端 + 技术端）
- 候选 B：某个消费者痛点（is_software_solvable=yes）+ 某个新 AI 能力（需求端 + 技术端）
- 候选 C：其它有价值的组合（可以是"这个痛点被现有 hot track 的某个竞品遗漏了"的三角）

简要写出 3 个候选的一句话描述，然后进入 Step 3。

### Step 3 — 对每个候选做竞品调研 + 差异化切入

对 3 个候选中的**每一个**依次：

1. 调 `survey_track_competitors(track_keywords="<候选关键词>")`，得到该方向的真实竞品 + blindspots
2. 调 `propose_niche_cut(track=..., competitors_json=..., ai_capability=...)`，得到 5 个差异化切入点
3. 从 5 个切入点里挑最具体、最有破坏性的 1 个
4. 调 `critique_idea` 验证基本可行性（硬约束：真 idea / 技术可行 / 法律合规 / solution_fit）

如果 3 个候选全 critique reject → 输出 `NO_VIABLE_IDEA_FOUND`，**不要硬凑**。

### Step 4 — 从通过 critique 的候选里选 1 个做深度分析

从 Step 3 通过 critique 的候选里选**最具体、最小可落地、最能用一句话描述给外婆听**的 1 个。对这个 idea 依次调：

1. `propose_monetization(idea_description, target_audience)` → 三档定价 + unit economics
2. `scope_mvp(idea_description, key_features)` → 三阶段 MVP 拆分

### Step 5 — 产出最终中文 Markdown 报告

按下面的段落模板组织。所有数据来自前 4 步的 tool 返回，**不要编造**。

## 禁止项

- 禁止跳过 Step 0 (audit_self_history)
- 禁止跳过 Step 1（三个 scan tool 必须都调）
- 禁止只产 1 个候选就进 Step 4
- 禁止产出"AI 驱动的 X 平台"、"智能 X 管理系统"这类空心标题
- 禁止不引用任何 AI 新能力（没有 `ai_capability_used` 就不是本 agent 该产出的 idea）
- 禁止选 `is_software_solvable=no` 的消费者痛点作为候选基础

## 关于 search_items

本版 agent 把 search_items 作为 **辅助 tool**：如果 Step 3 挑好 niche cut 后想验证"目标用户真的有这个痛点"，可以去消费者子版（`source_contains='Parenting'` 等）查 3-5 条佐证引用，把它们融进"依据"段落。不作为 idea 锚点。

## 最终输出格式（**中文**，严格按以下段落组织）

## 产品 idea
`idea_title` + 2-3 句展开。

## 赛道
一句话说明该 idea 所属赛道（照抄 Step 1 的 bucket 名）。

## AI 新能力
一句话说明该 idea 用到了 Step 2 里的哪个具体 AI 新能力。

## 差异化切入点
把 `propose_niche_cut` 选中的那条切入点 JSON **直接贴入**（在 code block 中），并附一句话中文摘要：
- 对标 [竞品名] 的 [blindspot]
- 我们做 [差异点]

## 数据引用
从 `scan_hot_launches` / `survey_track_competitors` 返回的竞品列表里挑一条**最具代表性的对标产品**作为数据锚点，必须带 ID：

item_id: <UUID>

> 该竞品描述（从 content 里节选）

## 用户故事
当 [具体用户] 在 [具体场景] 时，他们 [遇到具体 X 问题]，我们给 [具体 Y]。禁止"开发者"/"企业"/"所有人"等泛称。

## 依据
150-300 字中文叙事段落。贯穿 Step 1/2/3/4 的发现：
- 市场端观察（引用 Step 1 赛道数据）
- AI 能力端观察（引用 Step 2 能力数据）
- 竞品端观察（引用 Step 4 的竞品 blindspot）
- 为什么这个切入点成立

禁止 "r/xxx 用户说：" 机械格式，改用自然语言 ("Product Hunt 这个月出现了大量 AI 销售邮件工具…"、"Hugging Face 最近一个 trending 模型能在…")。

## 主要功能
3-5 个，每个都是动词 + 具体宾语。

## 竞品
把 `survey_track_competitors` 的 JSON 输出直接贴入（在 code block 中）。

## 盈利模型
把 `propose_monetization` 的 JSON 输出直接贴入。

## MVP 计划
把 `scope_mvp` 的 JSON 输出直接贴入。

## 为什么现在
150 字左右。为什么**此刻**是窗口期（AI 新能力刚成熟 / 赛道刚开始热 / 用户习惯刚转变）。

## 综合评分
`综合评分：X.X`（0-10）。≥ 7 的条件：
- idea_title 无禁用词
- track 明确
- ai_capability_used 具体（不是"AI"这样的泛词）
- niche_cut 明确对标某竞品 blindspot
- 竞品 / 盈利 / MVP 三段都不空
- 用户故事具体到可一句话复述
"""
```

- [ ] **Step 2: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "
from src.agent.prompts import SYSTEM_PROMPT
for marker in ['audit_self_history', 'scan_hot_launches', 'scan_ai_capabilities', 'survey_track_competitors', 'propose_niche_cut', 'propose_monetization', 'scope_mvp']:
    assert marker in SYSTEM_PROMPT, marker
print('prompt ok', len(SYSTEM_PROMPT), 'chars')
"
```

Expected: `prompt ok <n> chars` with n > 3500.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/prompts.py
git commit -m "prompt: rewrite as internet-product-analyst 6-step workflow"
```

---

## Task 14: Persist New Fields in `jobs.py`

**Files:**
- Modify: `backend/src/scheduler/jobs.py`

- [ ] **Step 1: Extract new fields from report**

In `backend/src/scheduler/jobs.py`, find the try block that does `idea_title = report.idea_title ...`. Right before `overall_score = float(report.overall_score)`, add:

```python
            track = report.track
            ai_capability_used = report.ai_capability_used
            niche_cut = report.niche_cut
```

- [ ] **Step 2: Default the fields in the except block**

In the matching `except` block, right before `source_item_id = None`, add:

```python
            track = None
            ai_capability_used = None
            niche_cut = None
```

- [ ] **Step 3: Pass new kwargs into `AnalysisResult(...)`**

In the same function, find the `analysis_record = AnalysisResult(...)` constructor call. Immediately after the `reasoning=reasoning,` line, add:

```python
            track=track,
            ai_capability_used=ai_capability_used,
            niche_cut=niche_cut,
```

- [ ] **Step 4: Smoke-test**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/backend
PYTHONPATH=. python -c "from src.scheduler.jobs import run_analysis; print('ok')"
```

Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add backend/src/scheduler/jobs.py
git commit -m "jobs: persist track/ai_capability_used/niche_cut"
```

---

## Task 15: Frontend Types + Detail Page Sections

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/app/analysis/[id]/page.tsx`

- [ ] **Step 1: Add fields to AnalysisResult interface**

In `frontend/src/lib/types.ts`, inside `interface AnalysisResult`, directly after `reasoning: string | null;`, add:

```typescript
  track: string | null;
  ai_capability_used: string | null;
  niche_cut: string | null;
```

- [ ] **Step 2: Render new sections on detail page**

In `frontend/src/app/analysis/[id]/page.tsx`, find the `{result.reasoning && (...)}` JSX block. Right after its closing `)}`, add:

```tsx
      {(result.track || result.ai_capability_used) && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            赛道与 AI 新能力
          </h2>
          <div
            className="rounded-2xl bg-card px-6 py-5 space-y-3"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {result.track && (
              <div className="flex items-baseline gap-3">
                <span className="text-[11px] font-medium tracking-wider text-muted-foreground">
                  赛道
                </span>
                <span className="font-serif text-[15px] text-foreground">{result.track}</span>
              </div>
            )}
            {result.ai_capability_used && (
              <div className="flex items-baseline gap-3">
                <span className="text-[11px] font-medium tracking-wider text-muted-foreground">
                  AI 新能力
                </span>
                <span className="font-serif text-[14px] text-foreground leading-relaxed">
                  {result.ai_capability_used}
                </span>
              </div>
            )}
          </div>
        </section>
      )}

      {result.niche_cut && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            差异化切入点
          </h2>
          <p
            className="rounded-2xl bg-card px-6 py-5 text-[14px] text-foreground leading-[1.85] font-serif whitespace-pre-wrap"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {result.niche_cut}
          </p>
        </section>
      )}
```

- [ ] **Step 3: Type-check**

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIIdea/frontend
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/app/analysis/\[id\]/page.tsx
git commit -m "frontend: render track/ai_capability_used/niche_cut on detail page"
```

---

## Task 16: E2E Verification

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

- [ ] **Step 2: Trigger analyze**

```bash
curl -s -X POST http://localhost:8001/api/pipeline/trigger/analyze_data
```

Expected: `{"status":"triggered", ...}`

- [ ] **Step 3: Follow tool-call trace**

```bash
tail -f /tmp/backend.log | grep -E "tool_audit_self_history|tool_scan_hot_launches|tool_scan_ai_capabilities|tool_scan_pain_clusters|tool_survey_track_competitors|tool_propose_niche_cut|tool_critique_idea|tool_propose_monetization|tool_scope_mvp|extract_agent_report_done|scheduled_analysis_done|scheduled_analysis_skipped"
```

Expected event order:
1. `tool_audit_self_history` × 1 (first)
2. `tool_scan_hot_launches` × 1
3. `tool_scan_ai_capabilities` × 1
4. `tool_scan_pain_clusters` × 1
5. `tool_survey_track_competitors` × 3 (one per candidate)
6. `tool_propose_niche_cut` × 3
7. `tool_critique_idea` × 3
8. `tool_propose_monetization` × 1 (on the chosen one)
9. `tool_scope_mvp` × 1
10. `extract_agent_report_done` with `has_track=true, has_ai_capability=true, has_niche=true`
11. `scheduled_analysis_done`

If steps 1-4 are skipped → prompt compliance issue → tighten Task 13.

- [ ] **Step 4: Query the new row**

```bash
curl -s "http://localhost:8001/api/analysis-results?page=1&page_size=1" | python3 -c "
import sys, json
r = json.load(sys.stdin)['items'][0]
print('Title:', r['idea_title'])
print('Track:', r.get('track'))
print('AI Capability:', r.get('ai_capability_used'))
print('Niche Cut:', (r.get('niche_cut') or '')[:120])
print('Score:', r['overall_score'])
"
```

Expected: `track` / `ai_capability_used` / `niche_cut` all non-empty and concrete.

- [ ] **Step 5: Browser spot-check**

Open `http://localhost:3000/analysis/<id>` in browser. Confirm 2 new sections render:
- **赛道与 AI 新能力** card with both fields filled
- **差异化切入点** paragraph

If any broken → fix in the page file, commit with a follow-up message.

---

## Self-Review

**Spec coverage.** User's three asks:

1. "这个是一个互联网产品分析专家 Agent 项目" → Tasks 1-6 reorient tools around product-trend signals (Product Hunt / HN / arxiv / HF) instead of consumer complaints. Task 13 prompt rewrite encodes the new framing.
2. "你的分析报告几乎没一个可用" → Task 5 `audit_self_history` lets the agent see its own failure patterns every run and actively avoid them.
3. "可实现 / 可落地 / 有市场需求 / 有盈利模式 / AI 相关" → each captured:
   - 可实现 / 可落地 → `scope_mvp` (Task 8) + `critique_idea` solution_fit hard constraint (pre-existing)
   - 有市场需求 → `scan_hot_launches` (Task 1) + `survey_track_competitors` (Task 3) ground idea in real market activity
   - 有盈利模式 → `propose_monetization` (Task 7) required for final output
   - AI 相关 → `scan_ai_capabilities` (Task 2) + prompt forbids outputs without `ai_capability_used`

**Placeholder scan.** All tool bodies are full implementations. No "TBD" / "handle errors appropriately" / "similar to Task N". Migration revision `b8f2e5a4c3d9` down-revises on `f4a8c2e9d5b7` which is the current head. Tool function names consistent across Task 6 registry, Task 13 prompt references, and Task 16 log-grep filter.

**Type consistency.**
- Tool names `audit_self_history` / `scan_hot_launches` / `scan_ai_capabilities` / `survey_track_competitors` / `propose_niche_cut` / `propose_monetization` / `scope_mvp` — consistent Task 1-8 create, Task 6 register, Task 13 prompt, Task 16 verify.
- Column names `track` / `ai_capability_used` / `niche_cut` — consistent across Task 9 migration, Task 10 model, Task 11 schema, Task 12 AgentReport, Task 14 jobs.py, Task 15 frontend.
- Alembic `down_revision: f4a8c2e9d5b7` matches existing head (verified via `alembic/versions/` directory listing).

## Explicitly Out of Scope

- **Re-balancing data sources**: current `sources_registry.py` is fine for this plan's needs. Removing `rss:lifehacker` / `rss:nyt_well` / consumer RSS would be a follow-up if desired.
- **Deleting the 54 existing bad reports**: requires explicit user permission to DELETE from shared DB. Leave as-is. New rows will look better.
- **Web-search-backed competitor / capability signals**: Task 2 and Task 3 both use the DB, not live web. Adding a web search tool (Perplexity / Brave API) is a higher-leverage follow-up but out of scope here.
- **TDD unit tests for the 5 new tools**: each is smoke-tested via its Step 2 command. Full pytest coverage is a follow-up.
- **Multi-idea reports (rank top 3)**: current workflow outputs exactly 1 idea. Multi-idea output is a UI+schema change, out of scope.
- **Backfill `track` / `ai_capability_used` / `niche_cut` on existing rows**: legacy rows stay NULL. Frontend is null-safe. Follow-up can run an extractor-style LLM backfill if desired.
