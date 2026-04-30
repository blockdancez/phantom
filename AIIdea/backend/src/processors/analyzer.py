"""Structured item analysis — Step 2 of the processing pipeline.

Replaces the old separate Classifier + Scorer pair. A single LLM call produces
the full insight bundle (category, tags, summary, problem, opportunity,
target_user, why_now, hotness, novelty, score) as a typed Pydantic model via
LangChain's structured-output binding.

This is the only place in the processing pipeline that consumes LLM tokens.
"""

from __future__ import annotations

import json
from typing import Literal

import structlog
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.models.source_item import SourceItem

logger = structlog.get_logger()


Category = Literal[
    "AI/ML",
    "SaaS",
    "Developer Tools",
    "E-commerce",
    "Social",
    "Fintech",
    "Health Tech",
    "Education",
    "Productivity",
    "Other",
    # Reserved bucket for "LLM returned an off-taxonomy label" — the plan's
    # feature-3 error matrix writes this one out explicitly.
    "unknown",
]


# What kind of signal this row represents — drives anchor selection
# downstream. Only ``pain_point`` / ``question`` items are good idea
# anchors; everything else has known failure modes:
# - launch: copying someone's existing product
# - story: turning nostalgia/anecdote into an idea (no real demand signal)
# - news: turning a press release into an idea (no user pain)
# - other: meta-discussion, memes, unrelated
SignalType = Literal[
    "pain_point",
    "question",
    "launch",
    "story",
    "news",
    "other",
    "unknown",
]


class ItemAnalysis(BaseModel):
    """Structured insight produced for a single SourceItem."""

    category: Category
    tags: list[str] = Field(
        ...,
        description="2-5 lowercase kebab-case tags capturing concrete topics",
        min_length=1,
        max_length=5,
    )
    summary_zh: str = Field(
        ...,
        description="3-5 句中文摘要，具体精炼，避免空话",
    )
    problem: str = Field(
        ...,
        description="这条内容揭示了什么用户痛点 / 需求？若无明显痛点请写 '无明显痛点'",
    )
    opportunity: str = Field(
        ...,
        description="基于此信号可能的产品机会，一句话描述具体做什么",
    )
    target_user: str = Field(
        ...,
        description="最可能为这个产品付费的目标用户画像，一句话",
    )
    why_now: str = Field(
        ...,
        description="为什么当下是做这件事的合适时机？若无时效性请写 '无特殊时机信号'",
    )
    hotness: float = Field(..., ge=0, le=10, description="热度：当下讨论 / 传播度")
    novelty: float = Field(..., ge=0, le=10, description="新颖度：创意的新鲜程度")
    score: float = Field(
        ...,
        ge=0,
        le=10,
        description="综合分 = hotness * 0.4 + novelty * 0.6, 保留 1 位小数",
    )
    signal_type: SignalType = Field(
        ...,
        description=(
            "这条内容的类型：pain_point=用户在抱怨/吐槽某事 / 求助找工具；"
            "question=用户在问'有没有 X 工具/方法'；"
            "launch=作者在宣传自己已经做出来的产品（如 'Built X' / 'Launched Y' / 'I made'）；"
            "story=怀旧/历史/讲故事/趣闻（如 '20 年前 X 公司...'）；"
            "news=公司动态/产品发布会/收购/融资新闻；"
            "other=以上都不像（meta 讨论/段子/无主题闲聊）。"
            "判断标准：选**最贴近**的一种，宁可标 other 也不要硬塞 pain_point。"
        ),
    )


_SYSTEM = (
    "你是一个专业的产品情报分析师，目标用户群体为美国市场的独立开发者、"
    "小型 SaaS 团队和创业者。给你一条从互联网采集到的原始内容，你要从中"
    "提炼可执行的产品情报，严格按 schema 输出。所有文本字段用中文。"
    "不要输出 schema 之外的任何内容。"
)

_USER_TEMPLATE = """标题: {title}
来源: {source}
原始信号: {signals}

正文:
{content}

请输出结构化分析。"""


_RELEVANT_RAW_KEYS = (
    "score",
    "num_comments",
    "stars_today",
    "tweet_volume",
    "descendants",
    "ups",
    "upvote_ratio",
)


class Analyzer:
    """Single-call structured analyzer replacing Classifier + Scorer."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        llm = ChatOpenAI(model=model, temperature=0.2)
        # LangChain wraps the schema into an OpenAI tool/function call under
        # the hood so the model is guaranteed to return a valid ItemAnalysis.
        # method="function_calling" works with older openai SDKs that don't
        # expose the newer `.parse()` endpoint.
        self.llm = llm.with_structured_output(ItemAnalysis, method="function_calling")
        self.model_name = model

    async def analyze(self, item: SourceItem) -> ItemAnalysis:
        signals = {
            k: v for k, v in (item.raw_data or {}).items() if k in _RELEVANT_RAW_KEYS
        }
        prompt = _USER_TEMPLATE.format(
            title=item.title or "",
            source=item.source or "",
            signals=json.dumps(signals, ensure_ascii=False),
            content=(item.content or "")[:6000],
        )
        # LangChain lets us prepend a system message via a list
        from langchain_core.messages import SystemMessage, HumanMessage

        messages = [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        logger.debug(
            "分析器调用",
            item_id=str(item.id),
            content_chars=len(item.content or ""),
            model=self.model_name,
        )
        # Per feature-3: "LLM 调用失败 → 记错误日志，该条跳过保留 processed=false,
        # 不阻塞批次". Do NOT swallow the exception here — the orchestrator in
        # ``processors/pipeline.py`` already catches per-item failures and
        # leaves ``processed=False``, which is the desired behaviour.
        raw_result = await self.llm.ainvoke(messages)
        result: ItemAnalysis = raw_result  # type: ignore[assignment]
        logger.debug(
            "分析器完成",
            item_id=str(item.id),
            category=result.category,
            score=result.score,
        )
        return result
