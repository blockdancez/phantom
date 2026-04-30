import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


IDEA_PROMPT = """你是美国消费级互联网产品策略师。下面是已识别出的趋势 JSON（每个 trend 附带 ≥ 3 条 supporting_items 及原文引用）：

{trends}

市场上下文（可选）：
{market_context}

## 任务

从 supporting_items 中**挑一个具体的 item 作为锚点**，基于它的原文引用推出一个产品 idea。idea 的用户、场景、痛点必须直接来自这个锚点 item —— 禁止凭空发明。

## 锚点挑选的硬性规则

**禁止**选以下类型的 supporting_item 作为锚点：
- item 内容涉及开发者 / 程序员 / 工程师 / 运维 / SRE / DevOps / API / SDK / 代码 / chatbot 集成 / LLM 接入 / 数据工程 / 后端 / 前端框架
- item 来自 `r/SaaS` / `r/webdev` / `r/startups` / `r/LocalLLaMA` / `r/indiehackers` / `r/SideProject` / arxiv / devto / dev.to / hackernoon
- `user_story` 里**绝对不允许**出现以下词：`开发者`、`程序员`、`工程师`、`DevOps`、`运维`、`后端`、`前端`、`团队`、`企业`

**优先**选这些 supporting_item：
- 来自 `r/mildlyinfuriating` / `r/firstworldproblems` / `r/LifeProTips` / `r/Parenting` / `r/personalfinance` / `r/frugal` / `r/loseit` / `r/BuyItForLife` / `r/getdisciplined` / `rss:lifehacker` / `rss:nyt_well` / `rss:nyt_your_money` / `rss:wirecutter`
- 内容描述的用户是普通消费者（家长 / 上班族 / 学生 / 老人 / 租户 / 房主 / 通勤族 / 病人 / 健身新手 / 理财小白）

如果所有候选 supporting_item 都不符合"普通消费者"条件，返回 JSON 字段 `idea_title = "NO_CONSUMER_ANCHOR_FOUND"` 而不是强行编一个开发者 idea。

## 反面示范（绝不能产出这样的 idea，太抽象、太大、太泛）

- 个性化本地化 AI 助手
- AI 就绪家庭中心
- 应急响应物流优化平台
- 远程办公协作工具
- AI 驱动的代码优化平台
- 高分数据信号搜索工具

## 期望的 idea 形态（具体 / 小 / 画面感 / 普通人能描述）

- 把 Venmo 群账单自动拆分成 iMessage 小额提醒，忘记还钱的朋友自动 nudge
- 每月一次扫你社交账号的陌生人好友申请，一键批量拒绝（Gmail Unsubscribe 的社交版）
- 爸妈坐飞机时帮他们翻译机上广播 + 空乘指令的 iOS app（上飞机离线可用）

## 禁用词

以下词**绝对不允许**出现在 idea_title 或 user_story 中：
- 平台、助手、中心、系统、管理、优化、全面、智能、解决方案、框架、生态、整合

## 输出格式（严格 JSON，不要 Markdown 代码块包裹）

{{
  "idea_title": "产品名 + 一句话描述，≤ 25 字，不含禁用词",
  "anchor_item_id": "从 trends.supporting_items 中选的一个 id",
  "anchor_quote": "该 item 的原文引用，≤ 100 字",
  "user_story": "当 [具体用户，不是'中小企业'/'技术敏感用户'这类泛称] 在 [具体动作或时机] 时，他们 [遇到的具体 X 问题]，我们给 [具体 Y]",
  "key_features": "3-5 个核心功能，逗号分隔，每个功能都是动词 + 具体宾语，禁用'管理/优化/全面'类虚词"
}}
"""


@tool
async def generate_ideas(trends: str, market_context: str = "") -> str:
    """Pick one anchor item from the trends JSON and generate ONE concrete product idea grounded in that item's original quote. Returns JSON with idea_title, anchor_item_id, anchor_quote, user_story, key_features."""
    logger.info("工具_生成创意")

    # temperature=0.4 — lower than before (was 0.7) to keep idea close to the
    # anchor quote rather than drifting into imaginative abstraction.
    llm = ChatOpenAI(model="gpt-4o", temperature=0.4)
    prompt = IDEA_PROMPT.format(trends=trends, market_context=market_context)
    response = await llm.ainvoke(prompt)
    return response.content
