# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

`ai-plan` 是 AIJuicer 流水线 **`plan` step 的 worker**：从 scheduler 拉任务 → 在 phantom 工作区跑 `phantom --plan` → 上传 `plan.md` 产物。它是 phantom CLI 的薄封装，自身不做规划逻辑。

## 常用命令

```bash
# 安装（必须 Python 3.12+）
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# 跑全部测试
.venv/bin/pytest -v

# 跑单个测试
.venv/bin/pytest tests/test_agent.py::test_first_run_invokes_phantom_plan_with_requirement_file -v

# 后台启动 worker（连 scheduler 拉任务）
bash scripts/service.sh start
tail -f logs/ai-plan.log

# 前台跑（调试用）
.venv/bin/python -m ai_plan.agent
```

## 架构关键点

### 包路径映射陷阱
`pyproject.toml` 把仓库根目录映射成 `ai_plan` 包（`package-dir = {"ai_plan" = "."}`）。**仓库内部 import 必须写 `from ai_plan.runner import ...`，不能写 `from runner import ...`**。`agent.py` 在根目录但导入时是 `ai_plan.agent`。

### 控制流（agent.py）
单 handler `handle(ctx)`，三条路径分支由**工作区状态**决定，不是 `ctx.attempt`：

| 工作区状态 | 用户反馈 | phantom 命令 |
|---|---|---|
| 无 `.phantom/state.json`（首跑） | — | `phantom --plan <requirement.md路径>` |
| 已有 state.json + 有 feedback | 字符串 | `phantom --plan <feedback字符串>` |
| 已有 state.json + 无 feedback | — | `phantom --plan`（synthetic refresh） |

**不要用 `ctx.attempt` 判断 rerun**：前几次 attempt 可能因 SDK / 上游问题 fatal 根本没跑到 phantom，工作区还是空的。`workspace_has_phantom_state()` 是唯一可靠信号。

### 工作区解析（runner.py）
- 路径 = `PHANTOM_PROJECTS_BASE / project_name`，默认 base = `/Users/lapsdoor/phantom`
- `resolve_workspace` 会拒绝含 `/`、以 `..` 或 `.` 开头的 `project_name`（防目录逃逸）
- 上游 `idea` / `requirement` step 已在该路径下写过文件；本 worker 幂等创建目录，不破坏已有内容

### phantom 子进程
- 子进程 cwd = workspace（phantom 在那里读写 `.phantom/state.json`）
- 父进程环境**全量继承**（`PHANTOM_GENERATOR_BACKEND` / `PHANTOM_CODE_REVIEWER_BACKEND` / `OPENAI_API_KEY` 等都靠这个透传）
- stdout 每行 → `ctx.heartbeat()`；stderr 单独缓冲，仅在失败时随异常上报
- 找不到 `phantom` 二进制 → 提示先在 PhantomCLI 仓库跑 `./install.sh`

### 错误分类（runner.py: `classify_phantom_failure`）
phantom 子进程失败时根据 stdout+stderr 关键字决定异常类型：
- `_RETRYABLE_PATTERNS`（超时 / rate limit / 连接失败）→ `RetryableError`，scheduler 会重试
- `_FATAL_PATTERNS`（plan.locked.md 已存在 / max_rounds / 找不到 phantom CLI）→ `FatalError`，不重试
- 默认乐观策略：未知失败 → `RetryableError`

新增关键字时同时改这两个元组，并在 `tests/test_runner.py` 加 case。

### 产物校验
`run_phantom` rc=0 ≠ 成功。必须额外校验 `.phantom/plan.locked.md` 存在；不存在则抛 `FatalError`（不要静默成功）。产物以 `plan.md` 名上传给 scheduler。

## 测试约定

- `pytest-asyncio` 用 `auto` 模式，不需要显式 `@pytest.mark.asyncio`（但代码里仍标了，保持一致即可）
- `tmp_workspace_base` fixture 把 `PHANTOM_PROJECTS_BASE` 指到 `tmp_path`，**所有测试都该用它**，避免污染真实 `~/phantom`
- 子进程测试用 `tests/fakes/fake_phantom.sh` 这个 shell 脚本模拟 phantom，靠 `phantom_bin` 参数注入
- `agent.handle` 测试用 `unittest.mock.patch("ai_plan.agent.run_phantom", ...)` 替换子进程调用
