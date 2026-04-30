import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


TREND_PROMPT = """你是一名消费级产品趋势分析师。从下列采集到的 item 中，识别 TOP 3 具体的、跨源的趋势。

**强制要求**：
- 每个 trend 必须附带 **至少 3 条支持 item**，每条包含该 item 的 ID、source、以及一句 ≤ 50 字的原文引用（从该 item 的 Content 里抽）
- trend 的名称必须具体到一个动作或一个场景，**严禁使用**这些抽象词：平台、助手、中心、系统、管理、优化、全面、智能、解决方案、框架
- 忽略面向开发者/ML 研究人员的 item，优先基于消费者痛点类 item 抽取趋势
- 如果某个趋势凑不够 3 条 supporting_items，丢弃它，不要编造 ID

**输出格式**（严格 JSON，不要 Markdown 代码块包裹）：

[
  {{
    "trend": "具体趋势一句话，≤ 20 字",
    "supporting_items": [
      {{"id": "从 Content 中看到的 ID", "source": "reddit|rss:xxx|...", "quote": "来自该 item Content 的原文引用"}},
      ...
    ]
  }},
  ...
]

原始 items：
{items_summary}
"""


@tool
async def synthesize_trends(items_summary: str) -> str:
    """Analyze source items and return top 3 trends as JSON, each with ≥3 supporting item citations (id + quote). Output preserves item lineage so downstream idea generation can anchor on specific items."""
    logger.info("工具_归纳趋势", summary_length=len(items_summary))

    # Low temperature to discourage LLM from inventing fake item IDs.
    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
    prompt = TREND_PROMPT.format(items_summary=items_summary)
    response = await llm.ainvoke(prompt)
    return response.content
