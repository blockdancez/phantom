# CLAUDE.md

本文件给未来接手此仓库的 Claude Code（或任何 AI 助手）提供**完整上下文**。请先读完再改代码。

---

## 1. 项目概述

**AI Idea Finder** — FastAPI + Next.js 的全栈应用。目标是从多个产品/技术情报源自动采集最新动态，经 LLM 打分与摘要后，用 LangGraph Agent 产出结构化的消费级产品创意报告，供产品经理 / 独立开发者 / 投资研究员浏览。

**用户**：产品经理、独立开发者、投资研究员。
**核心流程**：`多源采集 → 入库去重 → LLM 处理打分 → Agent 生成创意 → 前端展示`。
**数据库**：PostgreSQL（每项目独立 DB：`ai_idea_finder`）。

---

## 2. 技术栈与目录结构

### 技术栈
- **后端**：Python 3.12、FastAPI、SQLAlchemy 2.0 async、asyncpg、Alembic、APScheduler、structlog、LangGraph、langchain-openai、httpx、trafilatura、feedparser、BeautifulSoup、Playwright（Twitter trends）
- **前端**：Next.js 16（App Router，**webpack 模式**，非 Turbopack）、React 19、TypeScript 5、Tailwind CSS 4、shadcn/ui、`@base-ui/react`
- **测试**：pytest（`asyncio_mode=auto`）、Playwright（E2E，位于 `tests/e2e/`）

### 目录结构
```
AIIdea/
├── backend/
│   ├── src/
│   │   ├── api/              # 接入层：health / source_items / analysis_results / stats / pipeline / router
│   │   ├── collectors/       # base / hackernews / reddit / producthunt / github_trending /
│   │   │                     # twitter_trends / rss_collector / generic_html / generic_json /
│   │   │                     # sources_registry / ingester
│   │   ├── processors/       # pipeline / enricher / analyzer（已替代旧 classifier+scorer）
│   │   ├── agent/            # graph（LangGraph ReAct）/ prompts / state / extractor / tools/*
│   │   ├── scheduler/        # jobs（APScheduler 三大 cron）/ runs（执行历史内存队列）
│   │   ├── models/           # SourceItem / AnalysisResult（SQLAlchemy ORM）
│   │   ├── schemas/          # Pydantic 入/出参模型
│   │   ├── config.py         # pydantic-settings（.env 读取 + 把 LLM key mirror 进 os.environ）
│   │   ├── db.py             # async engine / session factory / asyncpg URL 改写
│   │   ├── envelope.py       # 统一响应 `{code,message,data,request_id}` 中间件 + 异常处理器
│   │   ├── exceptions.py     # ErrorCode 枚举 + APIError
│   │   ├── middleware.py     # RequestIdMiddleware（body 日志 + 1KB 截断）
│   │   ├── logging_setup.py  # structlog JSON + service_name=ai-idea-finder-api
│   │   └── main.py           # FastAPI app、CORS loopback regex、lifespan（起 scheduler）
│   ├── alembic/              # 迁移（initial_tables + 5 个增量迁移）
│   ├── tests/                # 与 src 结构镜像
│   ├── scripts/              # probe_sources / audit_existing_reports / backfill_analysis_reports
│   ├── pyproject.toml        # 依赖（Python≥3.12）
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/              # App Router：`/` dashboard / `/sources` / `/sources/[id]` /
│   │   │                     # `/analysis` / `/analysis/[id]`；各路由带 not-found.tsx
│   │   ├── components/       # header / sidebar / trigger-button / analysis-card / analysis-filter-bar /
│   │   │                     # sources-filter-bar / source-item-card / copy-button / pagination /
│   │   │                     # score-indicator / tag-badge / test-harness(window.__TEST__) / ui/*
│   │   ├── lib/              # api.ts（ApiError + fetch 封装）/ types.ts / utils.ts
│   │   └── .env.local        # NEXT_PUBLIC_API_URL=http://localhost:53839
│   └── package.json          # Next 16 + React 19，**dev/build 都用 --webpack**
├── scripts/                  # start-backend.sh / start-frontend.sh（一键起）
├── tests/e2e/                # Playwright E2E
├── docker-compose.yml        # backend + frontend；**不含 Postgres**，走 host.docker.internal
├── playwright.config.js      # baseURL 从 .phantom/port 读
├── .env.example / .env
└── .phantom/                 # phantom AutoDev 的规划 / 日志 / 迭代记录（详见第 7 节）
```

---

## 3. 关键文件职责

### 后端热点
- `backend/src/main.py` — 应用入口。启动时 (a) 调 `setup_logging`；(b) 把 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 从 Settings mirror 进 `os.environ`（langchain 客户端只认 env，**不要删这段**）；(c) 缺 `OPENAI_API_KEY` 直接 raise RuntimeError（可用 `AI_IDEA_FINDER_SKIP_KEY_CHECK=1` 绕过，仅测试用）；(d) 注册中间件（Envelope + RequestId）+ 全局异常处理器；(e) CORS 走 `allow_origin_regex=^http://(localhost|127\.0\.0\.1)(:\d+)?$` 接纳任意本地端口，**严禁硬编码 3000**；(f) lifespan 启 APScheduler，启动失败直接 raise 不降级。
- `backend/src/db.py` — `_coerce_async_url` 把 `postgresql://` 透明改写为 `postgresql+asyncpg://`（Alembic env.py 同步使用）。
- `backend/src/envelope.py` + `backend/src/exceptions.py` — 统一响应 `{code,message,data,request_id}`；`ErrorCode`（SRC001/SRC002/ANA001/ANA002/PIPELINE001..003/STATS001/HEALTH001/400000/503000/000000/999999）集中维护，**新增错误码先查已有**。
- `backend/src/middleware.py` — `RequestIdMiddleware` 读 `X-Request-ID` header（缺失生成 UUID），注入 `request.state.request_id`，回传响应 header 与 body 的 `request_id` 字段；记 `request_started` / `request_completed` INFO 日志带 body，>1KB 截断。
- `backend/src/logging_setup.py` — structlog JSON 输出，每条日志带 `timestamp / level / message / request_id / service_name=ai-idea-finder-api`。**严禁 `print`**。
- `backend/src/scheduler/jobs.py` — 三类 cron：`collect_data`（`COLLECT_INTERVAL_MINUTES`，默认 60m）、`process_data`（`PROCESS_INTERVAL_MINUTES`，30m）、`analyze_data`（`ANALYSIS_INTERVAL_MINUTES`，120m）。**每类都在启动时 `next_run_time=now` 立即跑一次**，保证首次启动 DB 不空。
- `backend/src/scheduler/runs.py` — 线程安全 deque（MAX=20），记录每类 job 的 `last_run_at / last_status / last_duration_ms / last_error`，供 `/api/stats/pipeline` 读。
- `backend/src/api/pipeline.py` — `POST /api/pipeline/trigger/{job_id}`。支持三类 job id：
  1. 调度任务：`collect_data` / `process_data` / `analyze_data` → `modify(next_run_time=now)`；
  2. per-source 采集：`collect_{hackernews|reddit|producthunt|github_trending|twitter|rss}` → inline 调对应 collector + `_collect_with_backoff`（指数退避 1s→2s→4s，3 次，覆盖 429 / 5xx / timeout / transport error）；
  3. inline：`process` / `analyze` → 同步跑。
  用 `_RUNNING_KEY_ALIASES = {"process":"process_data","analyze":"analyze_data"}` 归一化 key，inline 和 scheduled 共享同一把 `_scheduled_lock` + `_running_scheduled` 锁（集合型，in-process 级别）。并发返 400 `PIPELINE002`，未知 job 返 404 `PIPELINE001`，scheduler 未起返 503 `PIPELINE003`。
- `backend/src/collectors/sources_registry.py` — 配置驱动的源注册表。`SourceConfig.kind ∈ {rss, html, json}`。**新增 RSS/HTML/JSON 源 = 在 `SOURCES` 追加一行**，不要新写 collector 类。专用 collector（`hackernews / reddit / producthunt / github_trending / twitter_trends`）硬编码在 `build_collectors()`。
- `backend/src/collectors/ingester.py` — `ingest_items` 按 `url` 唯一去重入库（`ON CONFLICT DO NOTHING`）。
- `backend/src/processors/pipeline.py` — 默认 `batch_size=50`，取未处理的 `SourceItem` 逐条过 `Enricher → Analyzer`。Enricher 用 trafilatura 拉原文，**只在比原 content 长时才覆写**；Analyzer 一次 structured-output LLM 调用（ChatOpenAI + Pydantic `ItemAnalysis`）生成 `category / tags / summary_zh / problem / opportunity / target_user / why_now / score`。LLM 失败 → 保留 `processed=False` 不阻塞批次；`pydantic.ValidationError`（非法 category）→ 写入 `category="unknown" / tags=["unknown"] / score=0.0 / processed=True`。
- `backend/src/agent/graph.py` — LangGraph ReAct 循环（gpt-4o），工具在 `agent/tools/`：`search_items / synthesize_trends / generate_ideas / critique_idea / analyze_market / assess_tech_feasibility`。中文 `SYSTEM_PROMPT`（见 `agent/prompts.py`）强制工作流：search → synthesize → generate → **critique（必做）** → 不合格则换 anchor item 最多重试 3 次。
- `backend/src/scheduler/jobs.py:_run_analysis_impl` — agent 返回后用 `agent/extractor.py` 解析 markdown 成 `AgentReport`，应用三重 guard：(1) 报告 <80 字 skip；(2) 含 bail markers（`NO_VIABLE_IDEA_FOUND` / `NO_CONSUMER_ANCHOR_FOUND` / `调整搜索策略` / `建议调整搜索`）skip；(3) 缺 `source_quote` 且缺 `user_story` → 判定为 agent 短路 skip；(4) `idea_title` 空或 `overall_score` 无法转 float → log error 后 skip。**这些 guard 是防"假大空"的，删除会污染库**。
- `backend/src/api/source_items.py` — 列表支持 `page / per_page`（`page_size` 作 legacy alias 仍接受，但响应体只含 `per_page`）、`source / category / collected_since / collected_until`（ISO-8601）、`sort / order` 参数。详情路径 UUID 非法 → 400 `SRC002`、不存在 → 404 `SRC001`。回填 `analysis_result_id` 字段供前端"查看分析"联动。
- `backend/src/api/analysis_results.py` — 列表按 `overall_score` 默认倒排，支持 `min_score`（0-100 校验）、`order=asc|desc`。详情 UUID 非法 → 400 `ANA002`、不存在 → 404 `ANA001`。`agent_trace` 为 `dict | None`，旧数据为 null 不 500。
- `backend/src/api/stats.py` — `/api/stats/sources`（每源总量 / 最近 24h 新增 / 平均分）、`/api/stats/pipeline`（每类 job 最近执行 + `scheduler_alive` bool）。用 `_db_guard` 把 `OperationalError / DBAPIError / SQLAlchemyError / ConnectionError` 转成 503 `STATS001`。

### 前端热点
- `frontend/src/app/layout.tsx` — 挂 `<TestHarness>` 暴露 `window.__TEST__ = {ready, route, user, store}` 供 E2E 断言。
- `frontend/src/lib/api.ts` — `DEFAULT_API_URL = "http://localhost:53839"`（字面量，**非环境变量**，合并 phantom 的端口约定）；`ApiError` 类透传后端 `code / message / requestId`。
- `frontend/src/app/page.tsx` — dashboard：顶部 `HealthBadge`（服务 / DB / Scheduler 三个子指标，失败独立降级不污染 stats）、6 张源统计卡、最新 5 条分析结果、顶栏手动触发按钮。
- `frontend/src/app/sources/page.tsx` — filter 条：`source / category / collected_since / collected_until`（日期范围）+ 分页；`category` 下拉通过 `per_page=200` 采样得出。
- `frontend/src/app/sources/[id]/page.tsx` — 详情页带"复制 URL"按钮（用 `CopyButton` 组件）、"查看原网站"、"查看分析"按钮（仅当 `analysis_result_id` 存在时渲染）。详情抓取失败仅 `SRC001/SRC002` 跳中文 not-found，其他错误抛给全局 error-boundary。
- `frontend/src/app/analysis/page.tsx` — `<AnalysisFilterBar>` 的 min_score 下拉（≥30/50/60/70/80/90）+ 升/降序切换，参数走 URL query，改动后 `router.push` 重置 `page=1`。
- `frontend/src/app/analysis/[id]/page.tsx` — 完整字段分区 + `agent_trace` 折叠面板（null → "此分析无推理轨迹"；JSON 串化异常 → "轨迹数据损坏"）。
- `frontend/AGENTS.md` — **必读**。Next.js 16 + React 19 不在你的训练数据里，写代码前要读 `node_modules/next/dist/docs/`。

### data-testid 规范
所有可交互元素带 `data-testid`，命名 `<feature>-<element>-<action>`，例如：`dashboard-trigger-collect_data`、`sources-list-empty`、`sources-detail-copy-url`、`source-detail-view-analysis`、`analysis-detail-trace-missing`、`analysis-not-found`、`dashboard-health-status`（带 `data-status="ok"|"fail"`）。

---

## 4. 如何运行 / 测试 / 部署

### 端口（phantom 预分配，字面量落在代码/配置里）
- 后端：`53839`（`.phantom/port.backend`）
- 前端：`53840`（`.phantom/port.frontend`）
- `.phantom/port`（= 前端端口）供 Playwright baseURL 读。

### 本地启动（推荐，非 Docker）
```bash
# 前置：本机 Postgres 已启，DB `ai_idea_finder` 已建（密码默认 1234）
# 1) 复制环境文件
cp .env.example .env        # 填 OPENAI_API_KEY；DATABASE_URL 本地保持 localhost
# 2) 后端（读 PORT / BACKEND_PORT / .phantom/port.backend，缺省 53839；自动跑 alembic upgrade head）
./scripts/service.sh start backend
# 3) 前端（读 FRONTEND_PORT / .phantom/port.frontend，缺省 53840；会自动 install）
./scripts/service.sh start frontend
```

### Docker（**注意 Postgres 不在 compose 里**）
```bash
docker compose up --build   # backend 默认 :8000、frontend :3000（可用 BACKEND_PORT / FRONTEND_PORT 覆盖）
```
Backend 容器通过 `host.docker.internal:5432` 连你**本机**的 Postgres。docker 场景下 `.env` 里的 `DATABASE_URL` 改为 `host.docker.internal`。

### 环境变量
| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | `postgresql://...` 或 `postgresql+asyncpg://...`，`db.py` 会自动改写 |
| `OPENAI_API_KEY` | **必填**（处理 + 分析管线都依赖）。缺失启动即 raise |
| `ANTHROPIC_API_KEY` | 可选 |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reddit 采集器 |
| `PRODUCTHUNT_API_TOKEN` | Product Hunt 采集器 |
| `COLLECT_INTERVAL_MINUTES` / `PROCESS_INTERVAL_MINUTES` / `ANALYSIS_INTERVAL_MINUTES` | cron 周期 |
| `LOG_LEVEL` | 默认 `INFO` |
| `AI_IDEA_FINDER_SKIP_KEY_CHECK` | `=1` 跳过启动 key 检查（仅测试/lint 用） |
| `CORS_EXTRA_ORIGINS` | 逗号分隔额外白名单 origin |
| `PORT` / `BACKEND_PORT` / `FRONTEND_PORT` | 启动脚本读 |
| `NEXT_PUBLIC_API_URL` / `API_URL` | 前端 server vs client 的 backend 指向 |

### 测试
```bash
# 后端（当前 143 条 pytest，通过 143/143；核心模块覆盖率 85~100%）
cd backend && pip install -e ".[dev]" && pytest                      # 全量
pytest tests/test_api/test_source_items.py::test_name -v              # 单条

# 前端 lint / typecheck
cd frontend && npm run lint
cd frontend && npx tsc --noEmit

# E2E（需前端在跑）
npx playwright test                                                   # 根目录
```

静态检查：`ruff check src/ tests/` + `mypy --ignore-missing-imports`（覆盖 16 个核心文件），都应当是 0 error。

### 手动触发管道
```bash
curl -X POST http://localhost:53839/api/pipeline/trigger/collect_data
curl -X POST http://localhost:53839/api/pipeline/trigger/collect_hackernews   # per-source
curl -X POST http://localhost:53839/api/pipeline/trigger/process              # inline 处理
curl -X POST http://localhost:53839/api/pipeline/trigger/analyze              # inline 分析（最长 180s）
```

### 运维脚本（`backend/scripts/`）
- `probe_sources.py` — dry-run 整个 `sources_registry.py`，生成 `sources_probe_report.md` 看每个源是否活着。
- `audit_existing_reports.py` / `backfill_analysis_reports.py` — 一次性修旧 `AnalysisResult` 的工具，**用前读文件开头**。

---

## 5. 开发规范（硬红线）

### 后端
- **分层**：`api/` 只做参数绑定 + 调服务层；业务在 `processors/` / `agent/` / `collectors/`；`models/` 只放 ORM；`schemas/` 只放 Pydantic。
- **统一响应**：所有 `/api/*` 走 `{code, message, data, request_id}`。成功 `code="000000"`；未处理异常 `code="999999"` + HTTP 500。业务错误用既有 `ErrorCode`，**新增前先查已有**。错误码结构 `<模块 3 位字母>+<3 位数字>`（plan）或 6 位数字（envelope 兼容，如 `400000 / 503000`）。
- **HTTP 状态码**：404（未找到）、400（参数非法）、503（DB / scheduler / 第三方不可达）、500（未处理异常）。业务错误原则上仍返 200 + 非零 code，本项目为贴合 plan 的错误矩阵对 404/503 直接用对应 HTTP 状态。
- **请求拦截**：所有请求都经 `RequestIdMiddleware` 记 `request_started` + `request_completed`，body >1KB 截断。
- **日志**：**严禁 `print`**，只能 `structlog.get_logger()`。每条日志必须带 `request_id`。
- **命名**：Python snake_case、TypeScript camelCase、组件 PascalCase；禁用缩写（通用词除外）。
- **禁用项**：`TODO` / `FIXME` 留在代码里；硬编码端口（含 `3000`）；空函数体（只 `pass` 不带 docstring）；测试外 mock 冒充真数据。
- **端口约定**（phantom AutoDev 规则）：首次实现时端口直接写字面量（`53839` / `53840`），不要从环境变量动态读。环境变量作**覆盖**用（脚本层），不是主路径。

### 前端
- **严禁 `console.log`**。
- 所有可交互元素必须带 `data-testid`。
- Next.js 16 + React 19 不在训练数据里，改前读 `frontend/node_modules/next/dist/docs/`。
- 所有页面必须有空态 / 加载态 / 错误态。
- 错误分流：404-类错误走 `notFound()` 渲染中文兜底页；5xx 抛给全局 error-boundary。

---

## 6. 未达标 feature（全部强制推进，产物可能不达标）

**背景**：以下 10 个 feature 全部在 phantom AutoDev 的 dev 循环里**达到 max_rounds 被强制推进**，code-review 多轮以空 issues 列表 fail（见 `.phantom/changelog.md` 多次记载），自测数据看着好看但**未有后续 test phase 的评分报告覆盖**，当前唯一一份运行态测试是 `.phantom/test-report-iter1.md`，**总分 22/100**（那是迭代 1 的结果，iter2 之后的实质修复没有被重新打分）。

- `feature-1-multi-source-collectors` — iter1 暴露 Product Hunt 403 / Twitter Playwright 浏览器未装 / `api.launch.cab` RSS 404；iter4 已加指数退避，但**真实源可用率从未被重新跑全过**。
- `feature-2-scheduling-and-triggers` — iter2 后契约齐了，但运行锁是 in-process `set[str]`，**多 worker 部署时会失效**，plan 没再要求。
- `feature-3-item-processing-pipeline` — iter9 修掉了 analyzer 吞异常、ValidationError 落 `unknown`，但**前端 `/trigger/process` 触发按钮**暂没单独接入（走的 `process_data` 调度别名）。
- `feature-4-ai-idea-analysis` — 三重 guard 生效，但 **agent timeout/exception 会写一条 `overall_score=0` 的占位行**到 `analysis_results`，plan 没明确要求是否该从列表过滤掉，当前未过滤。
- `feature-5-source-items-api` — iter14 起把字段 `page_size` 迁到 `per_page`，但**保留了 `page_size` 作 legacy query alias**。
- `feature-6-analysis-results-api` — iter14 把 `agent_trace` 改为 `dict | None`；列表/详情已齐。
- `feature-7-stats-and-health` — iter15 起 DB 不可达返 503 `STATS001`；`recent_24h` 用的 `make_interval` 是 Postgres-only 语法，非 Postgres 测试环境下回落 0，生产正常。
- `feature-8-dashboard` — iter20 起有 `HealthBadge` 三指标显示，但 iter1 的"立即采集" CORS/fetch 失败已在 iter2 修复（改 53839 + loopback regex），**无再次端到端验证**。
- `feature-9-sources-browser` — iter21 修了 filter 条（source / category / 日期范围）+ "查看分析"联动 + 复制 URL；但 category 下拉靠采样 `per_page=200` 的数据抽取，数据稀疏时选项少。
- `feature-10-analysis-browser` — iter20/21 落了 `min_score` + `order` + agent_trace 腐坏分支；前端无独立单测框架（Vitest/Jest 都没装），只靠 tsc + eslint + 下游 Playwright。

**其他已知遗留**（贯穿多轮 changelog）：
- `backend/tests/test_collectors/test_ingester.py` 有 pre-existing `RuntimeWarning: coroutine _execute_mock_call was never awaited`（AsyncMock 用法问题，不在任何 feature scope 里）。
- Twitter collector 的 Playwright Chromium 需要 deploy phase 手动 `playwright install chromium`，dev 脚本里没自动装（避免首次启动多分钟延迟）。
- 根目录 `README.md` **不存在**（iter1 test report 因此扣分，后续 dev 轮次也没补）。

---

## 7. 项目历史与 AI 记忆（给未来 AI 助手）

**你（未来的 AI 助手）改本仓库前应当知道：**

- 本项目由 **phantom AutoDev** 生成（一个多轮 dev+review+test 自动化开发框架）。现在的代码不是人类从零写的，是多轮 AI 迭代的产物，风格、结构、注释密度都带有它的印记。
- **`.phantom/plan.locked.md` 是原始完整规划**（本轮 2026-04-23 从 v1 项目迁移而来；v1 的 plan 在 `.phantom/legacy/plan.v1.md`）。数据模型、feature 列表、API 契约、评分标准都以它为准。**改代码前先读 plan.locked.md**，不然会把 plan 约定好的字段名 / 错误码 / 空态行为改掉。
- **`.phantom/changelog.md` 是每轮 dev 的追加记录**。每次 iteration 以 `## Iteration N — group-X / feature-...` 开头，包含"做了什么 / 自测结果 / 已知遗留"三段。想知道某个字段/行为为什么这么设计，翻 changelog 的对应 iteration 比翻 git blame 快得多。
- **`.phantom/test-report-iter*.md` 是每轮 test phase 的评分报告**。当前只有 `test-report-iter1.md` 一份（22/100），iter2 之后的代码修复没再跑 test phase，分数没更新——**不要被单测 100% 通过和 92% 覆盖率骗了**，运行态的端到端验证是缺失的。
- **`.phantom/port` 是本项目预分配端口**（= 前端口 `53840`）；`.phantom/port.backend` = `53839`、`.phantom/port.frontend` = `53840`。端口作为字面量写入代码（`frontend/src/lib/api.ts:DEFAULT_API_URL = "http://localhost:53839"`、启动脚本的 fallback、`.env.local`），不是纯环境变量读取——**这是 phantom 的端口约定，不要改成"只靠 env 读"**。
- **`.phantom/state.json` / `.phantom/return-packet.md` / `.phantom/logs/`** 是 phantom 本身的运行状态，不是你需要关心的；但如果碰到奇怪的"为什么代码里有这个分支但没测试"，可以去 `logs/` 翻翻当时的 reviewer / dev 对话记录。
- **`.phantom/legacy/`** 装的是迁移前 v1 项目的归档，不要在 v2 代码里引用。
- 本仓库 git 里 `main` 分支只有 3 次 commit（`init` / `feat: complete AI Idea Finder — backend + frontend Tasks 1-18` / `chore: stop tracking .phantom`），**所有真实开发历史在 `.phantom/changelog.md` 而不在 `git log` 里**。

**对你的建议**：
1. 用户问"这个字段为什么叫 X"时，先看 plan.locked.md 的数据模型表，再看 changelog 里对应 iteration。
2. 改 API 契约前，搜 changelog 里有没有 iteration 专门讨论过那个端点——iter14（per_page 迁移）、iter15（stats 503 + service_name）、iter21（analysis_result_id 回填 + sources filter 重写）是几个关键节点。
3. 不要删掉看似多余的 guard（三重 agent guard、`_coerce_async_url`、envelope 的 `BaseHTTPMiddleware.dispatch` 兜底 `except`、`_RUNNING_KEY_ALIASES`），它们都是历次 review 补上的，删了就回归。
4. 新增源优先走 `sources_registry.py`，不要新写 collector 类。
5. 测试 pytest 全绿 ≠ 功能在浏览器里能跑——前端无独立单测框架，改前端必须手动跑 `./scripts/service.sh start frontend` 打开浏览器验证。
