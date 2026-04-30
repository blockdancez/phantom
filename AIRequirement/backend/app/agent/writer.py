import re

import structlog

logger = structlog.get_logger()

_OUTER_FENCE_RE = re.compile(
    r"^\s*```[a-zA-Z0-9_+-]*\s*\n(.*?)\n\s*```\s*$",
    re.DOTALL,
)


def _strip_outer_fence(text: str) -> str:
    """Models occasionally wrap the whole markdown response in ```...```.
    The frontend's `.prose pre` then renders the entire PRD on a black
    background. Detect & unwrap a single outer fence; leave inner code
    blocks alone."""
    m = _OUTER_FENCE_RE.match(text)
    return m.group(1) if m else text

PRD_SYSTEM_PROMPT = """你是一位资深的产品经理，擅长撰写清晰、完整、专业的产品需求文档（PRD）。

你需要根据用户提供的产品idea和竞品调研结果，生成一份完整的产品需求文档。

文档必须包含以下章节：
1. **产品概述** — 产品定位、目标用户、核心价值
2. **市场分析** — 竞品分析、市场机会、差异化策略
3. **用户画像** — 目标用户群体描述、用户痛点
4. **功能需求** — 核心功能列表（P0/P1/P2优先级）、每个功能的详细描述
5. **非功能需求** — 性能、安全性、可用性要求
6. **信息架构** — 页面结构、导航流程
7. **MVP范围** — 第一版最小可行产品包含的功能
8. **里程碑计划** — 粗略的开发时间线
9. **成功指标** — 可量化的KPI

输出格式为Markdown，请用中文撰写。
直接输出Markdown正文，**不要**用 ``` 代码围栏把整篇文档包起来；只在确实需要展示代码片段时才使用代码块。"""


class PrdWriter:
    def __init__(self, openai_client, model: str = "gpt-4o"):
        self.client = openai_client
        self.model = model

    async def generate(
        self,
        idea: str,
        research: dict,
        rerun_instruction: str | None = None,
        previous_prd: str | None = None,
    ) -> dict:
        # Edit mode: rerun + we have the previous PRD → patch it surgically.
        # Without this, the model regenerates from scratch every rerun and the
        # output drifts wildly even on tiny feedback ("the two PRDs are
        # completely different"). We give it the previous text as the base and
        # tell it to edit minimally.
        if rerun_instruction and previous_prd and previous_prd.strip():
            return await self._generate_edit(idea, rerun_instruction, previous_prd)

        logger.info(
            "PRD 生成开始",
            idea=idea[:100],
            model=self.model,
            rerun=bool(rerun_instruction),
        )

        competitors_text = self._format_competitors(research.get("competitors", []))
        keywords_text = ", ".join(research.get("keywords", []))

        rerun_header = ""
        rerun_footer = ""
        system_suffix = ""
        if rerun_instruction:
            rerun_header = (
                "# ⚠️ 重跑指令（最高优先级，必须严格执行）\n\n"
                f"{rerun_instruction}\n\n"
                "执行约束：\n"
                "1. 上述反馈是本次输出的首要目标，优先级高于默认章节模板。\n"
                "2. 与反馈冲突的旧版本写法必须直接覆写，不得保留。\n"
                "3. 反馈中提到的每一个要点都必须在文档中明确体现。\n\n"
                "---\n\n"
            )
            rerun_footer = (
                "\n\n---\n\n"
                "**最后请自检：上方「重跑指令」中提到的每个要点，"
                "是否都已经在文档里得到明确体现？如有遗漏，请补充后再输出最终结果。**"
            )
            system_suffix = (
                "\n\n本次为重跑任务。用户已提供修改反馈，必须严格按反馈调整，"
                "不要保留旧版本中与反馈冲突的内容。"
            )

        user_prompt = f"""{rerun_header}## 产品Idea

{idea}

## 竞品调研结果

### 关键词
{keywords_text}

### 竞品列表
{competitors_text}

请根据以上信息，生成一份完整的产品需求文档。{rerun_footer}"""

        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=8000,
            temperature=0.3 if rerun_instruction else 0.7,
            messages=[
                {"role": "system", "content": PRD_SYSTEM_PROMPT + system_suffix},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = _strip_outer_fence(response.choices[0].message.content)
        title = self._extract_title(content, idea)

        logger.info("PRD 生成完成", title=title)

        return {"title": title, "content": content}

    async def _generate_edit(
        self, idea: str, rerun_instruction: str, previous_prd: str,
    ) -> dict:
        logger.info(
            "PRD 编辑模式生成",
            model=self.model,
            prev_len=len(previous_prd),
            instruction_preview=rerun_instruction[:80],
        )

        edit_system = PRD_SYSTEM_PROMPT + (
            "\n\n本次为编辑模式：基于「上一版 PRD」做最小化修改，"
            "保留所有未被反馈触及的章节、措辞、列表项原样不变。"
            "禁止重新生成整篇文档。"
        )

        user_prompt = f"""# ⚠️ 重跑指令（最高优先级，必须严格执行）

{rerun_instruction}

执行约束：
1. 这是对「上一版 PRD」的最小化修改：未被反馈触及的章节、句子、列表项必须**逐字保留**。
2. 仅按反馈调整与之相关的部分；与反馈冲突的旧写法直接覆写。
3. 不要重新组织文档结构；不要更换措辞风格；不要补充未被要求的新内容。
4. 输出"修改后的完整 Markdown"——不是 diff、不是片段、不要外层 ``` 围栏。

---

## 产品 Idea
{idea}

## 上一版 PRD（在此基础上做最小修改）

{previous_prd}

请输出修改后的完整 PRD。"""

        response = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=8000,
            temperature=0.2,
            messages=[
                {"role": "system", "content": edit_system},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = _strip_outer_fence(response.choices[0].message.content)
        title = self._extract_title(content, idea)
        logger.info("PRD 编辑模式生成完成", title=title)
        return {"title": title, "content": content}

    def _format_competitors(self, competitors: list[dict]) -> str:
        if not competitors:
            return "未找到直接竞品。"
        lines = []
        for c in competitors:
            lines.append(f"- **{c['title']}** ({c['url']})\n  {c['summary']}")
        return "\n".join(lines)

    def _extract_title(self, content: str, fallback_idea: str) -> str:
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return f"{fallback_idea[:50]} — 产品需求文档"
