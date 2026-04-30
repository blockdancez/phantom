"""Competitor scan — call this BEFORE critique_idea.

Asks gpt-4o to enumerate already-shipping U.S. products that solve the
same user job as the idea. Returns JSON with a count of "strong"
incumbents (those with credible ARR > $5M or category dominance).

We use the model's own knowledge rather than a web search API for two
reasons:
1. SaaS / consumer-app market knowledge is well-represented in gpt-4o's
   training data; web search would just round-trip the same info through
   noisier results.
2. No external HTTP dependency / rate limit / API key to manage.

The prompt forces the model to mark itself uncertain rather than invent
fake competitors when it doesn't actually know the space.
"""

from __future__ import annotations

import json

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


_PROMPT = """你是一个对美国互联网/SaaS/AI 工具市场非常熟悉的产品分析师。下面给你一个产品 idea，请列出**当下**美国市场已经在卖的同类产品（直接竞品）。

## Idea

- 标题：{idea_title}
- 一句话描述：{idea_description}
- 目标用户：{target_audience}
- 主要功能：{key_features}

## 你的任务

枚举**直接竞品**——不是擦边的、不是被替代用法的，而是同样目标用户在为同样问题付费的产品。要求：

- 优先列你**明确知道存在**的产品。如果你不确定它是否还在运营，不要列。
- 每个竞品评估 ARR（年度经常性收入）量级：≥ $50M=large，$5M-$50M=mid，<$5M 或不确定=small。
- 只统计 large + mid 才算"strong incumbent"——small 不计入 strong_count（小竞品意味着市场没真正成熟）。
- 如果你**完全不熟悉**这个细分赛道，说出来——把 confidence 标 "low"。

## 输出（严格 JSON，无 markdown 包裹）

{{
  "confidence": "high | medium | low",
  "competitors": [
    {{
      "name": "<产品名>",
      "url": "<官网或 'unknown'>",
      "est_arr_tier": "large | mid | small | unknown",
      "differentiator": "<这个竞品的核心卖点一句话>"
    }}
  ],
  "strong_count": <large+mid 竞品数量整数>,
  "verdict": "saturated | competitive | open",
  "comment": "<2-3 句中文：当前市场是空白/有几家小玩家/已被巨头占据，并对这个 idea 进入有什么建议>"
}}

**verdict 规则**：
- saturated = strong_count >= 3，或有任一 large 玩家通吃市场
- competitive = strong_count 1-2，市场有竞争但仍有 niche
- open = strong_count = 0，且 confidence != low

不要在 JSON 外加任何说明。
"""


@tool
async def search_competitors(
    idea_title: str,
    idea_description: str = "",
    target_audience: str = "",
    key_features: str = "",
) -> str:
    """Enumerate U.S. competitors already selling the same product. Returns JSON {confidence, competitors:[...], strong_count, verdict ('saturated'|'competitive'|'open'), comment}. Call this BEFORE critique_idea so critique can include competitor pressure in its verdict. strong_count >= 3 (saturated) usually means the idea should be rejected unless it has a clear niche edge."""
    logger.info("工具_竞品扫描", idea_title=idea_title[:80])

    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    prompt = _PROMPT.format(
        idea_title=idea_title,
        idea_description=idea_description or "(无)",
        target_audience=target_audience or "(无)",
        key_features=key_features or "(无)",
    )
    response = await llm.ainvoke(prompt)
    raw = response.content if isinstance(response.content, str) else str(response.content)

    # Sanity check: if model returned non-JSON, surface that to caller so
    # critique_idea can still proceed with the raw text rather than failing.
    try:
        parsed = json.loads(raw)
        logger.info(
            "竞品扫描完成",
            verdict=parsed.get("verdict"),
            strong_count=parsed.get("strong_count"),
            confidence=parsed.get("confidence"),
        )
    except Exception:
        logger.warning("竞品扫描结果无法解析", head=raw[:200])

    return raw
