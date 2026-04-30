"""Parse the free-form markdown report produced by the LangGraph agent into
structured product-focused fields for persistence.

The agent is expected to produce:
- A ``## 数据引用`` section containing the anchor item's UUID
- A ``## 依据`` section with a narrative paragraph explaining *how* the idea
  was reached (PM-style reasoning, not a bulleted quote list)

When either section is missing, the corresponding field stays null rather
than being fabricated.
"""

from __future__ import annotations

import structlog
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class AgentReport(BaseModel):
    """Structured form of one analysis run. All text in Chinese."""

    idea_title: str = Field(description="产品创意的一句话标题，不含 Markdown 符号，不超过 25 字；禁用'平台/助手/中心/系统/管理/优化/全面/智能'等抽象词")
    product_idea: str = Field(
        description="产品 idea：2-4 句中文说明这是一个什么样的产品，解决什么核心问题。不含 Markdown 符号",
    )
    target_audience: str = Field(
        description="产品面向人群：具体的目标用户群体描述（角色、规模、行业等），纯文本，避免'所有人'/'中小企业'这类泛称",
    )
    use_case: str = Field(
        description="产品使用场景：用户在什么情境下会用到这个产品，给出 2-4 个具体场景，纯文本",
    )
    pain_points: str = Field(
        description="现有的痛点：这些用户在当前没有此产品时面临的痛点，3-5 条，纯文本",
    )
    key_features: str = Field(
        description="主要的功能：产品的 3-6 个核心功能点，纯文本",
    )
    source_quote: str | None = Field(
        default=None,
        description="锚点 item 的原文引用（≤ 100 字）。从 `## 数据引用` 的 blockquote 里取。没有就留空",
    )
    source_item_id: str | None = Field(
        default=None,
        description="锚点 SourceItem 的 UUID。原报告 `## 数据引用` 段落应包含一个 `item_id: <uuid>` 或 `ID: <uuid>`，从中抽取。必须是合法 UUID 格式。没找到就留空（null）—— 禁止编造",
    )
    user_story: str | None = Field(
        default=None,
        description="一句话用户故事：'当 [具体用户] 在 [具体场景] 时，他们 [遇到 X 问题]，我们给 [具体 Y]'。如果原报告没有明显的 `## 用户故事` 段落，这里留空",
    )
    reasoning: str | None = Field(
        default=None,
        description="产品经理叙事风格的一段中文推理，150-300 字。说明这个 idea 是如何从数据中得来的：我们从哪些帖子 / 文章 / 讨论中看到了什么具体的抱怨或信号，这些信号如何指向这个产品机会。不是引用列表，不是 '用户说：xxx' 这种机械格式。从原报告的 `## 依据` 段落抽取。没有就留空",
    )
    overall_score: float = Field(
        description="0-10 的综合评分，支持一位小数",
        ge=0,
        le=10,
    )
    is_digital_product: bool = Field(
        description=(
            "判定该 idea 是否属于'互联网/数字产品'。"
            "true 当且仅当 idea 形态是：Web 应用 / SaaS / 移动 app / 浏览器插件 / "
            "API / SDK / 开发者工具 / AI 应用（LLM/RAG/Agent/视觉模型） / "
            "Bot（Slack/Discord/Telegram/iMessage）/ CLI / 桌面客户端。"
            "false 当 idea 是：实体商品（袋/盒/包装/硬件配件）、线下服务（清洁/维修/配送/培训现场班）、"
            "纯生活攻略（教用户怎么用现有工具）、食品饮料、物流运输等需要实体网络的业务。"
            "判定标准看 idea_title + product_idea + key_features，"
            "如果 key_features 里出现物理动作（缝制/印刷/装配/送达/上门）一定 false；"
            "如果 product_idea 描述的是'物品'而非'软件'，false；"
            "如果是'app + 实体物品'的组合（如智能水杯），false。"
        )
    )
    digital_product_form: str | None = Field(
        default=None,
        description=(
            "数字产品形态的简短标签，从以下中选一个："
            "web / mobile_app / chrome_extension / api / sdk / ai_app / "
            "bot / cli / desktop / saas。"
            "is_digital_product=false 时留空。"
        ),
    )
    project_name: str = Field(
        description=(
            "项目英文短名（slug），用作 AIJuicer project_name / DB / 仓库目录命名。"
            "**严格格式**：1-3 个全小写英文单词，用 `-` 连接；"
            "只允许 [a-z0-9-]，不能以 `-` 开头/结尾；总长度 ≤ 40 字符。"
            "应当反映 idea 的核心含义（用英文表达 idea_title 的关键名词），"
            "示例：``resume-ai`` / ``standup-bot`` / ``invoice-ocr-api``。"
            "**不要**起 `idea-1` / `my-project` 这类无信息名。"
        ),
        pattern=r"^[a-z][a-z0-9]*(-[a-z0-9]+){0,2}$",
        max_length=40,
    )


_EXTRACT_PROMPT = """下面是一份产品创意分析报告（Markdown 格式）。请从中提取结构化字段。

要求：
- 所有字段必须是中文
- 去除所有 Markdown 符号（如 ###、**、- 等），输出纯文本
- 标题简短有力；**禁用抽象词**：平台 / 助手 / 中心 / 系统 / 管理 / 优化 / 全面 / 智能
- `source_quote` 只取 `## 数据引用` 里 blockquote 的原文，不含标题和 ID
- `source_item_id` 从 `## 数据引用` 段落里抽出 UUID 格式字符串，没有就 null
- `reasoning` 是 `## 依据` 段落的内容，应是一段产品经理风格的叙事文字，**重新组织成自然流畅的 150-300 字中文段落**。如果原报告给的是 bullet list，请在提取时改写成段落。不要保留 "r/sub" 这种 Reddit 原生标签，改用自然语言（如"Hacker News 上一位独立开发者提到…"、"讨论该主题的另一条帖子里，用户反映…"）
- `user_story`: 只从 `## 用户故事` 段落提取
- `is_digital_product`: 必填。严格按 schema 描述判定，宁严勿松；当 product_idea / key_features 里同时出现"物品"和"app"时，按物品的"配套 app"处理 → false
- `digital_product_form`: is_digital_product=true 时必填一个标签；false 时留空
- `project_name`: 必填。把 idea_title 翻译成 1-3 个全小写英文单词，用 `-` 连接，如 ``resume-ai`` / ``standup-bot`` / ``invoice-ocr-api``。只允许 [a-z0-9-]，开头必须字母，长度 ≤ 40。**禁止**起 `idea-1` / `my-project` 这类无信息名

原始报告：
---
{report}
---"""


async def extract_agent_report(report_text: str) -> AgentReport:
    """Run a single structured-output LLM call to parse the agent's markdown."""
    logger.info("抽取 Agent 报告开始", report_chars=len(report_text))

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
        AgentReport, method="function_calling"
    )
    result = await llm.ainvoke(_EXTRACT_PROMPT.format(report=report_text))

    logger.info(
        "抽取 Agent 报告完成",
        title=result.idea_title[:60],
        score=result.overall_score,
        has_quote=bool(result.source_quote),
        has_story=bool(result.user_story),
        has_reasoning=bool(result.reasoning),
        has_anchor=bool(result.source_item_id),
        is_digital=result.is_digital_product,
        form=result.digital_product_form,
        project_name=result.project_name,
    )
    return result
