# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Phantom AutoDev 是一个 **bash 驱动的元工具**：它编排 AI CLI（Claude Code 或 OpenAI Codex）自动完成「需求 → 规划 → 开发 → 代码审查 → 部署 → 测试 → 下一个 feature」的全流程，参考 [Anthropic Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) 的 harness 模式。本仓库是 shell + prompt 框架，被编排的 AI CLI 在 `$PWD/<name>/` 下生成目标项目。

## 常用命令

```bash
# ── 新项目（跑全流程 plan → design → dev-test）──
phantom requirements.md
phantom "构建 Todo App + PostgreSQL + React 前端"
phantom --generator codex requirements.md       # generator 用 codex（evaluator 角色自动选 claude）

# ── 已有项目：三个模式 + 一个单节点 ──
# "在现有项目上追加需求" 的主入口；在 .phantom/ 所在目录里跑：
phantom "请添加列表搜索功能"                     # 字符串 + 无 flag → 默认进入 --plan 增量
phantom --plan "请重新考虑 rubric 权重"           # 只跑 plan 模式（R1→R2→R3）
phantom --plan                                   # 纯重规划（注入 synthetic refresh amendment，保留结构）
phantom --design "UI 改成暖色调"                  # 只跑 design 模式（R1→R2→R3）
phantom --dev-test "feature-3 点击没反应"         # 只跑 dev→code-review→deploy→test 一圈（不打磨）
phantom --test                                   # 只重跑 test 一次（不回流 dev）
phantom --test "重点测登录失败场景"               # 带 extra note 给 tester

# ── 恢复 / 删除 ──
phantom --resume [项目名]
phantom --delete [项目名]

# ── 修饰 flag（可叠加）──
phantom --strict requirements.md                 # 任意 group 达到 max rounds 直接失败
phantom --fast requirements.md                   # 降低 min rounds 地板（烟测用）
```

**模式 flag 的通用规则**：

| 调用 | 无 `.phantom/state.json` | 有 `.phantom/state.json` |
|---|---|---|
| 文件需求（无 mode flag） | 新项目全流程 | **报错**（歧义，要显式 `--plan <file>`） |
| 字符串需求（无 mode flag） | 新项目全流程 | 自动走 `--plan` 增量 |
| `--plan [参数]` | 要求需求；新项目只跑 plan | 只跑 plan；带参→写 amendment；无参→synthetic refresh |
| `--design [参数]` | **报错** | 只跑 design；带参→写 amendment |
| `--dev-test [参数]` | **报错** | 只跑 dev-test；带参→构造 return-packet |
| `--test [参数]` | **报错** | 只重跑 test；带参→作为 extra-note 传给 tester |

**已弃用 flag**（保留兼容 + warn 一次，下个大版本删）：`--plan-only`（→ `--plan`）、`--ui-only`（→ `--design`）、`--skip-plan`（→ `--dev-test`）、`--test-only`（→ `--dev-test` + `PHANTOM_TEST_ONLY=1`）

本仓库没有构建 / lint / test 命令——改动 shell 或 prompt 后，唯一的验证方式是对一个真实需求跑一次 `phantom` 端到端，观察 `<project>/.phantom/logs/` 和 `<project>/.phantom/test-report-iter*.md`。

依赖：`claude` 或 `codex` CLI、`jq`、`python3`、`curl`、可选 `postgres` MCP、可选 `playwright`（前端 E2E）。Deploy 通过启动脚本 + `nohup` 常驻进程。

## 架构（harness v2）

三层：`phantom.sh`（入口 + 主循环）→ `lib/phases.sh`（5 个 phase 函数）→ `lib/loop.sh`（AI 后端抽象 + 跨模型解析 + compaction）。阅读顺序就是这个。

### 顶层流程

phantom 有三种"模式"，每种独立可重入。无 flag 串起来就是全流程：

```
[--plan]      plan R1 ──▶ plan-review R2 ──▶ plan R3              ──▶ .phantom/plan.locked.md
[--design]    design R1 ──▶ design-review R2 ──▶ design R3         ──▶ .phantom/ui-design/*.html
[--dev-test]  ┌──▶ dev ──▶ code-review ──▶ deploy ──▶ test ──┐  ×group-per-sprint
              │         │           │           │             │
              │         ▼           ▼           ▼             ▼
              └──── return-packet 回流，上限 max_rounds ─────┘
[--test]      test（独立重跑，不回流 dev）
[无 flag]     plan → design → dev-test 全跑一遍
```

- **plan 模式**（`run_plan_phase`）：R1 planner 起草 → R2 plan-reviewer 跨模型审 → R3 planner 修订 → `cp plan.md plan.locked.md` 冻结
- **design 模式**（`run_ui_design_phase`）：R1 designer 通过 Stitch MCP 为每屏生成 HTML → R2 ui_design_reviewer 跨模型审 → R3 designer 根据 comments 修订；`_plan_has_frontend` 判纯后端项目则 skip；R1 失败（0 screen 产出）则 skip R2/R3 降级
- **dev-test 模式**（`_run_group_sprint_loop`）：主循环按 feature group 走。plan 把 feature 按相关性分组（2-4 组），每组 2-4 个 feature；一组走完 `dev → code-review → deploy → test` 一整圈才进下一组。任一站失败回流 dev（code-review reject / deploy 失败 / test 分数 <90 都写 `return-packet.md`）。`--dev-test` 模式跑通就收手（`PHANTOM_NO_POLISH=1` 跳过强制打磨）
- **test 模式**（`run_test_only_phase`）：仅重跑 test 一次，**不**回流 dev；用户触发，失败给提示让用户 `--dev-test` 修复

### 增量需求（amendment）

所有**已有项目**的模式都支持"带参数运行"：

- `--plan [str|file]` / `--design [str|file]` → 写入 `.phantom/amendment.md`，plan.md / ui-design.md prompt 的 `{{AMENDMENT}}` 占位符读取；prompt 的"增量修订规则"段要求 AI 保留原有编号、只追加 / 修改增量指向的部分
- `--dev-test [str]` → 走 `write_user_return_packet` 构造 `return_from: user-amendment` 的 return-packet，dev 当成"最高优先级必修项"消化
- `--test [str]` → 写入 `.phantom/test-extra-note.md`，tester 通过 `{{EXTRA_NOTE}}` 占位符读取，一次性使用后清除

每个模式跑完后 `clear_amendment` 清空 amendment（防跨模式泄漏）。

### 后端抽象（`lib/loop.sh`）

两个执行函数：`_claude_run_new` / `_claude_run_continue` 和 `_codex_run_new` / `_codex_run_continue`。

`ai_run <role> <prompt> <log>` 根据 `.phantom/sessions/<role>-<backend>` 标记文件自动选 new / continue 模式——首次调用某 role+backend 时启动新会话，之后用 `-c` / `resume --last` 继续（compaction）。

`ai_run_oneshot <role> <prompt> <log>` 用于 plan phase 的短会话（每 round 独立）。

### 后端解析（`lib/loop.sh::resolve_backend`）

```
PHANTOM_<ROLE>_BACKEND → 若是 cross_model_role → 自动选与 generator 不同的后端 → PHANTOM_BACKEND → claude
```

角色：`generator / plan_reviewer / code_reviewer / tester / deploy / ui_designer / ui_design_reviewer`。其中 `plan_reviewer / code_reviewer / tester / ui_design_reviewer` 默认**强制跨模型**；`ui_designer` 特例**强制 claude**（Stitch MCP 只挂在 claude user-scope）。

### Phase 函数（`lib/phases.sh`）

1. **`run_plan_phase`** — R1 planner 起草 plan（`_plan_has_required_sections` 关键字校验 4 个核心章节）→ R2 plan-reviewer 跨模型审 rubric（无产出也 OK，降级为"无意见"）→ R3 planner 根据 comments 修订 → `cp plan.md plan.locked.md` 冻结 → 解析 feature 分组（`list_feature_groups_from_plan`，至少 5 个 feature、2+ 个 group）。若 `.phantom/amendment.md` 存在，`{{AMENDMENT}}` 占位符注入到 plan.md prompt，planner 执行"增量修订"语义
2. **`run_ui_design_phase`** — 仅前端项目（`_plan_has_frontend` 扫 plan.locked.md 的前端关键字）。R1 走 `ai_run ui_designer`（强制 claude）通过 Stitch MCP 生成 HTML 到 `.phantom/ui-design/<slug>.html` + `.json`、写总览 `.phantom/ui-design.md` → R2 走 `ai_run_oneshot ui_design_reviewer`（跨模型，自动选 codex）写 `.phantom/ui-design-review-comments.md` → R3 `ai_run ui_designer` 继续同会话按 comments 修订（复用原 Stitch `project_id` / `design_system_id`，只改需改的 screen）。**幂等**（非 force 场景跳过）、**降级不阻塞**（R1 产出 0 screen 则跳过 R2/R3）。纯后端项目整个 phase skip
3. **`run_dev_phase`** — 单次 dev round。**首次调用时 `ensure_ports` 分配后端/前端端口**（写到 `.phantom/port.backend` / `port.frontend`，后续 round 幂等跳过）；端口通过 `{{BACKEND_PORT}}` / `{{FRONTEND_PORT}}` 注入 prompt，AI 直接把端口**写死进代码 / 配置文件**（不走环境变量）。注入当前 group 的 feature 列表（逗号分隔），走 `ai_run generator`（compaction），一次实现整组所有 feature。校验 `changelog.md` 新增 `## Iteration N` 条目，没增加则触发补救 round。完成后归档并清除 return-packet
4. **`run_code_review_phase`** — 单次 review round。走 `ai_run code_reviewer`（跨模型），校验 `last-code-review.json` 合法 + verdict=pass；pass 后还要跑 `lib/code-review.sh::run_shell_code_review` shell 兜底 grep，任一命中降级为 fail 并写 return-packet
5. **`run_deploy_phase`** — 单次 deploy round，内部自试 2 次。AI 写 `scripts/start-backend.sh`（+ `start-frontend.sh` 如有前端），**脚本只负责 `exec` 启动命令，不再通过 `PORT` 环境变量传端口**（端口由 dev 写死进代码）。shell 侧：kill 旧 PID → `nohup` 启动新进程 → 读 `.phantom/port.backend` 等端口就绪（60s）→ smoke test（所有 API 端点 happy path curl 非 5xx）。成功后进程**常驻**（不清理），日志落到 `.phantom/runtime/{backend,frontend}.log`。失败 2 次后写 return-packet 回 dev
6. **`run_test_phase`** — 单次 test round。走 `ai_run tester`（跨模型）。E2E **默认用 Chrome DevTools MCP 实时驱动**（navigate/click/fill/take_snapshot/list_console_messages/list_network_requests/evaluate_script），**回退**用 Playwright 脚本（仅当需要重复跑、并行、持久化 storageState 或 MCP 做不到时）。curl 跑所有端点所有场景，按 rubric 打分写 `test-report-iter<N>.md`。Shell 如存在 `.playwright/results.json` 会解析并打 info 日志（非强制）；提取总分 ≥90 pass，否则 fail 并写 return-packet
7. **`run_test_only_phase`** — `--test` 模式专用。校验 runtime/backend.pid 进程在线后调用 `run_test_phase`；若 `.phantom/test-extra-note.md` 存在，作为 `PHANTOM_EXTRA_NOTE` 透传给 tester prompt。**失败不回流 dev**（只日志警示），让用户显式决定下一步

### Group 迭代（`phantom.sh::run_group_sprint`）

```
for each group in plan.locked.md Feature 列表:
  for round in 1..max_rounds:
    run_dev_phase(group的所有feature)
    run_code_review_phase  (reject → continue loop)
    run_deploy_phase       (fail → continue loop)
    run_test_phase         (<90 → continue loop)
    if round >= min_rounds: break (group done)
    if PHANTOM_NO_POLISH=1: break (--dev-test 模式跳过打磨)
    else: shell 写"强制打磨"return-packet 继续 loop
```

每 group `min_rounds=2`（`--fast` 时 `=1`，`PHANTOM_NO_POLISH=1`/`--dev-test` 时 `=0`），`max_rounds=6`。达 max strict 模式 exit 1，默认 `mark_forced_feature` 标记组内所有 feature 继续。

**Plan 分组格式**：Feature 列表中用 `### group-N: name` 做分组标题，组内 feature 用 `#### feature-N-slug`。也兼容旧格式（H3 直接是 feature slug，每个自成一组）。

### Handoff 文件（`.phantom/` 下）

| 文件 | 作用 |
|---|---|
| `state.json` | Phase 状态 + `current_group_index` + `test.forced_features[]` |
| `plan.md` | Phase 1 工作稿 |
| `plan.locked.md` | Phase 1 冻结版（主循环读） |
| `plan-review-comments.md` | plan R2 产物 |
| `ui-design.md` | UI design 总览（screen 清单 + Stitch project_id，仅前端项目） |
| `ui-design/<slug>.html` `ui-design/<slug>.json` | 每屏的 HTML 结构（dev 还原 UI 的依据）+ Stitch 返回的原始 JSON |
| `ui-design-review-comments.md` | design R2 产物 |
| `amendment.md` | `--plan` / `--design` 通过参数传入的增量需求文本；由 `{{AMENDMENT}}` 占位符读取，模式跑完 `clear_amendment` 清空 |
| `test-extra-note.md` | `--test "xxx"` 传入的测试侧重点；tester 通过 `{{EXTRA_NOTE}}` 读取；一次性使用 |
| `changelog.md` | dev 每轮追加 |
| `return-packet.md` | 当前回流包（每次重写，旧的归档到 logs/）；`return_from: user-amendment` 表示 `--dev-test "xxx"` 构造的用户请求 |
| `last-code-review.json` | code-review 结构化 verdict |
| `test-report-iter<N>.md` | 每 test round 的评分报告 |
| `port.backend` / `port.frontend` | 首次 dev phase 分配的端口（`socket.bind(0)` 拿到）；dev AI 直接把端口写死进代码，deploy / test 阶段 shell 侧读此文件用于等端口 + curl |
| `runtime/backend.pid` `runtime/frontend.pid` | 运行中进程的 PID（deploy 常驻） |
| `runtime/backend.log` `runtime/frontend.log` | 运行时 stdout+stderr 日志（debug 用） |
| `sessions/<role>-<backend>` | compaction 会话标记（空文件，存在即代表已启动） |
| `logs/` | 每 phase 每 round 原始输出 |

### Shell 侧确定性判断

不让 AI 自己说"我做完了"，可机械化的事全由 shell 做：

- Plan 的核心章节：`_plan_has_required_sections` 关键字 grep（产品目标/Feature列表/API约定/评分标准）
- Changelog 新增：`grep -c '^## Iteration '` 前后对比
- Code-review 兜底：`lib/code-review.sh::run_shell_code_review` 5 类 grep
- Deploy gate：启动脚本存在 + `nohup` 启动后 PID 存活 + 端口 60s 内可连 + 每端点 happy path curl 非 5xx
- Test 分数：从 report 的"总分: X/100"提取

### Strict / Fast / NO_POLISH 模式

- `PHANTOM_STRICT=1` / `--strict`：group 达到 max_rounds 直接 `exit 1`
- `PHANTOM_FAST=1` / `--fast`：`DEV_MIN_ROUNDS=1`（跳过"强制打磨"轮）
- `PHANTOM_NO_POLISH=1` / `--dev-test`：跑通一圈就 break（无视 `min_rounds`）——给增量修改用，不做打磨

## 修改指引

- **改工作流顺序 / 轮数 / gate**：只动 `lib/phases.sh`（各 phase 函数）或 `phantom.sh::run_group_sprint`，不要把逻辑塞进 prompt
- **改 AI 的方法论**：只动 `prompts/*.md`，不要因此修 shell
- **加新模式 flag**：在 `phantom.sh` 的 `_set_mode` case 段加；`run_all_phases` 的 case 段加对应分支；如需新 handoff 文件，`lib/state.sh` 加常量 + 辅助函数（`write_xxx`/`has_xxx`/`clear_xxx`）
- **加新后端**：在 `lib/loop.sh` 补 `_<name>_run_new` / `_run_continue` 两个函数，`resolve_backend` 的 `_detect_available_backends` 加检测，`ai_run` 的 case 加 dispatch；`stream-parser.py` 要能解析它的 JSONL
- **改 handoff 文件契约**：`render_prompt` 和**所有**引用占位符的 `prompts/*.md` 必须一起改
- **改完成判定**：
  - plan phase → 改 `_plan_has_required_sections` 的 grep 关键字
  - ui-design phase → 改 `_plan_has_frontend` 的前端关键字列表，或改 `run_ui_design_phase` 的 screen 计数校验
  - dev phase → 改 changelog line-growth check
  - code-review phase → 改 `lib/code-review.sh` 的 grep 列表
  - deploy phase → 改 shell 四项中的判断逻辑
  - test phase → 改 `_extract_score_from_report` 或 `run_test_phase` 的阈值
- **改跨模型规则**：改 `lib/loop.sh::CROSS_MODEL_ROLES` 列表（目前含 `plan_reviewer / code_reviewer / tester / ui_design_reviewer`）
- **ui_designer 后端特例**：`lib/loop.sh::resolve_backend` 里有一段硬编码 ui_designer 强制 claude（因 Stitch MCP 只在 claude user-scope）；若要改成配置，用 `PHANTOM_UI_DESIGNER_BACKEND` 环境变量覆盖即可
- **改增量语义**：plan/design 的增量行为由 `prompts/plan.md` 和 `prompts/ui-design.md` 的"增量修订（仅…非空）"段描述；shell 侧只管写 `.phantom/amendment.md` 和清空它，具体怎么融合 old+new 是 AI 的职责

## 用户偏好（来自全局 CLAUDE.md）

- 用中文交流
- 被编排出的目标项目必须结构化日志（含 timestamp/level/message/request_id），禁止 `print`/`console.log`——这条规则在 `prompts/develop.md` 和 `prompts/code-review.md` 里落地
- 数据库必须 PostgreSQL + postgres MCP——在 `prompts/plan.md` 和 `prompts/develop.md` 里落地
