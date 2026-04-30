"""Hard reality-check for a candidate product idea.

Called *after* generate_ideas and *before* the agent's final decision.

Two tiers of checks:

**Hard constraints** (any fail → overall=reject → agent must regenerate):
  1. is_real_idea   — actual product, not meta-advice
  2. technical_feasibility — doable without system-level permissions or hardware
  3. legal_risk     — no obvious regulatory / TOS / CFAA exposure

**Soft concerns** (logged but do not block; agent may lower score):
  4. competitive_landscape — entrenched incumbents?
  5. differentiation — crowded market, weak moat?

Soft concerns alone do not reject; many profitable products exist in
crowded categories with modest differentiation. Rejecting on them was
producing "3 strikes → NO_VIABLE_IDEA_FOUND" too often.
"""

from __future__ import annotations

import structlog
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


_CRITIQUE_PROMPT = """你是资深产品经理，对下面的产品 idea 做审查。**按两类标准判断**。

## 输入

- 标题：{idea_title}
- 用户故事：{user_story}
- 锚点引用：{anchor_quote}
- 主要功能：{key_features}
- 竞品扫描（来自 search_competitors 工具）：
{competitors_summary}

## 硬约束（任一 fail 整体 reject）

### 1. is_real_idea
reject 条件：
- 标题含"建议"、"方案"、"框架"、"搜索策略"、"指南"等元级说法
- idea 的事情是"meta"（如"建议调整搜索策略"、"帮助 agent 搜数据"）

### 2. technical_feasibility
reject 条件：
- 需要系统级权限第三方 app 拿不到（控制别的 app 的广告 / 修改系统设置 / 读取其他 app 内容 / 拦截通知）
- 需要制造硬件（除非明确说用现成智能家居 API 调度）
- 需要大规模基础设施（自建地图 / 证券撮合 / 支付清算）

典型 reject 案例：屏蔽其他 app 广告（iOS/Android 沙箱禁止）、自研全新操作系统

### 3. legal_risk
reject 条件：
- 绕过付费墙或广告（CFAA 风险）
- 爬取有明确 TOS 禁止条款的数据（LinkedIn / TikTok）
- 进入需要牌照的强监管领域（美国的证券 / 银行 / 处方药 / 律师执业）
- 处理未成年人数据或 HIPAA 受保护医疗数据，但没提到合规架构

### 4. market_saturation（基于 search_competitors）
reject 条件：
- 竞品扫描的 verdict = "saturated"（已有 ≥3 个 strong incumbent，或某个 large 玩家通吃）
- 竞品扫描里出现 ≥1 个 large 量级（ARR > $50M）的直接竞品，且本 idea 的差异化点没有在 key_features 里清楚体现

例外（**不** reject）：
- verdict = "competitive" 但 idea 在 key_features 里清楚说明了一个**未被现有竞品覆盖**的差异化点（特定细分人群 / 特定渠道 / 特定交互范式），可以放过
- verdict = "open" 一律放过这一项

如果 search_competitors 没有被调过（"竞品扫描"为空或 "(未调研)"），**这一项 reject** —— 强制 agent 先去调 search_competitors。

### 5. solution_fit（最重要！）
**方案必须真的能解决 anchor_quote 里描述的痛点**。

reject 条件（任一命中都 reject）：
- 痛点源于**陌生人/非用户**的行为，但方案让**被困扰的用户**装 app —— 这是方向错位（被动方装 app 也没用，因为要改变的是陌生人）
  - 反例："陌生人在餐厅大声打电话" → 让被困扰用户装"提醒陌生人安静的 app"。陌生人根本不会收到任何提醒
  - 反例："邻居晚上噪音大" → 让我装"噪音分析 app"。邻居没装我的 app，分析了也没用
  - 反例："路人闯红灯" → 让司机装"预警 app"。闯红灯的人没装
- 方案**假设第三方（非用户、无合同关系的人）会配合**（如自愿安装同款 app / 扫二维码 / 接收短信）但没有明确说他们为什么会这么做
- 方案只是"检测问题"但没真正"解决"问题（只监测 / 只提醒用户本人 / 只可视化数据 —— 如果痛点本身就是"用户察觉不到"这才值得；如果用户明明已经察觉到但无力改变，只"提醒"是没用的）
- 方案的"解决路径"明显与痛点的因果链断开：拿痛点逐字读一遍，想清楚 **"我用户装了 app 之后下一步怎么行动改变这个情况？"** 如果答案是"没法行动"，reject

**快速判断问句**：
- "这个 app 的用户装上它之后，能真的让痛点消失吗？"
- "痛点里那个造成问题的角色（陌生人 / 邻居 / 大厂 / 政府）为什么会配合？"
- 不能清晰回答这两个问句 → reject

## 软提示（记录 concerns 但不整体 reject）

### 4. competitive_landscape
concern 条件（**不要**自动 reject）：
- 目标市场有大厂深耕（Google / Apple / Amazon / Microsoft / Samsung）
- 但：有细分 niche 或用户体验切入点就仍可接受

### 5. differentiation
concern 条件（**不要**自动 reject）：
- 同类 app 已有多款成熟产品
- 但：如果 idea 说清楚了具体的差异化点（特定场景 / 特定用户 / 特定交互），仍可接受

## 输出（严格 JSON，无 Markdown 包裹）

{{
  "is_real_idea": "pass 或 reject",
  "technical_feasibility": "pass 或 reject",
  "legal_risk": "pass 或 reject",
  "market_saturation": "pass 或 reject",
  "solution_fit": "pass 或 reject",
  "competitive_landscape": "pass 或 concern",
  "differentiation": "pass 或 concern",
  "hard_reject_reasons": ["如果硬约束有 reject，列出一句话理由；否则空数组"],
  "soft_concerns": ["列出所有 concern 的一句话说明"],
  "overall": "pass 或 reject"
}}

**overall 规则**：只要硬约束五项（is_real_idea / technical_feasibility / legal_risk / market_saturation / solution_fit）全 pass，overall = "pass"（哪怕软提示有 concerns）。硬约束任一 reject，overall = "reject"。
"""


@tool
async def critique_idea(
    idea_title: str,
    user_story: str,
    anchor_quote: str = "",
    key_features: str = "",
    competitors_summary: str = "",
) -> str:
    """Reality check. Hard constraints (is_real_idea / technical_feasibility / legal_risk / market_saturation / solution_fit) cause overall=reject. Soft concerns (competitive_landscape / differentiation) are logged but do not block. **competitors_summary** must be the JSON returned by search_competitors — call that tool first; passing an empty string forces market_saturation=reject so the agent is pushed to do the scan. Returns JSON."""
    logger.info("工具_审查创意", idea_title=idea_title[:80])

    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
    prompt = _CRITIQUE_PROMPT.format(
        idea_title=idea_title,
        user_story=user_story,
        anchor_quote=anchor_quote or "(无)",
        key_features=key_features or "(无)",
        competitors_summary=competitors_summary or "(未调研)",
    )
    response = await llm.ainvoke(prompt)
    # Surface the full verdict in logs so we can see which axis failed and
    # why agent bailed out.
    logger.info("创意审查结果", verdict=response.content[:400])
    return response.content
