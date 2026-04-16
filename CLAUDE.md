# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Phantom AutoDev 是一个 **bash 驱动的元工具**：它编排 AI CLI（Claude Code 或 OpenAI Codex）自动完成「需求 → 规划 → 开发 → 代码审查 → 部署 → 测试 → 下一个 feature」的全流程，参考 [Anthropic Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) 的 harness 模式。本仓库是 shell + prompt 框架，被编排的 AI CLI 在 `$PWD/<name>/` 下生成目标项目。

## 常用命令

```bash
# 从需求启动
phantom requirements.md
phantom "构建 Todo App + PostgreSQL + React 前端"
phantom --generator codex requirements.md       # generator 用 codex（evaluator 角色自动选 claude）

# 恢复 / 删除
phantom --resume [项目名]
phantom --delete [项目名]

# strict：任意 feature 达到 max rounds 直接失败
phantom --strict requirements.md

# fast：降低 min rounds 地板（烟测用）
phantom --fast requirements.md
```

本仓库没有构建 / lint / test 命令——改动 shell 或 prompt 后，唯一的验证方式是对一个真实需求跑一次 `phantom` 端到端，观察 `<project>/.phantom/logs/` 和 `<project>/.phantom/test-report-iter*.md`。

依赖：`claude` 或 `codex` CLI、`jq`、`python3`、`docker`、`curl`、可选 `postgres` MCP。

## 架构（harness v2）

三层：`phantom.sh`（入口 + 主循环）→ `lib/phases.sh`（5 个 phase 函数）→ `lib/loop.sh`（AI 后端抽象 + 跨模型解析 + compaction）。阅读顺序就是这个。

### 顶层流程

```
 plan ──▶ plan-review ──▶ plan ──▶ [dev ──▶ code-review ──▶ deploy ──▶ test]×group ──▶ done
  R1           R2          R3        │           │             │          │
                                     ▲           │             │          │
                                     └───────────┴─────────────┴──────────┘
                                       return-packet 回流
```

- **Plan phase 一次性跑**：plan R1 → plan-review R2 → plan R3 → 冻结成 `.phantom/plan.locked.md`
- **主循环按 feature group 走**：plan 把 feature 按功能相关性分组（2-4 组），每组 2-4 个 feature；一组走完 `dev → code-review → deploy → test` 一整圈才进下一组
- **任一站失败回流 dev**：code-review reject / deploy 失败 / test 分数 < 80 都写 `.phantom/return-packet.md` 退回 dev

### 后端抽象（`lib/loop.sh`）

两个执行函数：`_claude_run_new` / `_claude_run_continue` 和 `_codex_run_new` / `_codex_run_continue`。

`ai_run <role> <prompt> <log>` 根据 `.phantom/sessions/<role>-<backend>` 标记文件自动选 new / continue 模式——首次调用某 role+backend 时启动新会话，之后用 `-c` / `resume --last` 继续（compaction）。

`ai_run_oneshot <role> <prompt> <log>` 用于 plan phase 的短会话（每 round 独立）。

### 后端解析（`lib/loop.sh::resolve_backend`）

```
PHANTOM_<ROLE>_BACKEND → 若是 cross_model_role → 自动选与 generator 不同的后端 → PHANTOM_BACKEND → claude
```

角色：`generator / plan_reviewer / code_reviewer / tester / deploy`。其中 `plan_reviewer / code_reviewer / tester` 默认**强制跨模型**。

### Phase 函数（`lib/phases.sh`）

1. **`run_plan_phase`** — R1 planner 起草 plan（`_plan_has_required_sections` 关键字校验 4 个核心章节）→ R2 plan-reviewer 跨模型审 rubric（无产出也 OK，降级为"无意见"）→ R3 planner 根据 comments 修订 → `cp plan.md plan.locked.md` 冻结 → 解析 feature 分组（`list_feature_groups_from_plan`，至少 5 个 feature、2+ 个 group）
2. **`run_dev_phase`** — 单次 dev round。注入当前 group 的 feature 列表（逗号分隔），走 `ai_run generator`（compaction），一次实现整组所有 feature。校验 `changelog.md` 新增 `## Iteration N` 条目，没增加则触发补救 round。完成后归档并清除 return-packet
3. **`run_code_review_phase`** — 单次 review round。走 `ai_run code_reviewer`（跨模型），校验 `last-code-review.json` 合法 + verdict=pass；pass 后还要跑 `lib/code-review.sh::run_shell_code_review` shell 兜底 grep，任一命中降级为 fail 并写 return-packet
4. **`run_deploy_phase`** — 单次 deploy round，内部自试 2 次。AI 只写 Dockerfile，shell 侧跑四项判断：docker build 退出码 == 0 + docker run 退出码 == 0 + 容器 60s 内 running + 每端点 happy path curl 非 5xx。失败 2 次后写 return-packet 回 dev
5. **`run_test_phase`** — 单次 test round。走 `ai_run tester`（跨模型），tester 生成 Playwright 测试脚本（`.playwright/tests/`）并执行 + curl 跑所有端点所有场景，按 rubric 打分写 `test-report-iter<N>.md`。Shell 解析 `.playwright/results.json` 日志输出 pass/fail 兜底，提取总分 ≥80 pass，否则 fail 并写 return-packet。可用 Chrome DevTools MCP 辅助调试失败场景

### Group 迭代（`phantom.sh::run_group_sprint`）

```
for each group in plan.locked.md Feature 列表:
  for round in 1..max_rounds:
    run_dev_phase(group的所有feature)
    run_code_review_phase  (reject → continue loop)
    run_deploy_phase       (fail → continue loop)
    run_test_phase         (<80 → continue loop)
    if round >= min_rounds: break (group done)
    else: shell 写"强制打磨"return-packet 继续 loop
```

每 group `min_rounds=2`（`--fast` 时 `=1`），`max_rounds=6`。达 max strict 模式 exit 1，默认 `mark_forced_feature` 标记组内所有 feature 继续。

**Plan 分组格式**：Feature 列表中用 `### group-N: name` 做分组标题，组内 feature 用 `#### feature-N-slug`。也兼容旧格式（H3 直接是 feature slug，每个自成一组）。

### Handoff 文件（`.phantom/` 下）

| 文件 | 作用 |
|---|---|
| `state.json` | Phase 状态 + `current_group_index` + `test.forced_features[]` |
| `plan.md` | Phase 1 工作稿 |
| `plan.locked.md` | Phase 1 冻结版（主循环读） |
| `plan-review-comments.md` | R2 产物 |
| `changelog.md` | dev 每轮追加 |
| `return-packet.md` | 当前回流包（每次重写，旧的归档到 logs/） |
| `last-code-review.json` | code-review 结构化 verdict |
| `test-report-iter<N>.md` | 每 test round 的评分报告 |
| `port` | 预分配端口（socket bind(0) 拿到） |
| `sessions/<role>-<backend>` | compaction 会话标记（空文件，存在即代表已启动） |
| `logs/` | 每 phase 每 round 原始输出 |

### Shell 侧确定性判断

不让 AI 自己说"我做完了"，可机械化的事全由 shell 做：

- Plan 的核心章节：`_plan_has_required_sections` 关键字 grep（产品目标/Feature列表/API约定/评分标准）
- Changelog 新增：`grep -c '^## Iteration '` 前后对比
- Code-review 兜底：`lib/code-review.sh::run_shell_code_review` 5 类 grep
- Deploy gate：docker 退出码 + `docker ps --filter status=running` + `curl -w '%{http_code}'`
- Test 分数：从 report 的"总分: X/100"提取

### Strict / Fast 模式

- `PHANTOM_STRICT=1` / `--strict`：group 达到 max_rounds 直接 `exit 1`
- `PHANTOM_FAST=1` / `--fast`：`DEV_MIN_ROUNDS=1`（跳过"强制打磨"轮）

## 修改指引

- **改工作流顺序 / 轮数 / gate**：只动 `lib/phases.sh`（各 phase 函数）或 `phantom.sh::run_group_sprint`，不要把逻辑塞进 prompt
- **改 AI 的方法论**：只动 `prompts/*.md`，不要因此修 shell
- **加新后端**：在 `lib/loop.sh` 补 `_<name>_run_new` / `_run_continue` 两个函数，`resolve_backend` 的 `_detect_available_backends` 加检测，`ai_run` 的 case 加 dispatch；`stream-parser.py` 要能解析它的 JSONL
- **改 handoff 文件契约**：`render_prompt` 和**所有**引用占位符的 `prompts/*.md` 必须一起改
- **改完成判定**：
  - plan phase → 改 `_plan_has_required_sections` 的 grep 关键字
  - dev phase → 改 changelog line-growth check
  - code-review phase → 改 `lib/code-review.sh` 的 grep 列表
  - deploy phase → 改 shell 四项中的判断逻辑
  - test phase → 改 `_extract_score_from_report` 或 `run_test_phase` 的阈值
- **改跨模型规则**：改 `lib/loop.sh::CROSS_MODEL_ROLES` 列表

## 用户偏好（来自全局 CLAUDE.md）

- 用中文交流
- 被编排出的目标项目必须结构化日志（含 timestamp/level/message/request_id），禁止 `print`/`console.log`——这条规则在 `prompts/develop.md` 和 `prompts/code-review.md` 里落地
- 数据库必须 PostgreSQL + postgres MCP——在 `prompts/plan.md` 和 `prompts/develop.md` 里落地
