"""把产品体验 run 委托给本地 codex exec 子进程。

codex 通过 ~/.codex/config.toml 已注册的 chrome-devtools MCP 真实驱动
浏览器；本模块只负责拼 prompt、起子进程、收报告与截图、错误分类。

输出契约（必须与 src.product_experience.extractor 的段落 100% 一致）：
- ## 概览 / ## 登录情况 / ## 功能盘点 / ## 优点 / ## 缺点 /
  ## 商业模式 / ## 目标用户 / ## 综合体验分
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class ExperienceRunResult:
    """与旧 run_experience_agent 返回字段一一对应，方便 _run_experience_impl 切换。"""

    markdown: str
    login_status: str  # google | none | failed | skipped
    screenshots: list[dict[str, Any]]
    trace: dict[str, Any]


_PROMPT_TEMPLATE = """你是一个产品研究员，正在为一个独立开发者体验下面这个产品，目的是**借鉴它的思路和功能去做一些创新和差异化**——不是照抄，而是从中得到启发，在它的基础上想清楚"我可以怎么做得不一样、怎么补它的短板"。

# 输入
- 产品: {product_name}
- 入口 URL: {product_url}
- 是否需要登录: {requires_login}

# 必须使用的工具
通过 **chrome-devtools** MCP 工具组打开浏览器并真实交互（navigate / take_snapshot / click / fill_form / take_screenshot / list_console_messages）。**禁止用 curl 或 fetch 抓 HTML 代替真实浏览**——我们要的是用户视角的体验。

# 思考要求（写报告前必须想清楚）
1. **产品在做什么**（功能层）
2. **为什么这样做**（用户在用之前用什么、用了之后变了什么；产品的核心理念）
3. **服务谁**（具体到 persona / 场景 / 痛点，不要"所有人"/"中小企业"这种泛称）
4. **它的局限/盲点**（什么人/场景没被满足、什么功能体验差、什么用例覆盖不到）
5. **我能在哪里做不一样**（用户场景拓展 / AI 增强 / 协作模式 / 商业模式 / 工作流简化 等维度）

# 工作流（严格按顺序）
1. `new_page` 打开入口 URL
2. `take_screenshot` 存到 `{work_dir}/screenshots/landing.png`
3. `take_snapshot` 看主页结构，理解产品定位和核心卖点
4. 如果 requires_login=true：尝试找 "Sign in with Google" 按钮并点击。成功跳到 Google 登录页视为 google；失败视为 failed；requires_login=false 视为 skipped；未尝试视为 none。
5. 找主导航里 3-6 个最有信息量的链接（features / pricing / docs / blog / about），逐个 navigate + take_screenshot + take_snapshot
6. 写最终报告到 `{work_dir}/REPORT.md`，**严格按下面字段顺序**，不要加额外章节：

```
# 产品启发 brief

## 产品理念
<一句话讲清"这个产品的核心理念是什么、用户为什么选它而不是别的"，3-5 句中文。这是借鉴的灵魂——把"它在解决什么本质问题"用一句话说出来>

## 目标用户画像
```yaml
persona: <一句话画像，含角色 + 场景 + 关键属性，例：在中小型 SaaS 公司做 lifecycle marketing 的运营经理>
scenarios:
  - <典型使用场景 1>
  - <典型使用场景 2>
  - <典型使用场景 3>
pain_points:
  - <用这个产品之前用户在面对什么具体痛点>
  - <...>
why_this_product: <用户为什么选它而不是竞品（核心吸引力）>
```

## 核心功能（含设计意图）
```yaml
- name: <功能名>
  priority: must  # must | should | nice，相对于这个产品的核心价值看必备程度
  where_seen: <在哪个页面/入口看到>
  rationale: <这个功能背后的产品思路——为什么做这个、它在为用户解决什么、和别的产品有什么不同>
- name: <功能名>
  priority: should
  where_seen: <...>
  rationale: <...>
（列 4-8 条核心功能，按 must → should → nice 排序）
```

## 差异化机会
```yaml
- observation: <这个产品当前的局限/盲点 1>
  opportunity: <我可以怎么补位 / 做更好>
  why_it_matters: <为什么这个改进对用户有价值>
- observation: <局限 2>
  opportunity: <...>
  why_it_matters: <...>
（列 3-6 条；这是这份 brief 最重要的输出，要具体可执行，不要泛泛"做得更好"）
```

## 创新切入点
```yaml
- angle: 用户场景拓展  # 也可以是: AI 增强 / 协作模式 / 商业模式 / 工作流简化 / 数据资产 / 集成生态
  hypothesis: <一句话假设：在这个维度做创新会带来什么价值>
  examples:
    - <具体可落地的功能例子 1>
    - <具体可落地的功能例子 2>
- angle: AI 增强
  hypothesis: <...>
  examples:
    - <...>
（列 3-5 个 angle；要面向"独立开发者能动手做出来"的尺度，不要画大饼）
```

---

## 附录：原始体验数据

> 以下段落保留旧字段格式以便老报告兼容，新版的核心信息已在上面 5 段中。

## 概览
<2-4 句中文，说明产品在做什么、面向谁>

## 登录情况
<google | none | failed | skipped>

## 功能盘点
- <功能名>: <在哪发现的页面 / 入口> | <一句话备注>
- <功能名>: <在哪发现的页面 / 入口> | <一句话备注>
（列 4-10 条）

## 优点
<3-6 句，列举亮点>

## 缺点
<3-6 句，列举体验问题>

## 商业模式
<免费 + 订阅 / 一次性付费 / 企业销售 / 广告 / 其它，写出推断依据>

## 目标用户
<2-3 句，画一个 ICP 的用户像>

## 综合体验分
<0-10 一位小数（与创意 IDEA 评分对齐；如：7.5）>
```

# 铁律
- 不要瞎编你没看到的功能。所有 ## 功能盘点 / ## 核心功能 都必须基于 take_snapshot 实际看到的内容。
- yaml 块用三个反引号 + yaml 包裹，**严格 yaml 语法**：键: 值，多行字符串必须缩进对齐，不要多余引号
- 差异化机会和创新切入点要**具体到一个独立开发者能上手的颗粒度**，不要写"提升用户体验"这种万金油
- 报告写完后**必须**确保文件落在 `{work_dir}/REPORT.md`（绝对路径，不要写到别处）
- 整次 session 最多 25 步浏览器操作
- 写完 REPORT.md 就停下，不要继续编辑或 commit
"""


def build_codex_prompt(
    *, product_name: str, product_url: str, requires_login: bool, work_dir: Path
) -> str:
    return _PROMPT_TEMPLATE.format(
        product_name=product_name,
        product_url=product_url,
        requires_login=str(requires_login).lower(),
        work_dir=str(work_dir),
    )


def _collect_screenshots(work_dir: Path, base_dir: Path) -> list[dict[str, Any]]:
    """Return screenshot metadata with a *relative* ``path`` rooted at the
    codex_experience base — that's what the frontend ScreenshotGallery
    appends to ``/static/codex/`` (mounted in main.py to base_dir). Storing
    an absolute filesystem path here would 404 the browser and leak local
    paths into the API response.
    """
    shots_dir = work_dir / "screenshots"
    if not shots_dir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(shots_dir.iterdir()):
        if p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        try:
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            ts = datetime.now(tz=timezone.utc).isoformat()
        try:
            rel = p.relative_to(base_dir)
        except ValueError:
            # Defensive: shot landed outside base_dir somehow — fall back to
            # absolute path so we don't drop it from the gallery.
            rel = p
        out.append({"name": p.stem, "path": str(rel), "taken_at": ts})
    return out


_LOGIN_TOKENS = {"google", "none", "failed", "skipped"}


def _extract_login_status(markdown: str) -> str:
    """从报告里抠出 ## 登录情况 段落第一行。容错：找不到 → none。"""
    import re

    m = re.search(r"^##\s+登录情况\s*$", markdown, re.MULTILINE)
    if not m:
        return "none"
    tail = markdown[m.end():].lstrip().splitlines()
    if not tail:
        return "none"
    token = tail[0].strip().lower()
    return token if token in _LOGIN_TOKENS else "none"


async def run_codex_experience(
    *,
    slug: str,
    name: str,
    url: str,
    requires_login: bool,
    report_id: str,
    base_dir: Path,
    codex_binary: str = "codex",
    timeout_seconds: int = 600,
) -> ExperienceRunResult:
    """Spawn `codex exec` against a per-run work_dir, wait, read REPORT.md."""
    base_resolved = Path(base_dir).resolve()
    work_dir = (base_resolved / report_id).resolve()
    (work_dir / "screenshots").mkdir(parents=True, exist_ok=True)

    prompt = build_codex_prompt(
        product_name=name,
        product_url=url,
        requires_login=requires_login,
        work_dir=work_dir,
    )

    # codex 接受 stdin 作为 prompt（CLI 文档：If `-` is used, instructions
    # are read from stdin）。把 prompt 走 stdin 比走 argv 稳：避免长度限制、
    # shell 引号转义、含 ` $ ` 等敏感符号被解释。
    # `--full-auto` 只对 shell 命令自动批准；MCP 工具（chrome-devtools 的
    # navigate / take_snapshot 等）仍会触发交互审批，在非交互的 codex exec
    # 环境下立即被取消（"user cancelled MCP tool call"）。
    # `--dangerously-bypass-approvals-and-sandbox` 跳过包括 MCP 在内的全部
    # 批准；prompt 是我们自己控制的，运行环境也是受信任的开发机。
    argv = [
        codex_binary,
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--skip-git-repo-check",
        "--cd",
        str(work_dir),
        "-",
    ]
    logger.info(
        "Codex 体验进程启动",
        slug=slug,
        report_id=report_id,
        work_dir=str(work_dir),
        timeout=timeout_seconds,
    )

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(work_dir),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(input=prompt.encode("utf-8")),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Codex 体验超时",
            slug=slug,
            timeout=timeout_seconds,
        )
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
        return ExperienceRunResult(
            markdown="",
            login_status="failed",
            screenshots=_collect_screenshots(work_dir, base_resolved),
            trace={
                "returncode": process.returncode,
                "reason": "timeout",
                "timeout_seconds": timeout_seconds,
            },
        )
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    report_path = work_dir / "REPORT.md"
    if process.returncode != 0 or not report_path.is_file():
        logger.warning(
            "Codex 体验无报告",
            slug=slug,
            returncode=process.returncode,
            report_exists=report_path.is_file(),
        )
        return ExperienceRunResult(
            markdown="",
            login_status="failed",
            screenshots=_collect_screenshots(work_dir, base_resolved),
            trace={
                "returncode": process.returncode,
                "stdout": stdout[-4000:],
                "stderr": stderr[-4000:],
                "reason": "no_report_or_nonzero_exit",
            },
        )

    markdown = report_path.read_text(encoding="utf-8")
    login_status = _extract_login_status(markdown) if requires_login else "skipped"

    return ExperienceRunResult(
        markdown=markdown,
        login_status=login_status,
        screenshots=_collect_screenshots(work_dir, base_resolved),
        trace={
            "returncode": 0,
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
        },
    )
