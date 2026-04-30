# Phantom 三模式接入 AIJuicer 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 aijuicer-sdk 写三个 worker agent（`ai-plan` / `ai-design` / `ai-devtest`），让 AIJuicer 的 `plan` / `design` / `devtest` 三个 step 调用 phantom 的对应模式实际工作，替换掉 `AIJuicer/sdk/examples/` 下的 mock 占位。

**Architecture:** 每个 agent 是一个常驻 Python 进程，通过 `aijuicer_sdk.Agent` 注册到 scheduler。收到任务时 `cd` 到 `/Users/lapsdoor/phantom/<project_name>`（`project_name` 由 AIJuicer 在 `task["input"]["project_name"]` 中下发，idea / requirement step 已经把产物落在这个目录里），用 `asyncio.create_subprocess_exec` 调 `phantom` 命令对应模式（`--plan` / `--design` / `--dev-test`），首跑用初始需求，重跑时把 `task["input"]["user_feedback"][step]` 透传给 phantom 作为增量需求。phantom 把所有产物写到 `<workspace>/.phantom/`，agent 跑完后 `save_artifact` 把关键产物上传给 scheduler（`plan.md` / `ui-design.md` / `code` 等）。

**Tech Stack:** Python 3.12+、aijuicer-sdk 0.4.x、phantom CLI（已安装为 `/usr/local/bin/phantom`）、asyncio subprocess、pytest（含 pytest-asyncio）

---

## 关键背景（前置阅读）

实施者必读，否则会迷失：

1. **AIJuicer 工作流目录约定**：AIJuicer 把每个 workflow 的 `project_name` 通过 `task["input"]["project_name"]` 下发，phantom agent 把工作目录定为 **`/Users/lapsdoor/phantom/<project_name>`**（写死的 base + 动态 project_name）。idea/requirement step 已经在这个目录下写过 `idea.md` / `requirement.md`。**所有 phantom agent 都 cd 到这个目录跑命令**，phantom 会在它的 `.phantom/` 子目录里管自己的状态。
   - 路径模板：`/Users/lapsdoor/phantom/<project_name>/`
   - 实例路径：`/Users/lapsdoor/phantom/todo-app-2026/`（`task["input"]["project_name"] == "todo-app-2026"`）
   - **base path 在 runner.py 写死成 `Path("/Users/lapsdoor/phantom")`**（用户单机部署，等多机/多用户再抽 env，YAGNI）
   - 注意：`ctx.artifact_root` 是 SDK 给的产物根目录，不是 phantom 工作区——这次方案里**不用** `ctx.artifact_root`，只用 `task["input"]["project_name"]`

2. **Phantom 三模式与 CLI 行为**（必读 `AIDevelop/CLAUDE.md` 的"模式 flag 通用规则"和"行为矩阵"）：
   - `phantom --plan <文件路径>`：在空目录里创建项目并只跑 plan 模式（plan R1→R2→R3→落锁 `.phantom/plan.locked.md`）
   - `phantom --plan "<增量字符串>"`：在已有 phantom 项目里写 `.phantom/amendment.md` + 重跑 plan（保留原 feature 编号 + 追加新 group）
   - `phantom --plan`（无参，已有项目）：纯 refresh，注入 synthetic amendment 保留结构
   - `phantom --design [需求]`：仅 design 模式（R1→R2→R3）。前置：`.phantom/plan.locked.md` 存在
   - `phantom --dev-test [需求]`：dev → code-review → deploy → test 一圈，跳过强制打磨（`PHANTOM_NO_POLISH=1`）。带参时构造 return-packet。前置：plan.locked.md 存在
   - phantom 全部产物落在 cwd 的 `.phantom/`：`plan.locked.md` / `ui-design.md` / `ui-design/<slug>.html` / `changelog.md` / `runtime/{backend,frontend}.{pid,log}` / `port.{backend,frontend}` 等

3. **Mock examples 当前位置**（保留，不删，作为参考）：
   - `AIJuicer/sdk/examples/ai_plan.py`
   - `AIJuicer/sdk/examples/ai_design.py`
   - `AIJuicer/sdk/examples/ai_devtest.py`
   
   这次的真实 agent **写到 phantom 仓库**（`AIDevelop/phantom_agents/`），不动 AIJuicer 仓库。这样 phantom 元工具的发布周期跟它的 agent 适配层在同一个 repo 里。

4. **AIJuicer SDK 的关键 API**（详见 `AIJuicer/sdk/README.md`）：
   - `Agent(name, step, server, redis_url, concurrency=1)` — 构造 agent 进程
   - `@agent.handler async def handle(ctx, task)` — 业务入口
   - `task["input"]["text"]` — 工作流首次输入的需求文本（idea agent 看的）
   - `task["input"]["user_feedback"][step]` — 用户在 UI 点"重新执行 X"时填的指令；**覆盖式**（保留最新一次）
   - `ctx.attempt > 1` 或 `feedback is not None` → 视为重跑
   - `ctx.artifact_root: str` — workflow 工作目录绝对路径
   - `await ctx.heartbeat("xxx")` — 上报进度（SDK 自动 30s 也发一次）
   - `await ctx.save_artifact(key, data, content_type=...)` — 上传产物字节
   - `await ctx.load_artifact(step, key) -> bytes` — 拉上游产物字节
   - `raise FatalError(...)` — 不重试（人工介入）
   - `raise RetryableError(...)` — 自动重试，超 max_retries 转人工

5. **首次输入的来源**：plan agent 不依赖 AIJuicer 的 `task["input"]["text"]` 字段直接读，而是从上游 requirement step 的产物 `requirement.md` 拉（`ctx.load_artifact("requirement", "requirement.md")`）。这符合 AIJuicer "step 之间用 artifact 衔接" 的设计。

---

## 文件结构

新目录 `AIDevelop/phantom_agents/`：

```
phantom_agents/
  pyproject.toml                # 依赖声明：aijuicer-sdk, pytest, pytest-asyncio
  README.md                     # 启动说明（每个 agent 一行命令）
  __init__.py
  runner.py                     # 共用：phantom 子进程调用、心跳泵、错误分类
  ai_plan.py                    # plan agent
  ai_design.py                  # design agent
  ai_devtest.py                 # devtest agent
  scripts/
    start-ai-plan.sh            # nohup 启动脚本
    start-ai-design.sh
    start-ai-devtest.sh
  tests/
    conftest.py                 # pytest-asyncio + tmp workspace fixtures
    test_runner.py              # runner.py 单测
    test_ai_plan.py
    test_ai_design.py
    test_ai_devtest.py
    fakes/
      fake_phantom.sh           # 假 phantom CLI，用于子进程测试
```

**职责切分**：
- `runner.py`：所有 agent 共用的、与 phantom subprocess 打交道的逻辑（命令拼接、子进程管理、stdout 流式心跳、退出码到 SDK 异常的分类）。每个 agent 只剩业务逻辑（决定参数、读输入、保存产物）。
- 三个 `ai_*.py`：每个 < 60 行业务代码（构造 Agent、写 handler、调 runner、保存产物）。
- 测试：每个文件都有对应的 test_*.py；用 `fakes/fake_phantom.sh` 当 phantom 替身（无需真的 claude/codex 后端）。

---

## Task 1：项目骨架（pyproject + 依赖）

**Files:**
- Create: `phantom_agents/pyproject.toml`
- Create: `phantom_agents/__init__.py`
- Create: `phantom_agents/README.md`

- [ ] **Step 1: 写 `pyproject.toml`**

```toml
[project]
name = "phantom-agents"
version = "0.1.0"
description = "AIJuicer worker agents that wrap the phantom CLI for plan/design/devtest steps."
requires-python = ">=3.12"
dependencies = [
  "aijuicer-sdk>=0.4.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: 写 `__init__.py`**

```python
"""Phantom AIJuicer agents — 把 phantom 三模式包装成 AIJuicer 的 plan/design/devtest worker。"""
__version__ = "0.1.0"
```

- [ ] **Step 3: 写 `README.md`**

```markdown
# phantom-agents

把 phantom 的三模式包装成 AIJuicer 的 plan / design / devtest worker。

## 安装

```bash
cd phantom_agents
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

前置：phantom CLI 已装（`./install.sh` 在 phantom 根目录），`phantom` 在 PATH 上。

## 运行（每个 agent 一个进程）

```bash
export AIJUICER_SERVER=http://127.0.0.1:8000
# Redis 让 scheduler 下发即可，不用配
export AIJUICER_ARTIFACT_ROOT=/path/to/aijuicer/var/artifacts
# AI 后端按需配（透传给 phantom）
export PHANTOM_GENERATOR_BACKEND=claude
export PHANTOM_CODE_REVIEWER_BACKEND=codex

# 三个独立进程：
python -m phantom_agents.ai_plan
python -m phantom_agents.ai_design
python -m phantom_agents.ai_devtest

# 或后台跑
bash scripts/start-ai-plan.sh
bash scripts/start-ai-design.sh
bash scripts/start-ai-devtest.sh
```
```

- [ ] **Step 4: 安装依赖并验证**

Run: `cd phantom_agents && python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
Expected: 安装无错误，aijuicer_sdk 可 import

Run: `.venv/bin/python -c "import aijuicer_sdk, phantom_agents; print('ok')"`
Expected: `ok`

- [ ] **Step 5: 提交**

```bash
git add phantom_agents/pyproject.toml phantom_agents/__init__.py phantom_agents/README.md
git commit -m "feat(agents): phantom_agents 项目骨架（aijuicer-sdk 依赖 + pytest 配置）"
```

---

## Task 2：runner.py — 工作区路径辅助

**Files:**
- Create: `phantom_agents/runner.py`
- Test: `phantom_agents/tests/conftest.py`
- Test: `phantom_agents/tests/test_runner.py`

- [ ] **Step 1: 写 `tests/conftest.py`**

```python
"""Pytest fixtures 共享。"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace_base(tmp_path: Path, monkeypatch) -> Path:
    """把 PHANTOM_PROJECTS_BASE 指向 tmp_path，避免测试碰真实 ~/phantom。"""
    base = tmp_path / "phantom"
    base.mkdir()
    monkeypatch.setenv("PHANTOM_PROJECTS_BASE", str(base))
    return base
```

- [ ] **Step 2: 写 `tests/test_runner.py`（resolve_workspace + workspace_has_phantom_state）**

```python
"""runner.py 单测。"""
from __future__ import annotations

from pathlib import Path

import pytest

from phantom_agents.runner import (
    PROJECTS_BASE_DEFAULT,
    resolve_workspace,
    workspace_has_phantom_state,
)


def test_resolve_workspace_joins_base_and_project_name(tmp_workspace_base: Path) -> None:
    """工作区 = PHANTOM_PROJECTS_BASE / project_name，幂等创建。"""
    result = resolve_workspace("todo-app")
    assert result == tmp_workspace_base / "todo-app"
    assert result.is_dir()


def test_resolve_workspace_idempotent_when_dir_exists(tmp_workspace_base: Path) -> None:
    """目录已存在（idea/requirement step 创建过）也应返回成功，不报错。"""
    (tmp_workspace_base / "existing").mkdir()
    (tmp_workspace_base / "existing" / "requirement.md").write_text("# req")
    result = resolve_workspace("existing")
    assert result == tmp_workspace_base / "existing"
    assert (result / "requirement.md").read_text() == "# req"  # 已有内容不被破坏


def test_resolve_workspace_rejects_empty_project_name() -> None:
    with pytest.raises(ValueError, match="project_name"):
        resolve_workspace("")


def test_resolve_workspace_rejects_unsafe_project_name(tmp_workspace_base: Path) -> None:
    """防止 ../ 逃逸到 base 之外。"""
    with pytest.raises(ValueError, match="project_name"):
        resolve_workspace("../../etc")
    with pytest.raises(ValueError, match="project_name"):
        resolve_workspace("/abs/path")


def test_default_base_is_user_phantom_dir() -> None:
    """没设环境变量时，默认 base 是 /Users/lapsdoor/phantom。"""
    assert PROJECTS_BASE_DEFAULT == Path("/Users/lapsdoor/phantom")


def test_workspace_has_phantom_state_false_when_empty(tmp_workspace_base: Path) -> None:
    ws = resolve_workspace("p")
    assert workspace_has_phantom_state(ws) is False


def test_workspace_has_phantom_state_true_when_state_json_exists(
    tmp_workspace_base: Path,
) -> None:
    ws = resolve_workspace("p")
    (ws / ".phantom").mkdir()
    (ws / ".phantom" / "state.json").write_text("{}")
    assert workspace_has_phantom_state(ws) is True
```

- [ ] **Step 3: 跑测试看它们 fail**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_runner.py -v`
Expected: ImportError 或 7 个 test FAIL（runner.py 还没写）

- [ ] **Step 4: 写 `runner.py` 第一部分（workspace 辅助）**

```python
"""phantom CLI 子进程调用 + 工作区管理 + 心跳泵。"""
from __future__ import annotations

import os
from pathlib import Path

# Phantom 工作区基目录。base 是单机/单用户部署，path = base / project_name。
# 多机部署时可设 PHANTOM_PROJECTS_BASE 覆盖。
PROJECTS_BASE_DEFAULT = Path("/Users/lapsdoor/phantom")


def _projects_base() -> Path:
    return Path(os.environ.get("PHANTOM_PROJECTS_BASE") or str(PROJECTS_BASE_DEFAULT))


def resolve_workspace(project_name: str) -> Path:
    """把 task['input']['project_name'] 转成 phantom 工作区绝对路径。

    路径 = PHANTOM_PROJECTS_BASE / project_name（base 默认 /Users/lapsdoor/phantom）。
    AIJuicer 的 idea step 已在该路径下写过 idea.md / requirement.md，
    但若目录不存在（边缘场景）这里幂等创建。
    """
    if not project_name:
        raise ValueError("project_name 为空，task['input']['project_name'] 必须有值")
    if "/" in project_name or project_name.startswith("..") or project_name.startswith("."):
        raise ValueError(
            f"project_name 不安全（含 / 或 .. / 以 . 开头）：{project_name!r}"
        )
    ws = _projects_base() / project_name
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def workspace_has_phantom_state(workspace: Path) -> bool:
    """已经初始化过 phantom 项目吗？（state.json 存在 = 是）"""
    return (workspace / ".phantom" / "state.json").is_file()
```

- [ ] **Step 5: 跑测试看它们 pass**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_runner.py -v`
Expected: 5 PASS

- [ ] **Step 6: 提交**

```bash
git add phantom_agents/runner.py phantom_agents/tests/conftest.py phantom_agents/tests/test_runner.py
git commit -m "feat(agents): runner.resolve_workspace + workspace_has_phantom_state（幂等建目录、识别已初始化项目）"
```

---

## Task 3：runner.py — phantom 子进程调用

**Files:**
- Modify: `phantom_agents/runner.py`
- Modify: `phantom_agents/tests/test_runner.py`
- Create: `phantom_agents/tests/fakes/fake_phantom.sh`

- [ ] **Step 1: 写假 phantom CLI（`tests/fakes/fake_phantom.sh`）**

```bash
#!/usr/bin/env bash
# 测试用假 phantom：把所有 args 写到 stderr（让 test 断言）+ 模拟 stdout 心跳行
# 退出码由 FAKE_PHANTOM_EXIT 环境变量控制（默认 0）
set -e
echo "FAKE_PHANTOM_ARGS: $*" >&2
echo "FAKE_PHANTOM_CWD: $PWD" >&2
echo "[phantom] starting"
sleep 0.05
echo "[phantom] doing work"
sleep 0.05
echo "[phantom] done"
exit "${FAKE_PHANTOM_EXIT:-0}"
```

Run: `chmod +x phantom_agents/tests/fakes/fake_phantom.sh`

- [ ] **Step 2: 测试 `run_phantom`（成功路径 + 心跳调用 + 退出码）**

写到 `tests/test_runner.py` 末尾：

```python
import os
from unittest.mock import AsyncMock

import pytest

from phantom_agents.runner import (
    PhantomFailedError,
    run_phantom,
)


@pytest.mark.asyncio
async def test_run_phantom_success_streams_heartbeat(tmp_path: Path, monkeypatch) -> None:
    """phantom 成功退出（rc=0），每行 stdout 都通过 heartbeat 上报。"""
    fake = Path(__file__).parent / "fakes" / "fake_phantom.sh"
    heartbeat = AsyncMock()
    rc = await run_phantom(
        workspace=tmp_path,
        args=["--plan", "test.md"],
        heartbeat=heartbeat,
        phantom_bin=str(fake),
    )
    assert rc == 0
    # 至少 3 行 stdout（starting / doing work / done）都触发了心跳
    assert heartbeat.await_count >= 3
    # 心跳消息包含 phantom 的输出
    call_messages = [c.args[0] for c in heartbeat.await_args_list]
    assert any("starting" in m for m in call_messages)
    assert any("done" in m for m in call_messages)


@pytest.mark.asyncio
async def test_run_phantom_runs_in_workspace_cwd(tmp_path: Path) -> None:
    fake = Path(__file__).parent / "fakes" / "fake_phantom.sh"
    captured_cwd: list[str] = []

    async def capture_cwd(msg: str) -> None:
        if msg.startswith("FAKE_PHANTOM_CWD:"):
            captured_cwd.append(msg.split(":", 1)[1].strip())

    # heartbeat 收 stdout 行（fake 里 cwd 是 stderr，下面用 stderr_callback）
    rc = await run_phantom(
        workspace=tmp_path,
        args=["--plan"],
        heartbeat=AsyncMock(),
        phantom_bin=str(fake),
        stderr_callback=capture_cwd,
    )
    assert rc == 0
    assert captured_cwd == [str(tmp_path)]


@pytest.mark.asyncio
async def test_run_phantom_passes_args_through(tmp_path: Path) -> None:
    fake = Path(__file__).parent / "fakes" / "fake_phantom.sh"
    captured: list[str] = []

    async def capture_args(msg: str) -> None:
        if msg.startswith("FAKE_PHANTOM_ARGS:"):
            captured.append(msg.split(":", 1)[1].strip())

    rc = await run_phantom(
        workspace=tmp_path,
        args=["--plan", "增加搜索功能"],
        heartbeat=AsyncMock(),
        phantom_bin=str(fake),
        stderr_callback=capture_args,
    )
    assert rc == 0
    assert captured == ["--plan 增加搜索功能"]


@pytest.mark.asyncio
async def test_run_phantom_nonzero_exit_raises(tmp_path: Path, monkeypatch) -> None:
    fake = Path(__file__).parent / "fakes" / "fake_phantom.sh"
    monkeypatch.setenv("FAKE_PHANTOM_EXIT", "7")
    with pytest.raises(PhantomFailedError) as ei:
        await run_phantom(
            workspace=tmp_path,
            args=["--plan"],
            heartbeat=AsyncMock(),
            phantom_bin=str(fake),
        )
    assert ei.value.exit_code == 7
    assert "phantom" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_run_phantom_inherits_env(tmp_path: Path, monkeypatch) -> None:
    """PHANTOM_*_BACKEND 环境变量必须透传给子进程。"""
    fake_path = Path(__file__).parent / "fakes" / "fake_phantom_env.sh"
    fake_path.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"BACKEND=${PHANTOM_GENERATOR_BACKEND:-unset}\" >&2\n"
        "exit 0\n"
    )
    fake_path.chmod(0o755)

    monkeypatch.setenv("PHANTOM_GENERATOR_BACKEND", "codex")
    captured: list[str] = []

    async def capture(msg: str) -> None:
        if msg.startswith("BACKEND="):
            captured.append(msg)

    rc = await run_phantom(
        workspace=tmp_path,
        args=["--plan"],
        heartbeat=AsyncMock(),
        phantom_bin=str(fake_path),
        stderr_callback=capture,
    )
    assert rc == 0
    assert captured == ["BACKEND=codex"]
```

- [ ] **Step 3: 跑测试看它们 fail**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_runner.py -v -k run_phantom`
Expected: 5 FAIL（`run_phantom` / `PhantomFailedError` 还不存在）

- [ ] **Step 4: 写 `run_phantom` 实现**

追加到 `runner.py`：

```python
import asyncio
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path


class PhantomFailedError(RuntimeError):
    """phantom 子进程退出码非 0。"""

    def __init__(self, exit_code: int, last_lines: list[str]) -> None:
        self.exit_code = exit_code
        self.last_lines = last_lines
        tail = "\n".join(last_lines[-20:])
        super().__init__(
            f"phantom 子进程失败（exit={exit_code}），日志末尾 20 行：\n{tail}"
        )


HeartbeatFn = Callable[[str], Awaitable[None]]


async def _drain(
    stream: asyncio.StreamReader,
    callback: HeartbeatFn | None,
    buffer: list[str],
) -> None:
    """读 stream（stdout 或 stderr）按行追加到 buffer，并调 callback（每行一次）。"""
    while True:
        line = await stream.readline()
        if not line:
            return
        text = line.decode(errors="replace").rstrip("\n")
        buffer.append(text)
        if callback is not None:
            try:
                await callback(text)
            except Exception:  # noqa: BLE001 — 心跳失败不应中断子进程
                pass


async def run_phantom(
    *,
    workspace: Path,
    args: list[str],
    heartbeat: HeartbeatFn,
    phantom_bin: str | None = None,
    stderr_callback: HeartbeatFn | None = None,
) -> int:
    """在 workspace 目录下跑 `phantom <args>`，stdout 每行触发 heartbeat。

    - 子进程 cwd = workspace（phantom 的 .phantom/ 状态会落在这里）
    - 环境变量从父进程继承（PHANTOM_*_BACKEND / OPENAI_API_KEY / 等）
    - 退出码 != 0 → 抛 PhantomFailedError（含日志末尾，便于上报 scheduler）
    """
    bin_path = phantom_bin or shutil.which("phantom")
    if not bin_path:
        raise RuntimeError(
            "找不到 phantom CLI（PATH 上没有 phantom）。请先在 AIDevelop 仓库根目录跑 ./install.sh。"
        )

    proc = await asyncio.create_subprocess_exec(
        bin_path,
        *args,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )
    stdout_buffer: list[str] = []
    stderr_buffer: list[str] = []
    assert proc.stdout is not None and proc.stderr is not None
    await asyncio.gather(
        _drain(proc.stdout, heartbeat, stdout_buffer),
        _drain(proc.stderr, stderr_callback, stderr_buffer),
    )
    rc = await proc.wait()
    if rc != 0:
        # 把 stderr 末尾也带上（phantom 错误一般在 stderr）
        merged = stdout_buffer + stderr_buffer
        raise PhantomFailedError(rc, merged)
    return rc
```

- [ ] **Step 5: 跑测试看它们 pass**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_runner.py -v`
Expected: 全部 PASS（含原 5 个 + 新 5 个）

- [ ] **Step 6: 提交**

```bash
git add phantom_agents/runner.py phantom_agents/tests/test_runner.py phantom_agents/tests/fakes/fake_phantom.sh
git commit -m "feat(agents): runner.run_phantom（cwd=workspace、stdout 流式心跳、退出码到 PhantomFailedError）"
```

---

## Task 4：runner.py — 失败分类（Retryable vs Fatal）

**Files:**
- Modify: `phantom_agents/runner.py`
- Modify: `phantom_agents/tests/test_runner.py`

**Why a separate task**：把 phantom 退出码 / 错误信息映射到 SDK 的 `RetryableError` / `FatalError` 是核心契约——AIJuicer 据此决定是自动重试还是转人工。需要明确分类规则。

**分类规则**：
- `phantom_bin` 不存在 → `FatalError`（环境问题，重试也没用）
- 退出码 0 → 成功
- 退出码 != 0 + stderr 含 "AI 调用超时" / "rate limit" / "Connection" / "ETIMEDOUT" → `RetryableError`
- 退出码 != 0 + stderr 含 "plan.locked.md 不存在" / "缺少需求文档" / "max_rounds" → `FatalError`（结构性问题）
- 其它退出码 != 0 → `RetryableError`（默认乐观，跟 SDK 兜底一致）

- [ ] **Step 1: 测试分类逻辑**

追加到 `tests/test_runner.py`：

```python
from aijuicer_sdk import FatalError, RetryableError

from phantom_agents.runner import classify_phantom_failure


def test_classify_timeout_is_retryable() -> None:
    err = PhantomFailedError(124, ["AI 调用超时（1800s），role=generator"])
    out = classify_phantom_failure(err)
    assert isinstance(out, RetryableError)
    assert "1800s" in str(out)


def test_classify_rate_limit_is_retryable() -> None:
    err = PhantomFailedError(1, ["LLM rate limited: try again"])
    assert isinstance(classify_phantom_failure(err), RetryableError)


def test_classify_connection_error_is_retryable() -> None:
    err = PhantomFailedError(1, ["Connection refused", "exiting"])
    assert isinstance(classify_phantom_failure(err), RetryableError)


def test_classify_missing_plan_is_fatal() -> None:
    err = PhantomFailedError(1, ["design 模式需要 .phantom/plan.locked.md 已存在"])
    out = classify_phantom_failure(err)
    assert isinstance(out, FatalError)


def test_classify_max_rounds_is_fatal() -> None:
    err = PhantomFailedError(1, ["group g-1 达到 max_rounds=6 仍未通过（strict 模式）"])
    assert isinstance(classify_phantom_failure(err), FatalError)


def test_classify_unknown_failure_defaults_retryable() -> None:
    err = PhantomFailedError(1, ["something weird went wrong"])
    out = classify_phantom_failure(err)
    assert isinstance(out, RetryableError)
```

- [ ] **Step 2: 跑测试看它们 fail**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_runner.py -v -k classify`
Expected: 6 FAIL（`classify_phantom_failure` 不存在）

- [ ] **Step 3: 实现 `classify_phantom_failure`**

追加到 `runner.py`：

```python
from aijuicer_sdk import FatalError, RetryableError


# stderr / stdout 含其中任一关键字 → 视为可重试
_RETRYABLE_PATTERNS = (
    "调用超时",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "Connection refused",
    "ConnectionResetError",
    "ETIMEDOUT",
    "Temporary failure",
)

# stderr / stdout 含其中任一关键字 → 视为不可重试（结构性问题，重试无意义）
_FATAL_PATTERNS = (
    ".phantom/plan.locked.md 已存在",
    "plan.locked.md 不存在",
    "需要 .phantom/plan.locked.md",
    "需要提供需求文档",
    "max_rounds",
    "找不到 phantom CLI",
)


def classify_phantom_failure(err: PhantomFailedError) -> RetryableError | FatalError:
    """根据 phantom 输出关键字决定 retryable / fatal。"""
    blob = "\n".join(err.last_lines)
    for pat in _FATAL_PATTERNS:
        if pat in blob:
            return FatalError(f"phantom 结构性失败（{pat}）：{err}")
    for pat in _RETRYABLE_PATTERNS:
        if pat in blob:
            return RetryableError(f"phantom 临时失败（{pat}）：{err}")
    # 默认乐观——和 SDK 的兜底策略保持一致
    return RetryableError(f"phantom 未知失败（exit={err.exit_code}）：{err}")
```

- [ ] **Step 4: 跑测试看它们 pass**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_runner.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add phantom_agents/runner.py phantom_agents/tests/test_runner.py
git commit -m "feat(agents): runner.classify_phantom_failure 把 phantom 退出归类成 Retryable/Fatal"
```

---

## Task 5：ai_plan agent

**Files:**
- Create: `phantom_agents/ai_plan.py`
- Test: `phantom_agents/tests/test_ai_plan.py`

**Plan agent 的逻辑**：

| 状态 | 条件 | phantom 调用 |
|---|---|---|
| 首跑 | `attempt==1` 且 `feedback is None` | 从上游读 `requirement.md` 写到 `<workspace>/requirement.md`，调 `phantom --plan requirement.md` |
| 重跑（带反馈） | `feedback is not None`（也就是用户在 UI 给了具体改动） | `phantom --plan "<feedback>"` |
| 重跑（无反馈） | `attempt > 1` 但 `feedback is None`（自动重试或纯 refresh） | `phantom --plan`（无参，phantom 自动注入 synthetic refresh amendment） |

产物：把 `<workspace>/.phantom/plan.locked.md` 的内容上传成 `plan.md` 产物（key 名约定，下游 design/devtest 可直接读盘上的 `.phantom/plan.locked.md`，artifact 主要给 UI 看 + 多机部署兜底）。

- [ ] **Step 1: 写测试 `tests/test_ai_plan.py`（首跑、带反馈重跑、无反馈重跑、上游缺失）**

```python
"""ai_plan.py 单测：mock phantom 子进程，断言参数 / 产物。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aijuicer_sdk import FatalError, RetryableError

from phantom_agents.ai_plan import handle


PROJECT = "todo-test"


def _make_ctx(attempt: int = 1, with_requirement: bool = True):
    """构造一个最小可用的 mock AgentContext。"""
    ctx = AsyncMock()
    ctx.workflow_id = "wf-test-123"
    ctx.task_id = "task-1"
    ctx.step = "plan"
    ctx.attempt = attempt
    ctx.request_id = "req-test"
    ctx.input = {}
    if with_requirement:
        ctx.load_artifact = AsyncMock(return_value=b"# Requirement\n\nbuild a todo app")
    else:
        ctx.load_artifact = AsyncMock(side_effect=FileNotFoundError("no requirement"))
    ctx.save_artifact = AsyncMock()
    ctx.heartbeat = AsyncMock()
    return ctx


def _make_task(
    text: str = "build a todo app",
    feedback: str | None = None,
    attempt: int = 1,
    project_name: str = PROJECT,
) -> dict:
    inp: dict = {"text": text, "project_name": project_name}
    if feedback is not None:
        inp["user_feedback"] = {"plan": feedback}
    return {
        "input": inp,
        "attempt": attempt,
        "task_id": "t",
        "workflow_id": "w",
        "step": "plan",
    }


def _seed_plan_output(workspace: Path, content: str = "# Plan\n\n- m1\n") -> None:
    """模拟 phantom 跑完后留下的 .phantom/plan.locked.md。"""
    (workspace / ".phantom").mkdir(parents=True, exist_ok=True)
    (workspace / ".phantom" / "plan.locked.md").write_text(content)


@pytest.mark.asyncio
async def test_first_run_invokes_phantom_plan_with_requirement_file(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT  # PHANTOM_PROJECTS_BASE/<project>
    ctx = _make_ctx()
    task = _make_task()
    captured_args: list[list[str]] = []
    captured_workspaces: list[Path] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured_args.append(args)
        captured_workspaces.append(workspace)
        _seed_plan_output(workspace)
        return 0

    with patch("phantom_agents.ai_plan.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    assert captured_workspaces == [workspace]
    assert captured_args == [["--plan", str(workspace / "requirement.md")]]
    assert (workspace / "requirement.md").read_text() == "# Requirement\n\nbuild a todo app"
    ctx.save_artifact.assert_awaited_once()
    args, kwargs = ctx.save_artifact.call_args
    assert args[0] == "plan.md"
    assert "# Plan" in args[1]
    assert kwargs["content_type"] == "text/markdown"
    assert out["rerun"] is False


@pytest.mark.asyncio
async def test_rerun_with_feedback_passes_string_to_phantom(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_output(workspace, "# Old plan\n")
    (workspace / ".phantom" / "state.json").write_text('{"current_phase":"plan"}')

    ctx = _make_ctx(attempt=2)
    task = _make_task(feedback="把 rubric 权重改了", attempt=2)

    captured_args: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured_args.append(args)
        _seed_plan_output(workspace, "# New plan after feedback\n")
        return 0

    with patch("phantom_agents.ai_plan.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    assert captured_args == [["--plan", "把 rubric 权重改了"]]
    assert out["rerun"] is True


@pytest.mark.asyncio
async def test_rerun_without_feedback_uses_synthetic_refresh(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_output(workspace, "# Old plan\n")
    (workspace / ".phantom" / "state.json").write_text('{"current_phase":"plan"}')

    ctx = _make_ctx(attempt=2)
    task = _make_task(feedback=None, attempt=2)

    captured_args: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured_args.append(args)
        _seed_plan_output(workspace, "# Refreshed plan\n")
        return 0

    with patch("phantom_agents.ai_plan.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    assert captured_args == [["--plan"]]
    assert out["rerun"] is True


@pytest.mark.asyncio
async def test_missing_requirement_artifact_raises_fatal(
    tmp_workspace_base: Path,
) -> None:
    ctx = _make_ctx(with_requirement=False)
    task = _make_task()
    with pytest.raises(FatalError, match="requirement"):
        await handle(ctx, task)


@pytest.mark.asyncio
async def test_phantom_failure_propagates_classified_error(
    tmp_workspace_base: Path,
) -> None:
    from phantom_agents.runner import PhantomFailedError

    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        raise PhantomFailedError(1, ["LLM rate limited: try later"])

    with patch("phantom_agents.ai_plan.run_phantom", new=fake_run):
        with pytest.raises(RetryableError):
            await handle(ctx, task)


@pytest.mark.asyncio
async def test_missing_plan_locked_after_phantom_is_fatal(
    tmp_workspace_base: Path,
) -> None:
    """phantom rc=0 但没产出 plan.locked.md → 视为 FatalError（不要静默成功）。"""
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        return 0  # 但不创建 plan.locked.md

    with patch("phantom_agents.ai_plan.run_phantom", new=fake_run):
        with pytest.raises(FatalError, match="plan.locked.md"):
            await handle(ctx, task)


@pytest.mark.asyncio
async def test_missing_project_name_raises_fatal(tmp_workspace_base: Path) -> None:
    """task['input'] 没 project_name → FatalError（路径无法计算）。"""
    ctx = _make_ctx()
    task = _make_task()
    del task["input"]["project_name"]
    with pytest.raises(FatalError, match="project_name"):
        await handle(ctx, task)
```

- [ ] **Step 2: 跑测试看它们 fail**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_ai_plan.py -v`
Expected: 7 FAIL（`phantom_agents.ai_plan` 还没写）

- [ ] **Step 3: 写 `phantom_agents/ai_plan.py`**

```python
"""ai-plan agent — 包装 phantom 的 plan 模式。"""
from __future__ import annotations

from typing import Any

from aijuicer_sdk import Agent, AgentContext, FatalError, TaskPayload

from phantom_agents.runner import (
    PhantomFailedError,
    classify_phantom_failure,
    resolve_workspace,
    run_phantom,
)

agent = Agent(name="ai-plan", step="plan", concurrency=1)


@agent.handler
async def handle(ctx: AgentContext, task: TaskPayload) -> dict[str, Any]:
    inp = task.get("input") or {}
    project_name = inp.get("project_name")
    if not project_name:
        raise FatalError(
            "task['input']['project_name'] 缺失，无法定位 phantom 工作区"
        )
    try:
        workspace = resolve_workspace(project_name)
    except ValueError as e:
        raise FatalError(str(e)) from e

    fb_map = inp.get("user_feedback") or {}
    feedback = fb_map.get("plan") if isinstance(fb_map, dict) else None
    is_rerun = task.get("attempt", 1) > 1 or feedback is not None

    # 决定 phantom 命令参数
    if is_rerun:
        if feedback:
            args = ["--plan", feedback]
            await ctx.heartbeat(f"plan rerun（用户反馈：{feedback[:40]}）")
        else:
            args = ["--plan"]  # synthetic refresh
            await ctx.heartbeat("plan rerun（无反馈，纯 refresh）")
    else:
        # 首跑：从上游 requirement step 拉需求文档
        try:
            req_bytes = await ctx.load_artifact("requirement", "requirement.md")
        except FileNotFoundError as e:
            raise FatalError(f"上游 requirement.md 不存在：{e}") from e
        req_path = workspace / "requirement.md"
        req_path.write_text(req_bytes.decode("utf-8"))
        args = ["--plan", str(req_path)]
        await ctx.heartbeat("plan 首跑（已写入 requirement.md）")

    # 跑 phantom
    try:
        await run_phantom(
            workspace=workspace,
            args=args,
            heartbeat=ctx.heartbeat,
        )
    except PhantomFailedError as e:
        raise classify_phantom_failure(e) from e

    # 校验产物 + 上传
    plan_locked = workspace / ".phantom" / "plan.locked.md"
    if not plan_locked.is_file():
        raise FatalError(
            "phantom 跑完但没有产出 .phantom/plan.locked.md，可能是核心章节校验失败。"
        )
    plan_md = plan_locked.read_text(encoding="utf-8")
    await ctx.save_artifact("plan.md", plan_md, content_type="text/markdown")

    return {"rerun": is_rerun, "bytes": len(plan_md)}


if __name__ == "__main__":
    agent.run()
```

- [ ] **Step 4: 跑测试看它们 pass**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_ai_plan.py -v`
Expected: 7 PASS

- [ ] **Step 5: 提交**

```bash
git add phantom_agents/ai_plan.py phantom_agents/tests/test_ai_plan.py
git commit -m "feat(agents): ai_plan agent — 首跑读 requirement.md，重跑透传用户反馈给 phantom --plan"
```

---

## Task 6：ai_design agent

**Files:**
- Create: `phantom_agents/ai_design.py`
- Test: `phantom_agents/tests/test_ai_design.py`

**Design agent 的逻辑**：

前置：`<workspace>/.phantom/plan.locked.md` 存在（同一 wf 的 plan agent 已经跑过）。如果不存在（多机部署且 design 跟 plan 不同机），从上游 plan 产物 `plan.md` 拉一份回来落到 `.phantom/plan.locked.md`，并且最小化 bootstrap 一份 `state.json`。

| 状态 | 条件 | phantom 调用 |
|---|---|---|
| 首跑 | `attempt==1` 且 `feedback is None` | `phantom --design` |
| 重跑（带反馈） | `feedback is not None` | `phantom --design "<feedback>"` |
| 重跑（无反馈） | `attempt > 1` 但 `feedback is None` | `phantom --design`（design 模式无 amendment 时强制重跑 R1→R2→R3） |

产物：上传 `<workspace>/.phantom/ui-design.md` 总览（key=`ui-design.md`）。如果有 HTML 落盘（前端项目），把整个 `<workspace>/.phantom/ui-design/` 目录打 tar.gz 上传（key=`ui-design.tar.gz`），方便多机部署 / UI 下载查看。**纯后端项目**（phantom skip 了 design）→ 只上传 `ui-design.md`（内容会是 "纯后端项目，无需 UI 设计"），不上传 tar。

- [ ] **Step 1: 写测试 `tests/test_ai_design.py`**

```python
"""ai_design.py 单测。"""
from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aijuicer_sdk import FatalError

from phantom_agents.ai_design import handle


PROJECT = "design-test"


def _make_ctx(attempt: int = 1):
    ctx = AsyncMock()
    ctx.workflow_id = "wf-1"
    ctx.task_id = "t-1"
    ctx.step = "design"
    ctx.attempt = attempt
    ctx.request_id = "req-1"
    ctx.input = {}
    ctx.load_artifact = AsyncMock(return_value=b"# Plan\n\n- f1\n")
    ctx.save_artifact = AsyncMock()
    ctx.heartbeat = AsyncMock()
    return ctx


def _make_task(
    feedback: str | None = None,
    attempt: int = 1,
    project_name: str = PROJECT,
) -> dict:
    inp: dict = {"text": "x", "project_name": project_name}
    if feedback is not None:
        inp["user_feedback"] = {"design": feedback}
    return {
        "input": inp,
        "attempt": attempt,
        "task_id": "t",
        "workflow_id": "w",
        "step": "design",
    }


def _seed_plan_locked(workspace: Path, content: str = "# Plan\n") -> None:
    (workspace / ".phantom").mkdir(parents=True, exist_ok=True)
    (workspace / ".phantom" / "plan.locked.md").write_text(content)
    (workspace / ".phantom" / "state.json").write_text(
        json.dumps({"current_phase": "ui_design", "phases": {"plan": {"status": "completed"}}})
    )


def _seed_design_outputs(workspace: Path, with_html: bool = True) -> None:
    """模拟 phantom --design 跑完后的产物。"""
    d = workspace / ".phantom"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ui-design.md").write_text("# UI Design Overview\n\nproject_id=abc\n")
    if with_html:
        (d / "ui-design").mkdir(exist_ok=True)
        (d / "ui-design" / "home.html").write_text("<html>home</html>")
        (d / "ui-design" / "home.json").write_text("{}")


@pytest.mark.asyncio
async def test_first_run_calls_phantom_design_no_args(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    ctx = _make_ctx()
    task = _make_task()
    captured: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured.append(args)
        _seed_design_outputs(workspace)
        return 0

    with patch("phantom_agents.ai_design.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    assert captured == [["--design"]]
    # 应上传 ui-design.md + ui-design.tar.gz
    keys_uploaded = {c.args[0] for c in ctx.save_artifact.call_args_list}
    assert keys_uploaded == {"ui-design.md", "ui-design.tar.gz"}
    assert out["rerun"] is False
    assert out["screens"] == 1


@pytest.mark.asyncio
async def test_rerun_with_feedback_passes_string(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    _seed_design_outputs(workspace)  # 上一次的产物
    ctx = _make_ctx(attempt=2)
    task = _make_task(feedback="改成暖白色调", attempt=2)
    captured: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured.append(args)
        _seed_design_outputs(workspace)
        return 0

    with patch("phantom_agents.ai_design.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    assert captured == [["--design", "改成暖白色调"]]
    assert out["rerun"] is True


@pytest.mark.asyncio
async def test_missing_plan_locked_fetches_from_artifact(
    tmp_workspace_base: Path,
) -> None:
    """同一 wf 但 design agent 跑在不同机器（plan.locked.md 不在本地） → 从 artifact 拉。"""
    # 不 seed plan_locked；workspace 由 resolve_workspace 自动创建
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        # 验证 phantom 跑之前 plan.locked.md 已经被写好了
        assert (workspace / ".phantom" / "plan.locked.md").exists()
        _seed_design_outputs(workspace)
        return 0

    with patch("phantom_agents.ai_design.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    ctx.load_artifact.assert_awaited_once_with("plan", "plan.md")
    assert out["rerun"] is False


@pytest.mark.asyncio
async def test_no_html_means_pure_backend_project(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        # 只写 ui-design.md，不写 ui-design/ 目录（纯后端 fallback）
        (workspace / ".phantom").mkdir(exist_ok=True)
        (workspace / ".phantom" / "ui-design.md").write_text("纯后端项目，无需 UI 设计\n")
        return 0

    with patch("phantom_agents.ai_design.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    keys = {c.args[0] for c in ctx.save_artifact.call_args_list}
    assert keys == {"ui-design.md"}  # 不上传 tar.gz
    assert out["screens"] == 0


@pytest.mark.asyncio
async def test_missing_ui_design_md_after_phantom_is_fatal(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        return 0  # 不写任何产物

    with patch("phantom_agents.ai_design.run_phantom", new=fake_run):
        with pytest.raises(FatalError, match="ui-design.md"):
            await handle(ctx, task)


@pytest.mark.asyncio
async def test_tarball_contains_html_files(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        _seed_design_outputs(workspace, with_html=True)
        return 0

    with patch("phantom_agents.ai_design.run_phantom", new=fake_run):
        await handle(ctx, task)

    # 找到 tar.gz 的 save_artifact 调用，解开看里面文件
    tar_calls = [c for c in ctx.save_artifact.call_args_list if c.args[0] == "ui-design.tar.gz"]
    assert len(tar_calls) == 1
    raw = tar_calls[0].args[1]
    assert isinstance(raw, (bytes, bytearray))
    with tarfile.open(fileobj=BytesIO(raw), mode="r:gz") as tf:
        names = tf.getnames()
    assert "ui-design/home.html" in names
    assert "ui-design/home.json" in names
```

- [ ] **Step 2: 跑测试看它们 fail**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_ai_design.py -v`
Expected: 6 FAIL

- [ ] **Step 3: 写 `phantom_agents/ai_design.py`**

```python
"""ai-design agent — 包装 phantom 的 design 模式。"""
from __future__ import annotations

import io
import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aijuicer_sdk import Agent, AgentContext, FatalError, TaskPayload

from phantom_agents.runner import (
    PhantomFailedError,
    classify_phantom_failure,
    resolve_workspace,
    run_phantom,
    workspace_has_phantom_state,
)

agent = Agent(name="ai-design", step="design", concurrency=1)


def _bootstrap_state_for_design(workspace: Path, plan_md: str) -> None:
    """plan.locked.md 不在本地（多机部署） → 从 artifact 落到本地 + 写最小 state.json。

    phantom --design 模式只读 .phantom/plan.locked.md + .phantom/state.json；
    其它字段（changelog 等）不读，所以一份最小骨架就够。
    """
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "plan.locked.md").write_text(plan_md)
    (pdir / "state.json").write_text(
        json.dumps(
            {
                "requirements_file": str(workspace / "requirement.md"),
                "project_dir": str(workspace),
                "current_phase": "ui_design",
                "current_group_index": 0,
                "phases": {
                    "plan": {"status": "completed", "iteration": 1},
                    "ui_design": {"status": "pending", "iteration": 0},
                    "dev": {"status": "pending", "iteration": 0},
                    "code_review": {"status": "pending", "iteration": 0},
                    "deploy": {"status": "pending", "iteration": 0},
                    "test": {"status": "pending", "iteration": 0, "forced_features": []},
                },
                "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    )
    # changelog 也建空文件——phantom 主循环对它有读，避免 render_prompt 报错
    (pdir / "changelog.md").touch()


def _make_ui_design_tarball(ui_design_dir: Path) -> bytes:
    """把 .phantom/ui-design/ 目录打成 tar.gz 字节流。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(ui_design_dir, arcname="ui-design")
    return buf.getvalue()


@agent.handler
async def handle(ctx: AgentContext, task: TaskPayload) -> dict[str, Any]:
    inp = task.get("input") or {}
    project_name = inp.get("project_name")
    if not project_name:
        raise FatalError(
            "task['input']['project_name'] 缺失，无法定位 phantom 工作区"
        )
    try:
        workspace = resolve_workspace(project_name)
    except ValueError as e:
        raise FatalError(str(e)) from e

    fb_map = inp.get("user_feedback") or {}
    feedback = fb_map.get("design") if isinstance(fb_map, dict) else None
    is_rerun = task.get("attempt", 1) > 1 or feedback is not None

    # 确保 plan.locked.md 在本地（不在则从 artifact 拉）
    plan_locked = workspace / ".phantom" / "plan.locked.md"
    if not plan_locked.is_file():
        try:
            plan_md = (await ctx.load_artifact("plan", "plan.md")).decode("utf-8")
        except FileNotFoundError as e:
            raise FatalError(f"上游 plan.md 不存在：{e}") from e
        _bootstrap_state_for_design(workspace, plan_md)
        await ctx.heartbeat("从 artifact 拉了 plan.locked.md，已 bootstrap 工作区")
    elif not workspace_has_phantom_state(workspace):
        # plan 在但 state.json 缺失（罕见）→ 也 bootstrap
        _bootstrap_state_for_design(workspace, plan_locked.read_text())

    args = ["--design"] if not feedback else ["--design", feedback]
    await ctx.heartbeat(f"design {'rerun' if is_rerun else '首跑'}")

    try:
        await run_phantom(workspace=workspace, args=args, heartbeat=ctx.heartbeat)
    except PhantomFailedError as e:
        raise classify_phantom_failure(e) from e

    # 校验 + 上传产物
    ui_design_md = workspace / ".phantom" / "ui-design.md"
    if not ui_design_md.is_file():
        raise FatalError(
            "phantom 跑完但没产出 .phantom/ui-design.md（前端项目应该有，纯后端 fallback 也应留一份）"
        )
    md_text = ui_design_md.read_text(encoding="utf-8")
    await ctx.save_artifact("ui-design.md", md_text, content_type="text/markdown")

    ui_design_dir = workspace / ".phantom" / "ui-design"
    screen_count = 0
    if ui_design_dir.is_dir():
        screen_count = sum(1 for p in ui_design_dir.glob("*.html"))
    if screen_count > 0:
        tar_bytes = _make_ui_design_tarball(ui_design_dir)
        await ctx.save_artifact(
            "ui-design.tar.gz",
            tar_bytes,
            content_type="application/gzip",
        )

    return {"rerun": is_rerun, "screens": screen_count}


if __name__ == "__main__":
    agent.run()
```

- [ ] **Step 4: 跑测试看它们 pass**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_ai_design.py -v`
Expected: 6 PASS

- [ ] **Step 5: 提交**

```bash
git add phantom_agents/ai_design.py phantom_agents/tests/test_ai_design.py
git commit -m "feat(agents): ai_design agent — 上游缺 plan.locked.md 时 bootstrap，纯后端项目不打 tar"
```

---

## Task 7：ai_devtest agent

**Files:**
- Create: `phantom_agents/ai_devtest.py`
- Test: `phantom_agents/tests/test_ai_devtest.py`

**Devtest agent 的逻辑**：

前置：`<workspace>/.phantom/plan.locked.md` 存在；如果是有前端的项目，最好也有 `<workspace>/.phantom/ui-design/`（不强制——phantom 在 dev 阶段会按通用规范降级）。同 design agent 的兜底逻辑：缺啥从 artifact 拉啥。

| 状态 | 条件 | phantom 调用 |
|---|---|---|
| 首跑 | `attempt==1` 且 `feedback is None` | `phantom --dev-test`（无 return-packet → 跑完所有 group，跳过强制打磨） |
| 重跑（带反馈） | `feedback is not None` | `phantom --dev-test "<feedback>"`（phantom 写 `return_from: user-amendment` 的 return-packet，触发一次性 sprint） |
| 重跑（无反馈） | `attempt > 1` 但 `feedback is None` | `phantom --dev-test`（继续剩余 group，没剩余则 phantom 自己 warn 后退出 0） |

产物：把 `<workspace>/backend/` + `frontend/`（如有）+ `scripts/` 整个打 tar.gz 上传成 `code.tar.gz`。同时上传最近一次 `<workspace>/.phantom/test-report-iter*.md` 当 `test-report.md`。如果项目部署时拿到了 endpoint 信息（端口在 `<workspace>/.phantom/port.backend`），写一份 `runtime.json` 含 `{backend_port, frontend_port, backend_pid}` 当产物，方便后续 deploy step 接管。

- [ ] **Step 1: 写测试 `tests/test_ai_devtest.py`**

```python
"""ai_devtest.py 单测。"""
from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aijuicer_sdk import FatalError

from phantom_agents.ai_devtest import handle


PROJECT = "devtest-test"


def _make_ctx(attempt: int = 1):
    ctx = AsyncMock()
    ctx.workflow_id = "wf-1"
    ctx.task_id = "t-1"
    ctx.step = "devtest"
    ctx.attempt = attempt
    ctx.request_id = "req-1"
    ctx.input = {}
    ctx.load_artifact = AsyncMock(return_value=b"# Plan\n\n- f1\n")
    ctx.save_artifact = AsyncMock()
    ctx.heartbeat = AsyncMock()
    return ctx


def _make_task(
    feedback: str | None = None,
    attempt: int = 1,
    project_name: str = PROJECT,
) -> dict:
    inp: dict = {"text": "x", "project_name": project_name}
    if feedback is not None:
        inp["user_feedback"] = {"devtest": feedback}
    return {
        "input": inp,
        "attempt": attempt,
        "task_id": "t",
        "workflow_id": "w",
        "step": "devtest",
    }


def _seed_phantom_state(workspace: Path) -> None:
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "plan.locked.md").write_text("# Plan\n")
    (pdir / "state.json").write_text(json.dumps({"current_phase": "dev", "phases": {}}))
    (pdir / "changelog.md").touch()


def _seed_devtest_outputs(workspace: Path, iter_n: int = 1, with_frontend: bool = True) -> None:
    """模拟 phantom --dev-test 跑完后的产物。"""
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"test-report-iter{iter_n}.md").write_text(f"# Test Report iter {iter_n}\n\n总分: 92/100\n")
    (pdir / "port.backend").write_text("12345")
    (pdir / "port.frontend").write_text("12346") if with_frontend else None
    (pdir / "runtime").mkdir(exist_ok=True)
    (pdir / "runtime" / "backend.pid").write_text("9999")
    # 业务代码
    (workspace / "backend").mkdir(exist_ok=True)
    (workspace / "backend" / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    if with_frontend:
        (workspace / "frontend").mkdir(exist_ok=True)
        (workspace / "frontend" / "index.html").write_text("<html></html>")
    (workspace / "scripts").mkdir(exist_ok=True)
    (workspace / "scripts" / "start-backend.sh").write_text("#!/bin/bash\nexec uvicorn ...")


@pytest.mark.asyncio
async def test_first_run_calls_phantom_dev_test_no_args(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()
    task = _make_task()
    captured: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured.append(args)
        _seed_devtest_outputs(workspace)
        return 0

    with patch("phantom_agents.ai_devtest.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    assert captured == [["--dev-test"]]
    keys = {c.args[0] for c in ctx.save_artifact.call_args_list}
    assert "code.tar.gz" in keys
    assert "test-report.md" in keys
    assert "runtime.json" in keys
    assert out["rerun"] is False


@pytest.mark.asyncio
async def test_rerun_with_feedback_passes_string(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    _seed_devtest_outputs(workspace, iter_n=1)
    ctx = _make_ctx(attempt=2)
    task = _make_task(feedback="搜索按钮点了没反应", attempt=2)
    captured: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured.append(args)
        _seed_devtest_outputs(workspace, iter_n=2)
        return 0

    with patch("phantom_agents.ai_devtest.run_phantom", new=fake_run):
        out = await handle(ctx, task)

    assert captured == [["--dev-test", "搜索按钮点了没反应"]]
    assert out["rerun"] is True


@pytest.mark.asyncio
async def test_test_report_picks_latest_iter(tmp_workspace_base: Path) -> None:
    """有多份 test-report-iterN.md → 上传最大 N 的那份。"""
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        _seed_devtest_outputs(workspace, iter_n=1)
        _seed_devtest_outputs(workspace, iter_n=3)  # 也写一份 iter-3
        _seed_devtest_outputs(workspace, iter_n=2)
        return 0

    with patch("phantom_agents.ai_devtest.run_phantom", new=fake_run):
        await handle(ctx, task)

    test_report_calls = [c for c in ctx.save_artifact.call_args_list if c.args[0] == "test-report.md"]
    assert len(test_report_calls) == 1
    body = test_report_calls[0].args[1]
    assert "iter 3" in body  # 最新一份


@pytest.mark.asyncio
async def test_runtime_json_has_ports_and_pid(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        _seed_devtest_outputs(workspace, with_frontend=True)
        return 0

    with patch("phantom_agents.ai_devtest.run_phantom", new=fake_run):
        await handle(ctx, task)

    runtime_calls = [c for c in ctx.save_artifact.call_args_list if c.args[0] == "runtime.json"]
    assert len(runtime_calls) == 1
    payload = json.loads(runtime_calls[0].args[1])
    assert payload == {"backend_port": 12345, "frontend_port": 12346, "backend_pid": 9999}


@pytest.mark.asyncio
async def test_code_tarball_contains_backend_frontend_scripts(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        _seed_devtest_outputs(workspace, with_frontend=True)
        return 0

    with patch("phantom_agents.ai_devtest.run_phantom", new=fake_run):
        await handle(ctx, task)

    tar_calls = [c for c in ctx.save_artifact.call_args_list if c.args[0] == "code.tar.gz"]
    assert len(tar_calls) == 1
    raw = tar_calls[0].args[1]
    with tarfile.open(fileobj=BytesIO(raw), mode="r:gz") as tf:
        names = tf.getnames()
    assert "backend/app.py" in names
    assert "frontend/index.html" in names
    assert "scripts/start-backend.sh" in names
    # .phantom/ 不应在打包里（会引入 runtime/ logs/ 等噪声）
    assert not any(n.startswith(".phantom") for n in names)


@pytest.mark.asyncio
async def test_missing_plan_locked_fetches_both_plan_and_design(
    tmp_workspace_base: Path,
) -> None:
    """devtest 在新机器跑：plan + design 都从 artifact 拉。"""
    ctx = _make_ctx()
    task = _make_task()

    # 区分 plan 和 design 的产物 mock
    async def load_artifact_dispatch(step: str, key: str) -> bytes:
        if step == "plan":
            return b"# Plan\n"
        if step == "design":
            return b"# UI Design Overview\n"
        raise FileNotFoundError(f"no {step}/{key}")

    ctx.load_artifact = AsyncMock(side_effect=load_artifact_dispatch)

    async def fake_run(*, workspace, args, heartbeat, **kw):
        assert (workspace / ".phantom" / "plan.locked.md").exists()
        # design 是 best-effort（design artifact 拉到了就放进去；拉不到不阻塞）
        _seed_devtest_outputs(workspace)
        return 0

    with patch("phantom_agents.ai_devtest.run_phantom", new=fake_run):
        await handle(ctx, task)

    # 至少调用了 plan.md 拉取
    plan_calls = [c for c in ctx.load_artifact.call_args_list if c.args == ("plan", "plan.md")]
    assert len(plan_calls) == 1


@pytest.mark.asyncio
async def test_missing_test_report_is_fatal(tmp_workspace_base: Path) -> None:
    """phantom rc=0 但没产出任何 test-report-iter*.md → fatal。"""
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()
    task = _make_task()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        # 不写 test-report
        (workspace / ".phantom").mkdir(exist_ok=True)
        (workspace / "backend").mkdir(exist_ok=True)
        (workspace / "backend" / "x.py").write_text("")
        return 0

    with patch("phantom_agents.ai_devtest.run_phantom", new=fake_run):
        with pytest.raises(FatalError, match="test-report"):
            await handle(ctx, task)
```

- [ ] **Step 2: 跑测试看它们 fail**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_ai_devtest.py -v`
Expected: 7 FAIL

- [ ] **Step 3: 写 `phantom_agents/ai_devtest.py`**

```python
"""ai-devtest agent — 包装 phantom 的 dev-test 模式。"""
from __future__ import annotations

import io
import json
import re
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aijuicer_sdk import Agent, AgentContext, FatalError, TaskPayload

from phantom_agents.runner import (
    PhantomFailedError,
    classify_phantom_failure,
    resolve_workspace,
    run_phantom,
)

agent = Agent(name="ai-devtest", step="devtest", concurrency=1)


def _bootstrap_state_for_devtest(workspace: Path, plan_md: str) -> None:
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "plan.locked.md").write_text(plan_md)
    (pdir / "state.json").write_text(
        json.dumps(
            {
                "requirements_file": str(workspace / "requirement.md"),
                "project_dir": str(workspace),
                "current_phase": "dev",
                "current_group_index": 0,
                "phases": {
                    "plan": {"status": "completed", "iteration": 1},
                    "ui_design": {"status": "completed", "iteration": 1},
                    "dev": {"status": "pending", "iteration": 0},
                    "code_review": {"status": "pending", "iteration": 0},
                    "deploy": {"status": "pending", "iteration": 0},
                    "test": {"status": "pending", "iteration": 0, "forced_features": []},
                },
                "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    )
    (pdir / "changelog.md").touch()


def _restore_design_if_available(workspace: Path, ui_design_md: str | None) -> None:
    if ui_design_md is None:
        return
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "ui-design.md").write_text(ui_design_md)


def _make_code_tarball(workspace: Path) -> bytes:
    """打包 backend/ frontend/ scripts/ 三个目录（存在的话），跳过 .phantom/。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for sub in ("backend", "frontend", "scripts"):
            sub_dir = workspace / sub
            if sub_dir.is_dir():
                tf.add(sub_dir, arcname=sub)
    return buf.getvalue()


def _latest_test_report(workspace: Path) -> Path | None:
    """从 .phantom/test-report-iter<N>.md 里挑出 N 最大的那份。"""
    pdir = workspace / ".phantom"
    if not pdir.is_dir():
        return None
    candidates: list[tuple[int, Path]] = []
    pat = re.compile(r"^test-report-iter(\d+)\.md$")
    for p in pdir.iterdir():
        m = pat.match(p.name)
        if m:
            candidates.append((int(m.group(1)), p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _runtime_summary(workspace: Path) -> dict[str, Any]:
    pdir = workspace / ".phantom"
    out: dict[str, Any] = {}
    bp = pdir / "port.backend"
    if bp.is_file():
        out["backend_port"] = int(bp.read_text().strip())
    fp = pdir / "port.frontend"
    if fp.is_file():
        out["frontend_port"] = int(fp.read_text().strip())
    pid = pdir / "runtime" / "backend.pid"
    if pid.is_file():
        out["backend_pid"] = int(pid.read_text().strip())
    return out


@agent.handler
async def handle(ctx: AgentContext, task: TaskPayload) -> dict[str, Any]:
    inp = task.get("input") or {}
    project_name = inp.get("project_name")
    if not project_name:
        raise FatalError(
            "task['input']['project_name'] 缺失，无法定位 phantom 工作区"
        )
    try:
        workspace = resolve_workspace(project_name)
    except ValueError as e:
        raise FatalError(str(e)) from e

    fb_map = inp.get("user_feedback") or {}
    feedback = fb_map.get("devtest") if isinstance(fb_map, dict) else None
    is_rerun = task.get("attempt", 1) > 1 or feedback is not None

    # 兜底：plan.locked.md 不在本地 → 从 artifact 拉
    plan_locked = workspace / ".phantom" / "plan.locked.md"
    if not plan_locked.is_file():
        try:
            plan_md = (await ctx.load_artifact("plan", "plan.md")).decode("utf-8")
        except FileNotFoundError as e:
            raise FatalError(f"上游 plan.md 不存在：{e}") from e
        _bootstrap_state_for_devtest(workspace, plan_md)
        # design 是 best-effort：拉得到就用，拉不到不阻塞（phantom 在 dev 阶段会按通用规范降级）
        try:
            ui_md = (await ctx.load_artifact("design", "ui-design.md")).decode("utf-8")
            _restore_design_if_available(workspace, ui_md)
        except FileNotFoundError:
            pass
        await ctx.heartbeat("从 artifact 拉了 plan.locked.md（design 可选），已 bootstrap 工作区")

    args = ["--dev-test"] if not feedback else ["--dev-test", feedback]
    await ctx.heartbeat(f"dev-test {'rerun' if is_rerun else '首跑'}")

    try:
        await run_phantom(workspace=workspace, args=args, heartbeat=ctx.heartbeat)
    except PhantomFailedError as e:
        raise classify_phantom_failure(e) from e

    # 校验 + 上传产物
    test_report = _latest_test_report(workspace)
    if test_report is None:
        raise FatalError(
            "phantom dev-test 跑完但没产出任何 .phantom/test-report-iter*.md，无法验证开发结果。"
        )
    await ctx.save_artifact(
        "test-report.md",
        test_report.read_text(encoding="utf-8"),
        content_type="text/markdown",
    )

    code_tar = _make_code_tarball(workspace)
    await ctx.save_artifact("code.tar.gz", code_tar, content_type="application/gzip")

    runtime = _runtime_summary(workspace)
    await ctx.save_artifact(
        "runtime.json",
        json.dumps(runtime, ensure_ascii=False),
        content_type="application/json",
    )

    return {
        "rerun": is_rerun,
        "code_bytes": len(code_tar),
        "test_report_iter": int(re.search(r"iter(\d+)", test_report.name).group(1)),
    }


if __name__ == "__main__":
    agent.run()
```

- [ ] **Step 4: 跑测试看它们 pass**

Run: `cd phantom_agents && .venv/bin/pytest tests/test_ai_devtest.py -v`
Expected: 7 PASS

- [ ] **Step 5: 提交**

```bash
git add phantom_agents/ai_devtest.py phantom_agents/tests/test_ai_devtest.py
git commit -m "feat(agents): ai_devtest agent — bootstrap + 打包 backend/frontend/scripts + 取最新 test-report"
```

---

## Task 8：启动脚本 + 全量测试

**Files:**
- Create: `phantom_agents/scripts/start-ai-plan.sh`
- Create: `phantom_agents/scripts/start-ai-design.sh`
- Create: `phantom_agents/scripts/start-ai-devtest.sh`

- [ ] **Step 1: 写三个启动脚本（内容只在 agent 名上有差异）**

`scripts/start-ai-plan.sh`：

```bash
#!/usr/bin/env bash
# 在 phantom_agents 目录下跑：bash scripts/start-ai-plan.sh
set -e
cd "$(dirname "$0")/.."
mkdir -p logs
nohup .venv/bin/python -m phantom_agents.ai_plan > logs/ai-plan.log 2>&1 &
echo "ai-plan PID=$! → logs/ai-plan.log"
```

同 pattern 写 `start-ai-design.sh`（替 `ai_plan` 为 `ai_design`）和 `start-ai-devtest.sh`（替 `ai_plan` 为 `ai_devtest`）。

```bash
chmod +x phantom_agents/scripts/*.sh
```

- [ ] **Step 2: 跑全量测试**

Run: `cd phantom_agents && .venv/bin/pytest -v`
Expected: 全部 PASS（runner: 11，ai_plan: 6，ai_design: 6，ai_devtest: 7）共 30 个

- [ ] **Step 3: 烟测启动（不要求真的连 scheduler）**

```bash
cd phantom_agents
AIJUICER_SERVER=http://nonexistent:9999 .venv/bin/python -m phantom_agents.ai_plan &
PID=$!
sleep 3
# 期望：进程在跑（连不上 server 时 SDK 会指数退避重试，不会立即崩）
ps -p $PID >/dev/null && echo "ai-plan 进程存活，SDK 正在退避重试"
kill -TERM $PID
wait $PID 2>/dev/null || true
```

Expected: "ai-plan 进程存活，SDK 正在退避重试" 显示出来；进程能被 SIGTERM 优雅终止。

- [ ] **Step 4: 提交**

```bash
git add phantom_agents/scripts/
git commit -m "feat(agents): nohup 启动脚本（每个 agent 一份），日志落 phantom_agents/logs/"
```

---

## Task 9：端到端集成手册（README 补充 + 实际跑一次）

**Files:**
- Modify: `phantom_agents/README.md`

- [ ] **Step 1: README 补"端到端验证清单"**

追加：

```markdown
## 端到端验证（首次部署后）

前置：本机 AIJuicer scheduler + Redis 已起（参考 AIJuicer/Makefile 的 `make dev`）。

1. 起三个 phantom agent：

   ```bash
   cd phantom_agents
   bash scripts/start-ai-plan.sh
   bash scripts/start-ai-design.sh
   bash scripts/start-ai-devtest.sh
   tail -f logs/ai-plan.log    # 看到 "agent.registered" 即成功
   ```

2. 在 AIJuicer Web UI（默认 http://127.0.0.1:3000）创建 workflow，
   或者命令行：

   ```bash
   cd ../AIJuicer
   python -m sdk.examples.ai_finder --topic "构建 Todo App + PostgreSQL + React" --auto
   ```

3. 观察 6 个 step 依次变绿。`plan` / `design` / `devtest` 三步会调到我们的 agent；
   每步的 artifact 在详情页查看：
   - `plan.md`（plan 步） → 完整的 plan.locked.md 内容
   - `ui-design.md` + `ui-design.tar.gz`（design 步） → 解开能看到 .phantom/ui-design/*.html
   - `test-report.md` + `code.tar.gz` + `runtime.json`（devtest 步）

4. 点 UI 的"重新执行 plan" 给反馈"加上搜索功能"，观察 plan agent 用 attempt=2 重跑，
   产物被新版 plan.md 覆盖，并且原版本（`plan.first.md`）保留。

5. 排错：
   - agent 起不来：`curl $AIJUICER_SERVER/health` / `redis-cli ping`
   - phantom 子进程失败：看 `logs/ai-<step>.log`，最后的 `phantom 子进程失败` 段会带末尾 20 行
   - workspace 路径不对：检查 scheduler 的 `AIJUICER_ARTIFACT_ROOT` env，应该指向 `<wf_id>` 上一级
```

- [ ] **Step 2: 提交**

```bash
git add phantom_agents/README.md
git commit -m "docs(agents): README 加端到端验证清单 + 排错指南"
```

---

## 自审清单（实施完成后跑一遍）

- [ ] **覆盖性**：用户提出的 3 条 Plan agent 要求 + 3 条 Design + 4 条 DevTest 都对应到具体 task？是
  - "单独的 worker"：每个 agent 都是独立 Python 进程（Task 5/6/7 的 `if __name__ == "__main__": agent.run()`）
  - "接入到 aijuicer 的 X 节点"：`Agent(step="plan"/"design"/"devtest")` 各自指定
  - "首次接收 handler，按需求文档进行规划"：plan agent Task 5 的 `_first_run_invokes_phantom_plan_with_requirement_file` 测试
  - "重跑指令"：每个 agent 都测了 with_feedback / without_feedback / attempt>1 三种重跑分支
  - "产出物"：plan = plan.md；design = ui-design.md + ui-design.tar.gz；devtest = code.tar.gz + test-report.md + runtime.json
  - "DevTest 接收 plan 和 design"：Task 7 的 `_missing_plan_locked_fetches_both_plan_and_design` 测试

- [ ] **类型一致**：所有 agent 都用 `dict[str, Any]` 作为返回类型；artifact key 命名规范（`plan.md` / `ui-design.md` / `ui-design.tar.gz` / `code.tar.gz` / `test-report.md` / `runtime.json`）下游可消费

- [ ] **错误分类**：runner 的 `classify_phantom_failure` 区分 retryable / fatal，每个 agent 都用它转换 PhantomFailedError

- [ ] **AIJuicer 工作流目录约定**：所有 agent 一致使用 `resolve_workspace(task["input"]["project_name"])` 当 cwd，base = `/Users/lapsdoor/phantom`（`PHANTOM_PROJECTS_BASE` env 可覆盖）

- [ ] **TDD 顺序**：每个 task 严格按 写 test → 跑 fail → 写实现 → 跑 pass → commit

- [ ] **Commit 粒度**：9 个 commit（task 1～9 各一），每个独立可回滚，message 用 conventional commit 前缀

- [ ] **Phantom CLI 调用**：所有路径都通过 `subprocess.create_subprocess_exec("phantom", args, cwd=workspace)`，环境变量从父进程继承（PHANTOM_GENERATOR_BACKEND / OPENAI_API_KEY 等透传）

---

## 执行 Handoff

**Plan 完整保存到 `docs/superpowers/plans/2026-04-24-phantom-aijuicer-agents.md`。两种执行方式：**

**1. Subagent-Driven（推荐）** — 每个 task 派一个新 subagent，task 之间停顿 review，迭代快。

**2. Inline Execution** — 在当前会话里按顺序执行，批量跑、按 commit 粒度 review。

**选哪种？**
