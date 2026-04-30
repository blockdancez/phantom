# Phantom AutoDev

全自主需求开发程序 — 输入需求，自动完成从规划到部署的全流程。支持 Claude Code 和 OpenAI Codex 两种 AI 后端，**默认强制跨模型**（generator 写代码，evaluator 跨模型审查）。

三个**可独立重入的模式**（plan / design / dev-test）+ 一个单节点（test）覆盖全生命周期。已经开发完的项目可以随时回头追加需求，比如 `phantom "请加一个搜索功能"` 会自动走 plan 增量、保留已有 feature 编号，把新需求拼接到下游 dev-test。

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

# ── 三模式 + 单节点（在已有 .phantom/ 的项目目录下跑） ──

# 增量需求主入口：有 state.json + 字符串需求 → 默认走 --plan 增量
phantom "请添加列表搜索功能"

# 显式 plan 增量
phantom --plan "把 rubric 权重调一下"

# 纯重规划（无参数，shell 注入 synthetic refresh amendment 保留结构）
phantom --plan

# 只跑 design 模式（design → design-review → design）
phantom --design "UI 改成暖白色调"

# 只跑 dev → code-review → deploy → test 一圈（不强制打磨）
phantom --dev-test "feature-3 搜索按钮点了没反应"

# 只重跑 test 一次（不回流 dev，需要 deploy 产物在线）
phantom --test
phantom --test "重点测登录失败场景"

# ── 恢复 / 删除 ──
phantom --resume                 # 交互选
phantom --resume todo-app

phantom --delete                 # 交互选
```

**已弃用**（保留兼容 + warn）：`--plan-only` / `--ui-only` / `--skip-plan` / `--test-only` 分别映射到新的 `--plan` / `--design` / `--dev-test` / `--dev-test + PHANTOM_TEST_ONLY=1`。

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

参考 [Anthropic Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) 的 harness 模式。三个独立可重入的**模式**，无 flag 串起来跑：

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

### plan 模式（`--plan`）

Planner 把需求展开成 `.phantom/plan.md`，包含 4 个核心章节（产品目标 / Feature 列表 / API 约定 / 评分标准）和若干推荐章节（技术栈 / 数据模型 / 非功能需求 / 编码标准 / 部署配置等）。**明确反 YAGNI，鼓励野心大**。

Feature 按功能相关性分组（`### group-N: name` + `#### feature-N-slug`），每组 2-4 个 feature，组间低耦合。

内部 3 轮：

1. **R1 plan**：planner 起草
2. **R2 plan-review**：跨模型 reviewer 审 feature 列表 + 非功能需求 + 前端页面结构 + rubric，**只提建议无否决权**
3. **R3 plan**：planner 根据 comments 修订，结束后冻结成 `.phantom/plan.locked.md`

**增量场景**（已有项目 + `--plan "<改动>"` 或裸 `phantom "<改动>"`）：shell 写入 `.phantom/amendment.md`，planner prompt 通过 `{{AMENDMENT}}` 占位符读取，按"保留已有 feature 编号、只追加 / 修改增量指向部分"的语义改写 plan.locked.md。

### design 模式（`--design`，仅前端）

Shell 扫 `plan.locked.md` 有前端关键字（`frontend/` / React / Vue / Svelte / TS 等）才触发。和 plan 对称，也是 R1→R2→R3：

1. **R1 design**：UI designer 通过 **Google Stitch MCP** 为每屏生成设计
   - `create_project` + `create_design_system`（独立色板 / 字体 / 圆角 / 间距）
   - 对每个前端 feature + 兜底页（空态/错误/404/登录等）调 `generate_screen_from_text`
   - 用 `get_screen` 把 HTML + JSON 落盘到 `.phantom/ui-design/<slug>.html` / `.json`
   - 写总览 `.phantom/ui-design.md`（screen ↔ feature 映射 + 关键 `data-testid` 清单）
2. **R2 design-review**：跨模型 reviewer 审 5 维（screen 覆盖完整性 / data-testid 完整 / 状态 completeness / 视觉一致性 / 语义可访问性），写 `.phantom/ui-design-review-comments.md`
3. **R3 design**：UI designer 同会话复用原 `project_id` / `design_system_id`，按 comments 改需要改的 screen

Dev 阶段读 `.phantom/ui-design/<slug>.html`，**严格保留 HTML 骨架 + 所有 `data-testid`**（下游 E2E 的锚点），class / 样式可适配项目 CSS 方案。

Stitch MCP 只挂在 claude user-scope，所以 designer 强制用 claude（通过 `PHANTOM_UI_DESIGNER_BACKEND` 可覆盖）；reviewer 跨模型自动选 codex。**幂等**（`ui-design.md` 存在则 skip）、**降级不阻塞**（R1 产出 0 screen 则跳过 R2/R3，dev 按通用规范自由发挥）。

**增量场景**：amendment.md 注入到 design prompt，复用 Stitch project_id/design_system_id 修改受影响的 screen，不重建。

### dev-test 模式（`--dev-test`）

按 plan 的 feature 分组**一组 feature** 跑完整循环 `dev → code-review → deploy → test`：

- **Dev**：Generator 在 compaction 长会话里一次实现整组 feature，写单元测试（核心覆盖率 100%），跑静态检查（ruff/eslint/tsc 等）**0 error**，自修复无限。**首次 dev 时分配端口**（`.phantom/port.{backend,frontend}`），AI 直接把端口**硬编码进代码 / 配置**，不走环境变量
- **Code-review**：跨模型 reviewer 审 diff（placeholder / mock / 日志规范 / API 契约 / 安全红线），**shell 侧 grep 兜底**（TODO / FIXME / console.log / 硬编码端口 / 硬编码凭据）
- **Deploy**：Generator 写 `scripts/start-backend.sh`（+ `start-frontend.sh` 如有），**脚本只 `exec` 启动命令**（端口在代码里），shell 用 `nohup` 本地启动 + 等端口 + curl smoke，2 次自试后失败回 dev。运行时日志在 `.phantom/runtime/`
- **Test**：跨模型 tester 用 Chrome DevTools MCP（默认）+ Playwright 脚本（回退）+ curl 跑所有端点所有场景，按 rubric 打分。**累积测试所有已完成 feature**（防回归），总分 **≥ 90** 过关

每 group `min_rounds=2`（强制打磨轮），`max_rounds=6`：

- 达 max_rounds：strict 模式 exit 1，默认模式 `forced_feature` 标记继续
- `--dev-test` 模式（`PHANTOM_NO_POLISH=1`）：跑通一圈就 break，不打磨

**增量场景**（`--dev-test "<具体要修的事>"`）：shell 写 return-packet（`return_from: user-amendment`），跑**一次性 sprint**（不按 group 迭代、不推进 `current_group_index`），dev 第一 round 消化必修项。

### test 模式（`--test`）

只重跑 test 一次。前置：`.phantom/runtime/backend.pid` 进程在线（即 deploy 产物已部署）。

`--test "<侧重点>"` 写入 `.phantom/test-extra-note.md`，tester 通过 `{{EXTRA_NOTE}}` 读取，作为本轮测试的额外侧重点（一次性，跑完清空）。

**失败不回流 dev**——只日志警示，让用户显式跑 `--dev-test "<要修的事>"` 修复。

### 收尾（无 flag 的全流程跑完后）

所有 group sprint 完成后生成 `CLAUDE.md`，然后 `cp` 成 `AGENTS.md`（字节级一致）。`--plan` / `--design` / `--dev-test` / `--test` 单独跑时不触发 docs 重生，避免每次微调都重写。

## 增量需求与模式重入

phantom 的所有"已有项目"操作都通过**模式 flag + 可选参数**统一表达。增量需求落到三种 handoff 文件：

| 模式 | 增量参数落位 | 由谁读取 | 何时清空 |
|---|---|---|---|
| `--plan [str\|file]` | `.phantom/amendment.md` | plan prompt 的 `{{AMENDMENT}}` 占位符 | plan 模式跑完 `clear_amendment` |
| `--design [str\|file]` | `.phantom/amendment.md` | ui-design prompt 的 `{{AMENDMENT}}` 占位符 | design 模式跑完 `clear_amendment` |
| `--dev-test "<str>"` | `.phantom/return-packet.md`（`return_from: user-amendment`） | dev prompt 的 `{{RETURN_PACKET}}` 占位符 | dev round 跑完归档到 `logs/` |
| `--test "<str>"` | `.phantom/test-extra-note.md` | tester prompt 的 `{{EXTRA_NOTE}}` 占位符 | test round 跑完 `rm` |

**默认路由**：

| 调用 | 无 `state.json` | 有 `state.json` |
|---|---|---|
| `phantom reqs.md`（文件） | 新项目全流程 | 拒绝（歧义：覆盖还是增量？） |
| `phantom "<增量>"`（字符串） | 新项目全流程 | **默认 `--plan "<增量>"`** |
| `phantom --plan` | 报错（要求需求） | 纯重规划（注入 synthetic refresh amendment 保留结构） |
| `phantom --design`/`--dev-test`/`--test` | 报错（无 plan） | 只跑该模式 |

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
| `ui_design_reviewer` | `PHANTOM_UI_DESIGN_REVIEWER_BACKEND` | **是**（自动选与 ui_designer 不同的后端） |
| `deploy` | `PHANTOM_DEPLOY_BACKEND` | 否 |
| `ui_designer` | `PHANTOM_UI_DESIGNER_BACKEND` | 强制 claude（Stitch MCP 挂在 claude user-scope） |

### Compaction 长会话

每个 role 维持一个跨 round、跨 group 的长会话（`claude -c` / `codex resume --last`），靠 CLI 原生 compaction 处理上下文膨胀。

### Return-packet 回流包

dev-test 循环任一站失败（code-review reject / deploy fail / test < 90）都写 `.phantom/return-packet.md` 退回 dev，含：
- 必修项（硬性清单）
- 建议项（软性清单）
- 全量报告路径
- `return_from` 字段标识来源（`code_review` / `deploy` / `test` / `user-amendment`）

Dev 下一轮开头必读，跑完归档到 `logs/return-packet-iter<N>.md`。`return_from: user-amendment` 表示是用户通过 `--dev-test "<str>"` 主动触发的修改，dev 视为**最高优先级必修项**。

### Shell 侧确定性判断

可机械化判断的事全部由 shell 做，不问 AI 主观判断：

- Plan 核心章节：关键字 grep（产品目标 / Feature 列表 / API 约定 / 评分标准）
- Changelog 是否新增 Iteration 条目：`grep -c`
- Code-review 兜底：`lib/code-review.sh` 跑 5 类 grep
- Deploy gate：启动脚本存在 + 进程 PID 存活 + 端口 60s 内可连 + curl 非 5xx
- Test 分数：从 `test-report-iter*.md` 提取"总分"

## 项目结构

```
phantom.sh                  # 主入口：参数解析 + MODE 路由 + 主循环（run_group_sprint）
install.sh                  # 安装脚本（双模式：本地 + 远程一键装）
lib/
  utils.sh                  # 日志函数、依赖检查、_compact_log_tag（防文件名过长）
  state.sh                  # state.json 读写 + handoff 文件常量 + amendment / return-packet 辅助
  loop.sh                   # 后端抽象 + 跨模型解析 + compaction 调用 + render_prompt
  phases.sh                 # 7 个 phase 函数 + feature 分组解析
  code-review.sh            # Shell 侧兜底 grep
  stream-parser.py          # 流式 JSON 解析器
prompts/
  plan.md                   # Planner：产出含分组的 plan（含 {{AMENDMENT}} 增量段）
  plan-review.md            # Plan reviewer：跨模型审 4 章节
  ui-design.md              # UI designer：用 Stitch MCP 生成前端设计（含 {{AMENDMENT}}）
  ui-design-review.md       # UI design reviewer：跨模型审 5 维 rubric
  develop.md                # Generator：实现一组 feature + 单测 + 静态检查
  code-review.md            # Code reviewer：跨模型审 diff
  deploy.md                 # Deploy：写 scripts/start-*.sh 启动脚本
  test.md                   # Tester：Chrome DevTools MCP / Playwright + 接口 + 评分
```

### 运行时生成（项目目录下）

```
<project>/
  .phantom/
    state.json                       # 6 phase + current_group_index + forced_features
    plan.md                          # plan 模式 R1/R3 工作稿
    plan.locked.md                   # plan 模式冻结版（主循环 / dev 读这个）
    plan-review-comments.md          # plan 模式 R2 产物
    ui-design.md                     # design 模式 R1/R3 总览（仅前端项目）
    ui-design/                       # 每屏的 HTML + JSON（仅前端项目）
      <slug>.html                    # dev 阶段严格还原 HTML 结构和 data-testid
      <slug>.json                    # Stitch 原始返回，审计用
    ui-design-review-comments.md     # design 模式 R2 产物
    amendment.md                     # --plan / --design "<str>" 注入的增量需求（一次性）
    test-extra-note.md               # --test "<str>" 注入的测试侧重点（一次性）
    changelog.md                     # dev 每轮追加
    return-packet.md                 # 当前回流包；return_from 含 user-amendment 表示用户主动改动
    last-code-review.json            # 最近一次 code-review 的 JSON verdict
    test-report-iter<N>.md           # 每轮 test 报告
    port.backend                     # 后端端口（首次 dev phase 分配；AI 直接写死进代码）
    port.frontend                    # 前端端口（同上）
    runtime/
      backend.pid                    # 运行中后端 PID（deploy 后常驻）
      backend.log                    # 后端运行时日志（stdout+stderr）
      frontend.pid                   # 运行中前端 PID
      frontend.log                   # 前端运行时日志
    sessions/                        # 每 role+backend 的会话标记（compaction）
    logs/                            # 每 phase 每 round 的原始输出 + 归档的 return-packet
  backend/                           # 后端代码（Python 默认）
  frontend/                          # 前端代码（React 默认，纯后端项目无此目录）
  scripts/
    start-backend.sh                 # deploy phase 写的启动脚本（端口在代码里硬编码）
    start-frontend.sh                # （有前端时）
  CLAUDE.md / AGENTS.md              # 项目说明（无 flag 全流程跑完后生成）
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
| **curl** | deploy 阶段 smoke 测试 | 大多数系统自带 |

### 可选（按项目需求）

| 依赖 | 用途 | 说明 |
|---|---|---|
| **postgres MCP** | 数据库操作 | 需要 PostgreSQL 的项目会用到，需本地安装 PostgreSQL 或配置远程连接 |
| **Playwright MCP** | E2E 浏览器测试 | 有前端的项目 test phase 会用到 |
| **Stitch MCP** | UI 设计生成 | 有前端的项目 ui-design phase 会用到；按 [官方文档](https://stitch.withgoogle.com/docs/mcp/setup) 申请 API key 后 `claude mcp add stitch --transport http https://stitch.googleapis.com/mcp --header "X-Goog-Api-Key: <你的 key>" -s user` 挂到 claude user-scope |
| **Chrome DevTools MCP** | test phase 调试失败场景 | `claude mcp add ...` user-scope 挂载；仅调试用，不强制 |

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
