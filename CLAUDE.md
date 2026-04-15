# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Phantom AutoDev 是一个 **bash 驱动的元工具**：它编排另一个 AI CLI（Claude Code 或 OpenAI Codex）来自动完成「需求 → 规划 → 开发 → 测试 → Docker 部署」的全流程。本仓库本身没有应用代码或测试套件——它是一个 shell + prompt 框架，被编排的 AI CLI 在 `projects/<name>/` 下生成目标项目。

## 常用命令

```bash
# 从需求启动（第一个参数可选 claude/codex 切换后端，默认 claude）
./phantom.sh requirements.md
./phantom.sh "构建 Todo API，Node.js + Express，端口 3000"
./phantom.sh codex requirements.md

# 恢复 / 删除
./phantom.sh --resume [项目名]
./phantom.sh --delete [项目名]
```

本仓库没有构建/lint/test 命令——改动提示词或 shell 后，唯一的验证方式是对一个真实需求跑一次 `./phantom.sh` 端到端，观察 `projects/<name>/.phantom/logs/` 下的日志。`test/sample-requirements.md` 是最小的 smoke-test 输入。

依赖：`claude` 或 `codex` CLI、`jq`、`python3`、`docker`（部署阶段才需要）。

## 架构

三层：`phantom.sh`（入口/CLI 解析）→ `lib/phases.sh`（阶段状态机）→ `lib/loop.sh`（AI 后端抽象 + 模板渲染）。阅读顺序就是这个。

### 后端抽象（`lib/loop.sh`）

只有两个真正的执行函数：`_claude_run` 和 `_codex_run`。所有阶段都走 `ai_run <role> <prompt> <log>` 派发，plan 阶段额外有 `ai_run_plan`（codex 需要英文规划指令注入）。**没有**会话延续——devtest 全程都是干净上下文（**Context Reset** 设计），跨轮信息靠 `.phantom/` 下的交接文件。

后端选择按角色分别解析：`PHANTOM_<ROLE>_BACKEND` → `PHANTOM_BACKEND` → `claude`。角色：`generator` / `reviewer` / `plan` / `deploy`。这允许 generator 用一个后端、reviewer 用另一个，打破"同模型自检"的偏置幻觉（CLI 标志：`--generator` / `--reviewer` / `--backend`）。

所有输出经 `lib/stream-parser.py` 解析（Claude `stream-json` / Codex `--json` JSONL），写入 `$LOG_DIR/phase-*.log`。

### 阶段流程（`lib/phases.sh`）

三个阶段，均由 `render_prompt` 从 `prompts/*.md` 填充模板后执行。模板占位符：`{{REQUIREMENTS}}` / `{{PLAN}}` / `{{PROGRESS}}` / `{{OPEN_ISSUES}}` / `{{FILE_MAP}}` / `{{LAST_REVIEW}}` / `{{REVIEW_STAGE}}` / `{{EXTRA_NOTE}}` / `{{PROJECT_DIR}}` / `{{HOME}}`。

1. **`run_plan_phase`** — 跑 `prompts/plan.md`，产物必须是 `.phantom/plan.md`。最多 3 次尝试，第 2/3 次会通过 `PHANTOM_EXTRA_NOTE` 注入"上次没生成，请直接 Write 文件"的强约束。注意：**没有**真正使用 Claude 的 `--permission-mode plan`，只靠 prompt 顶部的"只允许写 .phantom/plan.md"约定。
2. **`run_devtest_phase`** — **核心设计**。分两个 Stage：
   - **Stage A（开发）** 最多 `dev_max=8` 轮 Generator→Reviewer 配对：generator 跑 `develop.md`，reviewer 跑 `review.md`（`PHANTOM_REVIEW_STAGE=dev_implementation`）。
   - **Stage B（测试）** 最多 `test_max=10` 轮 Tester→Reviewer→Fix 循环：`test.md` → `review.md`（`PHANTOM_REVIEW_STAGE=test_quality`），reject 时跑 `fix-from-test.md`。
   - 两个 Stage 切换时 `reset_last_review` 清空 `.phantom/last-review.json`，避免污染。
   - **每轮 generator 之后** `run_generator_round` 校验 `.phantom/progress.md` 行数是否增长，没增长就触发一轮"补 progress.md"补救，这是 Context Reset 的命脉保护。
   - **完成判定**统一靠读 `.phantom/last-review.json` 的 `verdict` 字段（`pass` / `fail`），不再用 `PHASE_COMPLETE` token。Reviewer 输出后 shell 端 `jq empty` 校验 JSON 合法性，非法 → 强制 fail。
3. **`run_deploy_phase`** — 最多 3 次 `deploy.md`（Docker build/run/curl），仍用 `PHASE_COMPLETE`，但收紧为只在日志最后 10 行内匹配独占行（`grep -qx`）避免误判。

### Strict 模式

`PHANTOM_STRICT=1`（或 `--strict` 标志）：任意阶段达到最大轮次直接 `exit 1`，不再 `forced_advance`。默认行为是把 `phases.<name>.forced_advance=true` 写入 `state.json`，`--resume` 时显著警告用户。

### 跨轮交接物（Context Reset 模式的命脉）

因为每轮都是 fresh context，上下文不能靠会话历史，只能靠 `.phantom/` 下这些文件：`progress.md`、`open-issues.md`、`file-map.md`、`last-review.json`、`plan.md`。`render_prompt`（`lib/loop.sh:12`）把它们读进来替换 `{{PROGRESS}}` / `{{OPEN_ISSUES}}` / `{{FILE_MAP}}` / `{{LAST_REVIEW}}` / `{{PLAN}}` / `{{REQUIREMENTS}}` / `{{PROJECT_DIR}}` / `{{HOME}}` 占位符。**改 prompt 时必须理解：generator 靠这些文件知道上一轮干了什么，reviewer 靠这些文件给出新的 verdict；破坏写入/读取这些文件的约定等于切断跨轮记忆。**

### 状态与项目布局

`lib/state.sh` 负责 `.phantom/state.json` 的读写（`get_state` / `set_phase_status` / `increment_iteration` / `advance_phase`）。每个项目目录结构：

```
projects/<name>/
  .phantom/
    state.json       # 阶段 + 迭代计数 + 需求文件路径
    plan.md          # plan 阶段产物
    progress.md, open-issues.md, file-map.md, last-review.json  # 交接物
    logs/phase-*.log # 每轮原始输出
  src/, Dockerfile, ...  # 编排出的目标项目
```

`--resume` 通过读 `state.json` 的 `current_phase` 跳到对应阶段函数继续。

## 修改指引

- **改工作流顺序/轮数**：只动 `lib/phases.sh`，不要把逻辑塞到 prompts 里。
- **改 AI 的行为/方法论**：只动 `prompts/*.md`，不要为此修改 shell。
- **加新后端**：在 `lib/loop.sh` 里补 `_<name>_new` / `_new_plan` / `_continue` / `_fresh` 四个函数，再在 `ai_*` dispatch 里加 case；`stream-parser.py` 也要能解析它的 JSONL 格式。
- **改交接文件契约**：`render_prompt` 和 **所有** 引用占位符的 `prompts/*.md` 必须一起改，否则某些阶段会拿到空字符串静默失败。
- **完成判定**：reviewer 阶段（dev/test）走 `.phantom/last-review.json` 的 `verdict` 字段；deploy 阶段走 `tail -n 10 ... | grep -qx "PHASE_COMPLETE"`。改 prompt 时必须保持对应输出格式。
- `prompts/verify-dev.md` 和 `prompts/verify-test.md` 是历史遗留死文件，当前 `phases.sh` 不再引用——不要往里加东西，要改就直接改 `review.md`。

## 用户偏好（来自全局 CLAUDE.md）

- 用中文交流。
- 后端代码必须结构化日志（含 timestamp/level/message/request_id），禁止 `print`/`console.log`——这条规则适用于被编排出的目标项目，本仓库的 shell 日志函数在 `lib/utils.sh`。
