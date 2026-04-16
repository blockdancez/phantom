# Phantom AutoDev

全自主需求开发程序 — 输入需求，自动完成从规划到部署的全流程。支持 Claude Code 和 OpenAI Codex 两种 AI 后端，**默认强制跨模型**（generator 写代码，evaluator 跨模型审查）。

## 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/blockdancez/phantom/main/install.sh | bash
```

或者手动安装：

```bash
git clone https://github.com/blockdancez/phantom.git
cd phantom
./install.sh
```

安装脚本会把 `phantom.sh` 软链到 `/usr/local/bin/phantom`（或 `~/.local/bin/phantom`），之后在**任何目录**都能调用 `phantom`。生成的项目会落在**当前工作目录**下。

卸载：`./install.sh --uninstall`

## 使用

```bash
# 在任意目录（项目生成在 $PWD 下）
cd ~/workspace
phantom requirements.md          # → ~/workspace/<auto-name>/

# 直接输入需求文本
phantom "构建一个 Todo App，Node.js + Express + PostgreSQL + React 前端"

# 指定 generator 后端（跨模型角色自动选另一个）
phantom --generator codex requirements.md

# 精确指定每个 role 的后端
phantom --generator claude --code-reviewer codex --tester codex requirements.md

# Strict 模式：任意 phase 达到 max rounds 直接失败
phantom --strict requirements.md

# Fast 模式：降低 min rounds 地板，快速烟测
phantom --fast requirements.md

# 只跑 plan 阶段（规划 + 评审 + 落锁），不写代码
phantom --plan-only requirements.md

# 跳过 plan，直接开发（需要 .phantom/plan.locked.md 已存在）
phantom --skip-plan --resume todo-app

# 恢复中断
phantom --resume                 # 交互选
phantom --resume todo-app

# 删除
phantom --delete                 # 交互选
```

## 默认技术栈与目录结构

除非需求明确指定其他技术，phantom 生成的项目默认采用：

| 层 | 默认技术 | 目录 |
|---|---|---|
| **后端** | Python 3.11+（FastAPI / uvicorn） | `backend/` |
| **前端** | React 18 + Vite + TypeScript | `frontend/` |
| **数据库** | PostgreSQL（硬性） | — |
| **包管理** | 后端 poetry / uv；前端 pnpm | — |
| **测试** | 后端 pytest；前端 vitest + Playwright | — |

**前后端强制分离**：有前后端的项目必须分为 `backend/` 和 `frontend/` 两个顶层目录，各自有独立的依赖声明和 lockfile。纯后端项目不建 `frontend/`，纯前端项目不建 `backend/`。

需求中可以指定其他技术栈（如"用 Go 写后端"、"用 Vue 做前端"），plan 阶段会自动适配。

## 工作流程（harness v2）

参考 [Anthropic Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) 的 harness 模式：

```
 plan ──▶ plan-review ──▶ plan ──▶ [dev ──▶ code-review ──▶ deploy ──▶ test]×group ──▶ done
  R1           R2          R3        │           │             │          │
                                     ▲           │             │          │
                                     └───────────┴─────────────┴──────────┘
                                       return-packet 回流（任一失败）
```

### Phase 1: plan（一次性）

Planner 把需求展开成 `.phantom/plan.md`，包含 4 个核心章节（产品目标 / Feature 列表 / API 约定 / 评分标准）和若干推荐章节（技术栈 / 数据模型 / 非功能需求 / 编码标准 / 部署配置等）。**明确反 YAGNI，鼓励野心大**。

Feature 按功能相关性分组（`### group-N: name` + `#### feature-N-slug`），每组 2-4 个 feature，组间低耦合。

内部 3 轮：

1. **R1 plan**：planner 起草
2. **R2 plan-review**：跨模型 reviewer 审 feature 列表 + 非功能需求 + rubric，**只提建议无否决权**
3. **R3 plan**：planner 根据 comments 修订，结束后冻结成 `.phantom/plan.locked.md`

### 主循环：Group-per-sprint

按 plan 的 feature 分组**一组 feature** 跑完整循环：

- **Dev**：Generator 在 compaction 长会话里一次实现整组 feature，写单元测试（核心覆盖率 ≥80%），跑静态检查（ruff/eslint/tsc 等）**0 error**，自修复无限
- **Code-review**：跨模型 reviewer 审 diff（placeholder / mock / 日志规范 / API 契约 / 安全红线），**shell 侧 grep 兜底**（TODO / FIXME / console.log / 硬编码端口 / 硬编码凭据）
- **Deploy**：Generator 写 Dockerfile，**shell 跑 docker build/run/smoke 并 curl 所有端点**，2 次自试后失败回 dev
- **Test**：跨模型 tester 用 Playwright MCP + curl 跑所有端点所有场景，按 rubric 打分。**累积测试所有已完成 feature**（防回归），总分 ≥ 80 过关

每 group `min_rounds=2`（打磨轮），`max_rounds=6`。达上限 strict 模式 exit 1，默认模式 `forced_feature` 标记继续。

### 收尾

所有 group sprint 完成后生成 `CLAUDE.md`，然后 `cp` 成 `AGENTS.md`（字节级一致）。

## 核心机制

### 强制跨模型评审

`plan_reviewer` / `code_reviewer` / `tester` 三个 evaluator 角色默认自动选一个和 `generator` **不同**的后端，打破"同模型自检"的盲区。只装一个后端时降级为同后端并 warn。

角色与环境变量：

| ROLE | 环境变量 | 默认跨模型 |
|---|---|---|
| `generator` | `PHANTOM_GENERATOR_BACKEND` | 否 |
| `plan_reviewer` | `PHANTOM_PLAN_REVIEWER_BACKEND` | **是** |
| `code_reviewer` | `PHANTOM_CODE_REVIEWER_BACKEND` | **是** |
| `tester` | `PHANTOM_TESTER_BACKEND` | **是** |
| `deploy` | `PHANTOM_DEPLOY_BACKEND` | 否 |

### Compaction 长会话

每个 role 维持一个跨 round、跨 group 的长会话（`claude -c` / `codex resume --last`），靠 CLI 原生 compaction 处理上下文膨胀。

### Return-packet 回流包

循环任一站失败（code-review reject / deploy fail / test < 80）都写 `.phantom/return-packet.md` 退回 dev，含：
- 必修项（硬性清单）
- 建议项（软性清单）
- 全量报告路径

Dev 下一轮开头必读。

### Shell 侧确定性判断

可机械化判断的事全部由 shell 做，不问 AI 主观判断：

- Plan 核心章节：关键字 grep（产品目标 / Feature 列表 / API 约定 / 评分标准）
- Changelog 是否新增 Iteration 条目：`grep -c`
- Code-review 兜底：`lib/code-review.sh` 跑 5 类 grep
- Deploy gate：`docker build` 退出码 + 容器 running + curl 非 5xx
- Test 分数：从 `test-report-iter*.md` 提取"总分"

## 项目结构

```
phantom.sh                  # 主入口：参数解析 + 主循环（group-per-sprint）
install.sh                  # 安装脚本（双模式：本地 + 远程一键装）
lib/
  utils.sh                  # 日志函数、依赖检查
  state.sh                  # .phantom/state.json 读写 + handoff 文件常量
  loop.sh                   # 后端抽象 + 跨模型解析 + compaction 调用
  phases.sh                 # 5 个 phase 函数 + feature 分组解析
  code-review.sh            # Shell 侧兜底 grep
  stream-parser.py          # 流式 JSON 解析器
prompts/
  plan.md                   # Planner：产出含分组的 plan
  plan-review.md            # Plan reviewer：跨模型审 rubric
  develop.md                # Generator：实现一组 feature + 单测 + 静态检查
  code-review.md            # Code reviewer：跨模型审 diff
  deploy.md                 # Deploy：写 Dockerfile
  test.md                   # Tester：跨模型 Playwright + 接口 + 评分
```

### 运行时生成（项目目录下）

```
<project>/
  .phantom/
    state.json              # 5 phase + current_group_index + forced_features
    plan.md                 # Phase 1 工作稿
    plan.locked.md          # Phase 1 冻结版（主循环读这个）
    plan-review-comments.md # Phase 1 R2 产物
    changelog.md            # dev 每轮追加
    return-packet.md        # 当前回流包
    last-code-review.json   # 最近一次 code-review 的 JSON verdict
    test-report-iter<N>.md  # 每轮 test 报告
    port                    # 预分配端口
    sessions/               # 每 role+backend 的会话标记（compaction）
    logs/                   # 每 phase 每 round 的原始输出
  backend/                  # 后端代码（Python 默认）
  frontend/                 # 前端代码（React 默认，纯后端项目无此目录）
  Dockerfile
  CLAUDE.md / AGENTS.md     # 项目说明（phantom 跑完后生成）
```

## 前置要求

使用 phantom 前，请确保以下依赖已安装并可用：

### 必须

| 依赖 | 用途 | 安装方式 |
|---|---|---|
| **Claude Code CLI** 或 **OpenAI Codex CLI** | AI 后端（至少装一个，**强烈建议两个都装**以启用跨模型评审） | `npm install -g @anthropic-ai/claude-code` / `npm install -g @openai/codex` |
| **git** | 代码版本管理 | macOS 自带；Linux: `sudo apt install git` |
| **jq** | JSON 状态管理 | `brew install jq`（macOS）/ `sudo apt install jq`（Linux） |
| **python3** | 流式输出解析 + 端口分配 | macOS 自带；Linux: `sudo apt install python3` |
| **docker** | deploy 阶段构建和运行容器 | [Docker Desktop](https://www.docker.com/products/docker-desktop/)（macOS/Windows）/ `sudo apt install docker.io`（Linux） |
| **curl** | deploy 阶段 smoke 测试 | 大多数系统自带 |

### 可选（按项目需求）

| 依赖 | 用途 | 说明 |
|---|---|---|
| **postgres MCP** | 数据库操作 | 需要 PostgreSQL 的项目会用到，需本地安装 PostgreSQL 或配置远程连接 |
| **Playwright MCP** | E2E 浏览器测试 | 有前端的项目 test phase 会用到 |

### 环境变量（按项目需求配置）

在 `~/.zshrc` 或 `~/.bashrc` 中配置以下环境变量，phantom 生成的项目会自动使用：

```bash
# 数据库（如果项目用 PostgreSQL）
export DATABASE_URL="postgresql://user:password@localhost:5432/mydb"

# AI API（如果项目需要调用大模型）
export OPENAI_API_KEY="sk-..."

# 搜索与爬虫（如果项目需要这些能力）
export BRAVE_API_KEY="..."       # Brave Search API
export TAVILY_API_KEY="tvly-..." # Tavily Search API
export FIRECRAWL_API_KEY="..."   # Firecrawl 网页抓取 API
```

> 这些环境变量不是运行 phantom 本身所必需的，而是**生成的项目**可能会用到。phantom 会在 plan 阶段根据需求自动决定使用哪些。

## 理念

**"Find the simplest solution possible, and only increase complexity when needed"**——当模型变得更强时，group-per-sprint 可以退化到单次 pass，plan 的 R2 协商可以删掉，跨模型强制可以放宽。当前的脚手架是为了模型限制服务的，不是永久建筑。
