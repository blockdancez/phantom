# Codex 产品体验 Runner 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `experience_products` cron 的实现从「LangGraph + Playwright + ChatOpenAI(gpt-4o)」替换成「调本地 `codex exec` 子进程，让 codex 通过已注册的 chrome-devtools MCP 真实操作浏览器深度体验产品，结束后从约定目录读取 markdown 报告」。

**Architecture:**
- 新增 `src/product_experience/codex_runner.py` 提供 `run_codex_experience(...)`，与旧 `run_experience_agent` 同形（输入参数、返回 `ExperienceRunResult` dataclass），让 `_run_experience_impl` 几乎无改动地切换。
- `codex exec` 用 `--full-auto --skip-git-repo-check --cd <work_dir>` 在独立工作目录跑；prompt 里**强约束**输出位置（`<work_dir>/REPORT.md`、`<work_dir>/screenshots/<name>.png`）和报告段落（与现有 `parse_agent_report` 完全一致）。
- 父进程 `asyncio.create_subprocess_exec` + `wait_for(timeout=480)`；exit code 0 = 成功，否则 `failed`；超时 → `terminate()` + `failed`。
- 旧 LangGraph 体系（`graph.py / prompts.py / tools.py / browser.py / google_login.py` 及对应 5 个测试文件）整体删除。`extractor.py` 完全保留（段落规约不变）。

**Tech Stack:**
- Python 3.12 / asyncio.subprocess
- Codex CLI: `/Applications/Codex.app/Contents/Resources/codex`，子命令 `codex exec`
- 已配置的 MCP: `chrome-devtools` / `playwright`（来自 `~/.codex/config.toml`）
- pytest + asyncio

---

## File Structure

**新建：**
- `backend/src/product_experience/codex_runner.py` — 子进程 wrapper 与报告读取
- `backend/tests/test_product_experience/test_codex_runner.py` — 单测（mock subprocess + 文件系统）

**修改：**
- `backend/src/scheduler/jobs.py:316-429` — `_run_experience_impl`：把 `run_experience_agent` 改成 `run_codex_experience`，移除 `requires_login` 入参传递（codex prompt 里仍可使用），其余流程不变
- `backend/src/config.py` — 新增 `codex_binary_path: str = "codex"` 与 `codex_experience_root: str = "data/codex_experience"`，使路径不写死

**删除（YAGNI，不保留 fallback）：**
- `backend/src/product_experience/graph.py`
- `backend/src/product_experience/prompts.py`
- `backend/src/product_experience/tools.py`
- `backend/src/product_experience/browser.py`
- `backend/src/product_experience/google_login.py`
- `backend/tests/test_product_experience/test_browser.py`
- `backend/tests/test_product_experience/test_google_login.py`
- `backend/tests/test_product_experience/test_tools.py`

**不动：**
- `backend/src/product_experience/extractor.py`（段落规约就是 codex prompt 的输出契约）
- `backend/tests/test_product_experience/test_extractor.py`
- `backend/src/models/product_experience_report.py`

---

## Task 1: 新增 codex prompt 模板与目录工具

**Files:**
- Create: `backend/src/product_experience/codex_runner.py`
- Test: `backend/tests/test_product_experience/test_codex_runner.py`

- [ ] **Step 1: 写失败测试 — prompt 包含必要约束**

文件 `backend/tests/test_product_experience/test_codex_runner.py`，全文：

```python
"""单测 codex_runner: subprocess wrapper + 报告读取 + 错误分类。

不真跑 codex —— mock asyncio.create_subprocess_exec 与文件系统。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.product_experience.codex_runner import (
    ExperienceRunResult,
    build_codex_prompt,
    run_codex_experience,
)


def test_build_prompt_contains_all_constraints():
    prompt = build_codex_prompt(
        product_name="Toolify",
        product_url="https://toolify.ai",
        requires_login=True,
        work_dir=Path("/tmp/exp/abc"),
    )
    # 输入参数必须出现
    assert "Toolify" in prompt
    assert "https://toolify.ai" in prompt
    assert "true" in prompt.lower()  # requires_login=true
    # 输出位置约定
    assert "/tmp/exp/abc/REPORT.md" in prompt
    assert "/tmp/exp/abc/screenshots" in prompt
    # 段落必须与 extractor 期望严格对齐
    for h in ("## 概览", "## 登录情况", "## 功能盘点",
              "## 优点", "## 缺点", "## 商业模式",
              "## 目标用户", "## 综合体验分"):
        assert h in prompt
    # 必须显式提示用 chrome-devtools MCP（而非自己 fetch HTML）
    assert "chrome-devtools" in prompt
```

- [ ] **Step 2: 跑测试，看到 ImportError**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest tests/test_product_experience/test_codex_runner.py::test_build_prompt_contains_all_constraints -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'src.product_experience.codex_runner'`

- [ ] **Step 3: 写最小实现**

文件 `backend/src/product_experience/codex_runner.py`：

```python
"""把产品体验 run 委托给本地 codex exec 子进程。

codex 通过 ~/.codex/config.toml 已注册的 chrome-devtools MCP 真实驱动
浏览器；本模块只负责拼 prompt、起子进程、收报告与截图、错误分类。

输出契约（必须与 src.product_experience.extractor 的段落 100% 一致）：
- ## 概览 / ## 登录情况 / ## 功能盘点 / ## 优点 / ## 缺点 /
  ## 商业模式 / ## 目标用户 / ## 综合体验分
"""
from __future__ import annotations

import asyncio
import shutil
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


_PROMPT_TEMPLATE = """你是一个深度产品体验分析师，正在体验下面这个产品。

# 输入
- 产品: {product_name}
- 入口 URL: {product_url}
- 是否需要登录: {requires_login}

# 必须使用的工具
通过 **chrome-devtools** MCP 工具组打开浏览器并真实交互（navigate / take_snapshot / click / fill_form / take_screenshot / list_console_messages）。**禁止用 curl 或 fetch 抓 HTML 代替真实浏览**——我们要的是用户视角的体验，不是 raw DOM。

# 工作流（严格按顺序）
1. 用 chrome-devtools 的 `new_page` 打开入口 URL
2. `take_screenshot` 存到 `{work_dir}/screenshots/landing.png`
3. `take_snapshot` 看页面结构，判断产品在做什么
4. 如果 requires_login=true：尝试找 "Sign in with Google" 按钮并点击。成功跳到 Google 登录页就视为 google；找不到/失败就视为 failed；requires_login=false 时本字段填 skipped；未尝试登录直接看营销页则填 none。
5. 找出主导航里 3-6 个最有信息量的链接（features / pricing / docs / blog / about），逐个 navigate + take_screenshot（命名 features.png / pricing.png 等存到同一 screenshots 目录）+ take_snapshot 看内容
6. 写最终报告到 `{work_dir}/REPORT.md`，**纯 markdown**，**严格按下面字段顺序与名称**，不要加额外章节：

```
# 产品体验报告

## 概览
<2-4 句中文，说明产品在做什么，目标用户是谁>

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
<0-100 整数>
```

# 铁律
- 不要瞎编你没看到的功能。`## 功能盘点` 必须基于 take_snapshot 看到的内容。
- 报告写完后**必须**确保文件落在 `{work_dir}/REPORT.md`（绝对路径，不要写到别处）。
- 整次 session 最多 25 步浏览器操作。
- 写完 REPORT.md 就停下，不要继续编辑或 commit。
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


async def run_codex_experience(
    *,
    slug: str,
    name: str,
    url: str,
    requires_login: bool,
    report_id: str,
    base_dir: Path,
    codex_binary: str = "codex",
    timeout_seconds: int = 480,
) -> ExperienceRunResult:
    """Spawn `codex exec` against a per-run work_dir, wait, read REPORT.md."""
    raise NotImplementedError  # 后续 task 填充
```

- [ ] **Step 4: 跑测试，预期通过**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest tests/test_product_experience/test_codex_runner.py::test_build_prompt_contains_all_constraints -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/src/product_experience/codex_runner.py backend/tests/test_product_experience/test_codex_runner.py
git commit -m "feat(product-experience): codex prompt template + skeleton runner"
```

---

## Task 2: 子进程 spawn + REPORT.md 读取（happy path）

**Files:**
- Modify: `backend/src/product_experience/codex_runner.py`
- Modify: `backend/tests/test_product_experience/test_codex_runner.py`

- [ ] **Step 1: 写失败测试 — happy path**

追加到 `test_codex_runner.py` 末尾：

```python
@pytest.mark.asyncio
async def test_run_codex_experience_happy_path(tmp_path: Path):
    """codex 退出码 0 + REPORT.md 存在 → status=completed, markdown 回填。"""
    base_dir = tmp_path / "experience"

    sample_md = (
        "# 产品体验报告\n\n## 概览\nFakeProduct 是一个测试产品。\n\n"
        "## 登录情况\ngoogle\n\n## 功能盘点\n- F: P | N\n\n"
        "## 优点\n好。\n\n## 缺点\n差。\n\n"
        "## 商业模式\n订阅。\n\n## 目标用户\n开发者。\n\n"
        "## 综合体验分\n75\n"
    )

    captured: dict[str, Any] = {}

    async def fake_subprocess_exec(*args, **kwargs):
        # 真实 codex 命令应以 "codex" + "exec" 开头
        captured["argv"] = list(args)
        captured["cwd"] = kwargs.get("cwd")
        # 模拟 codex 把报告写出去
        work_dir = Path(kwargs["cwd"])
        (work_dir / "REPORT.md").write_text(sample_md, encoding="utf-8")
        (work_dir / "screenshots").mkdir(exist_ok=True)
        (work_dir / "screenshots" / "landing.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
        proc.wait = AsyncMock(return_value=0)
        return proc

    with patch(
        "src.product_experience.codex_runner.asyncio.create_subprocess_exec",
        new=fake_subprocess_exec,
    ):
        result = await run_codex_experience(
            slug="fake",
            name="FakeProduct",
            url="https://fake.test",
            requires_login=True,
            report_id="abc123",
            base_dir=base_dir,
            codex_binary="codex",
            timeout_seconds=10,
        )

    # 命令构造正确
    assert captured["argv"][0] == "codex"
    assert captured["argv"][1] == "exec"
    assert "--full-auto" in captured["argv"]
    assert "--skip-git-repo-check" in captured["argv"]
    # 工作目录是 base_dir/<report_id>
    assert captured["cwd"].endswith("abc123")

    # 返回值
    assert isinstance(result, ExperienceRunResult)
    assert "FakeProduct 是一个测试产品" in result.markdown
    assert result.login_status == "google"
    assert len(result.screenshots) == 1
    assert result.screenshots[0]["name"] == "landing"
    assert result.screenshots[0]["path"].endswith("landing.png")
    assert "stdout" in result.trace
```

- [ ] **Step 2: 跑测试，看到 NotImplementedError**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest tests/test_product_experience/test_codex_runner.py::test_run_codex_experience_happy_path -v`

Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: 实现 happy path 逻辑**

替换 `codex_runner.py` 中的 `run_codex_experience` 函数体（保留 import / dataclass / template / build_codex_prompt 不变）：

```python
def _collect_screenshots(work_dir: Path) -> list[dict[str, Any]]:
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
        out.append({"name": p.stem, "path": str(p), "taken_at": ts})
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
    timeout_seconds: int = 480,
) -> ExperienceRunResult:
    work_dir = Path(base_dir) / report_id
    (work_dir / "screenshots").mkdir(parents=True, exist_ok=True)

    prompt = build_codex_prompt(
        product_name=name,
        product_url=url,
        requires_login=requires_login,
        work_dir=work_dir,
    )

    argv = [
        codex_binary,
        "exec",
        "--full-auto",
        "--skip-git-repo-check",
        "--cd",
        str(work_dir),
        prompt,
    ]
    logger.info(
        "codex_experience_spawn",
        slug=slug,
        report_id=report_id,
        work_dir=str(work_dir),
        timeout=timeout_seconds,
    )

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(work_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_bytes, stderr_bytes = await asyncio.wait_for(
        process.communicate(), timeout=timeout_seconds
    )
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    report_path = work_dir / "REPORT.md"
    if process.returncode != 0 or not report_path.is_file():
        logger.warning(
            "codex_experience_no_report",
            slug=slug,
            returncode=process.returncode,
            report_exists=report_path.is_file(),
        )
        return ExperienceRunResult(
            markdown="",
            login_status="failed",
            screenshots=_collect_screenshots(work_dir),
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
        screenshots=_collect_screenshots(work_dir),
        trace={
            "returncode": 0,
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
        },
    )
```

- [ ] **Step 4: 跑测试，预期通过**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest tests/test_product_experience/test_codex_runner.py -v`

Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/product_experience/codex_runner.py backend/tests/test_product_experience/test_codex_runner.py
git commit -m "feat(product-experience): spawn codex exec, read REPORT.md, collect screenshots"
```

---

## Task 3: 超时与失败分支

**Files:**
- Modify: `backend/src/product_experience/codex_runner.py`
- Modify: `backend/tests/test_product_experience/test_codex_runner.py`

- [ ] **Step 1: 写失败测试 — codex 进程超时**

追加到 `test_codex_runner.py`：

```python
@pytest.mark.asyncio
async def test_run_codex_experience_timeout_kills_process(tmp_path: Path):
    """timeout → terminate() + 返回 status_failed-friendly 结果。"""
    base_dir = tmp_path / "experience"

    proc = MagicMock()
    proc.returncode = None  # 仍在跑
    proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
    proc.terminate = MagicMock()
    proc.wait = AsyncMock(return_value=-15)

    async def fake_subprocess_exec(*args, **kwargs):
        return proc

    with patch(
        "src.product_experience.codex_runner.asyncio.create_subprocess_exec",
        new=fake_subprocess_exec,
    ):
        # 内部 wait_for 抛 TimeoutError 由我们捕获
        result = await run_codex_experience(
            slug="fake",
            name="FakeProduct",
            url="https://fake.test",
            requires_login=False,
            report_id="t1",
            base_dir=base_dir,
            timeout_seconds=1,
        )

    proc.terminate.assert_called_once()
    assert result.markdown == ""
    assert result.login_status == "failed"
    assert result.trace["reason"] == "timeout"


@pytest.mark.asyncio
async def test_run_codex_experience_no_report_when_codex_exits_clean(tmp_path: Path):
    """codex 退出 0 但忘了写 REPORT.md → 视为失败，trace 标 reason。"""
    base_dir = tmp_path / "experience"

    async def fake_subprocess_exec(*args, **kwargs):
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    with patch(
        "src.product_experience.codex_runner.asyncio.create_subprocess_exec",
        new=fake_subprocess_exec,
    ):
        result = await run_codex_experience(
            slug="fake",
            name="FakeProduct",
            url="https://fake.test",
            requires_login=False,
            report_id="t2",
            base_dir=base_dir,
            timeout_seconds=10,
        )

    assert result.markdown == ""
    assert result.login_status == "failed"
    assert result.trace["reason"] == "no_report_or_nonzero_exit"
```

- [ ] **Step 2: 跑测试，看到 timeout 测试 fail**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest tests/test_product_experience/test_codex_runner.py -v`

Expected: 第一个新测试 FAIL（timeout 抛出未捕获），第二个可能 PASS（已被 happy-path 实现覆盖）。

- [ ] **Step 3: 加超时捕获**

修改 `codex_runner.py` 中 `run_codex_experience`，把 `await asyncio.wait_for(process.communicate(), ...)` 段落替换为：

```python
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except asyncio.TimeoutError:
        logger.warning(
            "codex_experience_timeout",
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
            screenshots=_collect_screenshots(work_dir),
            trace={
                "returncode": process.returncode,
                "reason": "timeout",
                "timeout_seconds": timeout_seconds,
            },
        )
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
```

- [ ] **Step 4: 跑全部新测试**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest tests/test_product_experience/test_codex_runner.py -v`

Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/product_experience/codex_runner.py backend/tests/test_product_experience/test_codex_runner.py
git commit -m "feat(product-experience): codex runner timeout + missing-report failure paths"
```

---

## Task 4: 配置项 + 删除旧 Playwright/LangGraph 实现

**Files:**
- Modify: `backend/src/config.py`
- Delete: `backend/src/product_experience/graph.py`
- Delete: `backend/src/product_experience/prompts.py`
- Delete: `backend/src/product_experience/tools.py`
- Delete: `backend/src/product_experience/browser.py`
- Delete: `backend/src/product_experience/google_login.py`
- Delete: `backend/tests/test_product_experience/test_browser.py`
- Delete: `backend/tests/test_product_experience/test_google_login.py`
- Delete: `backend/tests/test_product_experience/test_tools.py`

- [ ] **Step 1: 加配置项**

编辑 `backend/src/config.py`，把 `Settings` 类加两行（放在 `experience_headless` 那行之后）：

```python
    codex_binary_path: str = "codex"
    codex_experience_root: str = "data/codex_experience"
```

- [ ] **Step 2: 删旧文件**

```bash
rm backend/src/product_experience/graph.py
rm backend/src/product_experience/prompts.py
rm backend/src/product_experience/tools.py
rm backend/src/product_experience/browser.py
rm backend/src/product_experience/google_login.py
rm backend/tests/test_product_experience/test_browser.py
rm backend/tests/test_product_experience/test_google_login.py
rm backend/tests/test_product_experience/test_tools.py
```

- [ ] **Step 3: 跑全部测试，确认旧引用已不在主链路上**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest -q --deselect tests/test_config.py::test_config_requires_database_url 2>&1 | tail -20`

Expected: 仅 `tests/test_scheduler_run_analysis.py` / `tests/test_processors/...` / `tests/test_product_experience/test_extractor.py` / `tests/test_product_experience/test_codex_runner.py` 等还跑；旧 `test_browser` / `test_google_login` / `test_tools` 不再出现；scheduler 路径会因 `_run_experience_impl` 仍 import `run_experience_agent` 失败 — 这是预期失败，下一 task 修。

如果出现非预期的 import 错（如 `_run_experience_impl` 之外的代码引用旧模块），到对应文件删除该 import。

- [ ] **Step 4: 提交（半成品状态，下一 task 修复 scheduler）**

```bash
git rm backend/src/product_experience/graph.py \
       backend/src/product_experience/prompts.py \
       backend/src/product_experience/tools.py \
       backend/src/product_experience/browser.py \
       backend/src/product_experience/google_login.py \
       backend/tests/test_product_experience/test_browser.py \
       backend/tests/test_product_experience/test_google_login.py \
       backend/tests/test_product_experience/test_tools.py
git add backend/src/config.py
git commit -m "chore(product-experience): drop LangGraph/Playwright runner and tests"
```

---

## Task 5: scheduler 接入 codex runner

**Files:**
- Modify: `backend/src/scheduler/jobs.py:316-429`（`_run_experience_impl` 函数体）
- Modify: `backend/tests/test_scheduler_run_analysis.py` 或 `tests/test_scheduler/...` 如有 experience 用例

- [ ] **Step 1: 写失败测试 — scheduler 调 codex_runner**

新建 `backend/tests/test_scheduler/test_run_experience.py`（如果 `tests/test_scheduler` 目录不存在则一并创建空 `__init__.py`）：

```python
"""scheduler._run_experience_impl 应：选 candidate → run_codex_experience →
parse_agent_report → 写 ProductExperienceReport 行。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.scheduler import jobs as jobs_module


class _FakeSession:
    def __init__(self, candidate=None):
        self.added: list = []
        self.committed = False
        self._candidate = candidate

    def add(self, obj):
        self.added.append(obj)

    async def get(self, model, key):
        return self._candidate

    async def execute(self, stmt):
        # 第一次返回 candidate，第二次返回 None（fallback 路径用）
        rv = SimpleNamespace(
            scalar_one_or_none=lambda: self._candidate,
        )
        # 把 candidate 置 None 供下一次调用
        self._candidate = None
        return rv

    async def commit(self):
        self.committed = True


class _Ctx:
    def __init__(self, sess):
        self._sess = sess

    async def __aenter__(self):
        return self._sess

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def fake_factory(monkeypatch: pytest.MonkeyPatch):
    candidate = SimpleNamespace(
        id="cid1",
        slug="fake",
        name="FakeProduct",
        homepage_url="https://fake.test",
        last_experienced_at=None,
        experience_count=0,
    )
    sess = _FakeSession(candidate)
    monkeypatch.setattr(
        jobs_module,
        "get_async_session_factory",
        lambda: (lambda: _Ctx(sess)),
    )
    return sess


@pytest.mark.asyncio
async def test_run_experience_writes_row_via_codex_runner(
    fake_factory, monkeypatch: pytest.MonkeyPatch
):
    sample_md = (
        "# 产品体验报告\n\n## 概览\nFakeProduct 是测试产品。\n\n"
        "## 登录情况\ngoogle\n\n## 功能盘点\n- F: P | N\n\n"
        "## 优点\n好。\n\n## 缺点\n差。\n\n"
        "## 商业模式\n订阅。\n\n## 目标用户\n开发者。\n\n"
        "## 综合体验分\n75\n"
    )
    from src.product_experience.codex_runner import ExperienceRunResult

    async def fake_run(**kw):
        return ExperienceRunResult(
            markdown=sample_md,
            login_status="google",
            screenshots=[{"name": "landing", "path": "/x/landing.png", "taken_at": "t"}],
            trace={"returncode": 0},
        )

    import src.product_experience.codex_runner as cr
    monkeypatch.setattr(cr, "run_codex_experience", fake_run)

    await jobs_module._run_experience_impl()

    assert len(fake_factory.added) == 1
    row = fake_factory.added[0]
    assert row.product_slug == "fake"
    assert row.status == "completed"
    assert row.login_used == "google"
    assert row.overall_ux_score == 75.0
    assert row.summary_zh and "FakeProduct" in row.summary_zh
```

- [ ] **Step 2: 跑测试，看到失败**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest tests/test_scheduler/test_run_experience.py -v`

Expected: FAIL — `_run_experience_impl` 仍 import `run_experience_agent` 引发 ImportError（因为 graph.py 已删）。

- [ ] **Step 3: 改 scheduler 实现**

打开 `backend/src/scheduler/jobs.py:331-429`（`_run_experience_impl` 函数）。把：

```python
    from src.product_experience.extractor import parse_agent_report
    from src.product_experience.graph import run_experience_agent
```

改为：

```python
    from src.product_experience.codex_runner import run_codex_experience
    from src.product_experience.extractor import parse_agent_report
    from src.config import Settings
```

把：

```python
        run_result = await asyncio.wait_for(
            run_experience_agent(
                slug=candidate_slug,
                name=candidate_name,
                url=candidate_url,
                requires_login=True,
                report_id=report_id,
            ),
            timeout=480,  # 8 minutes
        )
        parsed = parse_agent_report(run_result.markdown)
```

改为：

```python
        settings = Settings()  # type: ignore[call-arg]
        from pathlib import Path
        run_result = await run_codex_experience(
            slug=candidate_slug,
            name=candidate_name,
            url=candidate_url,
            requires_login=True,
            report_id=report_id,
            base_dir=Path(settings.codex_experience_root),
            codex_binary=settings.codex_binary_path,
            timeout_seconds=480,
        )
        parsed = parse_agent_report(run_result.markdown)
```

注意：`run_codex_experience` 内部已自带 timeout，外层不再用 `asyncio.wait_for`。也因此不会再触发 `TimeoutError` —— 把原来 `except TimeoutError:` 分支保留（兜底），但其触发概率为 0。也可以删，留着对兼容性更稳。

- [ ] **Step 4: 跑测试**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest tests/test_scheduler/test_run_experience.py tests/test_product_experience/ -v`

Expected: 全部 PASS

- [ ] **Step 5: 跑全量回归**

Run: `cd backend && AI_IDEA_FINDER_SKIP_KEY_CHECK=1 python3 -m pytest -q --deselect tests/test_config.py::test_config_requires_database_url 2>&1 | tail -10`

Expected: 全部 PASS（排除已知 pre-existing config 测试）。

- [ ] **Step 6: 提交**

```bash
git add backend/src/scheduler/jobs.py backend/tests/test_scheduler/test_run_experience.py backend/tests/test_scheduler/__init__.py
git commit -m "feat(product-experience): wire scheduler to codex runner"
```

---

## Task 6: 端到端冒烟（实跑一次 codex）

**Files:**
- 不改代码，仅手工触发 + 观察。

- [ ] **Step 1: 重启后端确保新代码加载**

```bash
PID=$(lsof -nP -iTCP:53839 -sTCP:LISTEN -t 2>/dev/null); [ -n "$PID" ] && kill "$PID"; sleep 2
cd /Users/lapsdoor/workspace/claude/phantom/AIIdea && unset DATABASE_URL && ./scripts/start-backend.sh &
```

等 `/api/health` 返回 `{db:ok, scheduler:ok}`：

```bash
until curl -sf http://localhost:53839/api/health -o /dev/null; do sleep 2; done && curl -s http://localhost:53839/api/health
```

Expected: `{"code":"000000",...,"data":{"status":"ok","db":"ok","scheduler":"ok"}}`

- [ ] **Step 2: 触发一次 experience_products**

```bash
curl -X POST http://localhost:53839/api/pipeline/trigger/experience_products
```

Expected: `{"code":"000000",...,"data":{"status":"triggered",...}}`

- [ ] **Step 3: 观察 codex 子进程**

新开 terminal：

```bash
ps -ef | grep -E "codex (exec|exec )" | grep -v grep
```

Expected: 看到一个 `codex exec --full-auto --skip-git-repo-check --cd .../data/codex_experience/<uuid>` 进程在跑。

- [ ] **Step 4: 等 codex 完成，看产物**

```bash
ls -la backend/data/codex_experience/$(ls -t backend/data/codex_experience | head -1)/
```

Expected: 看到 `REPORT.md` 与 `screenshots/*.png`。

- [ ] **Step 5: 校验数据库行**

```bash
python3 -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    eng = create_async_engine('postgresql+asyncpg://postgres:yqd9PX20WhcETsx2@8.138.217.250:5432/ai_idea_finder')
    async with eng.connect() as c:
        r = await c.execute(text('SELECT product_name, status, overall_ux_score, login_used FROM product_experience_reports ORDER BY run_started_at DESC LIMIT 1'))
        print(r.fetchone())
asyncio.run(main())
"
```

Expected: 一行新数据，`status='completed'`，`overall_ux_score` 在 0-100 之间，`product_name` 是被选中的候选产品。

- [ ] **Step 6: 概览页校验**

打开 http://localhost:53840/。Expected: "产品体验" section 的"累计体验报告"+1，最新 3 条里出现这条。

- [ ] **Step 7: 提交**

无新代码改动，仅文档。如果 Step 5 / 6 暴露问题再回 Task 5 修。

```bash
git commit --allow-empty -m "test: smoke-test codex experience runner end-to-end"
```

---

## 自检结果

**Spec coverage：**
- 1 (codex CLI) → Task 2 用 `codex exec` 子进程
- 2 (chrome-devtools MCP) → Task 1 prompt 显式约束 "通过 chrome-devtools MCP"
- 3 (输入输出在 prompt) → Task 1 prompt 模板把 `work_dir/REPORT.md` 与 `screenshots/` 写死
- 4 (exit 0 完成) → Task 2 / 3 实现按 returncode + REPORT.md 双重判定
- 5 (报告格式与 extractor 一致) → Task 1 prompt 8 个段落硬编码与 `_split_sections` 对齐
- 6 (旧路径整体删) → Task 4 删 5 个源文件 + 3 个测试文件

**Placeholder 扫查：** 无 TBD/TODO；每个 step 都有完整代码或具体命令。

**类型一致性：** `ExperienceRunResult` 的字段（markdown / login_status / screenshots / trace）在 Task 1（dataclass）/ Task 2（实例化）/ Task 5（scheduler 消费）三处一致，与旧 `ExperienceRunResult` 字段同名同型。
