# AI 榨汁机 🧃

AI 端到端软件交付流水线调度平台——把一个"产品想法"榨成 **6 种汁**（Finder → Requirement → Plan → Design → DevTest → Deploy）。

6-step 固定流水线：AI Finder → AI Requirement → AI Plan → AI Design → AI DevTest → AI Deploy。支持长期运行、状态持久化、人工介入、失败自动重试。

设计文档：`docs/superpowers/specs/2026-04-20-aiclusterschedule-design.md`

## 里程碑

- **M1** ✅ 后端骨架（状态机 + 核心 API + 结构化日志 + 审批流程）
- **M2** ✅ Agent Python SDK + Redis Streams 任务队列
- **M3** ✅ 可恢复性（启动恢复 + 心跳超时监控 + SDK 自动心跳）
- **M4** ✅ `aijuicer` CLI（submit / list / show / approve / rerun / skip / abort / logs / agents）
- **M5** ✅ Web UI v1（Next.js + React Flow DAG + SSE 事件时间线 + 审批面板）
- **M6** ✅ 产物预览（markdown / text / json / 图片 / HTML / 下载）
- **M7** ✅ 6 个示例 agent 骨架 + `scripts/run_all.sh` 一键本机启动
- **M8** ✅ Prometheus `/metrics`（workflows / step_duration / retries / heartbeat_timeout 等）

## 架构一览

```
Web UI (Next.js :3000)
       │ HTTP + SSE
       ▼
Scheduler Core (FastAPI :8000)
       │               ├─ /health /metrics /api/...
       │               └─ SSE: /api/workflows/{id}/events
       ▼
   Postgres ────── Redis Streams (tasks:<step>)
                   │
                   ▼  XREADGROUP
             Agent SDK (Python)
             ai-finder / ai-requirement / ... / ai-deploy
```

## 依赖

- Python 3.12+（后端 + SDK + CLI）
- Node 20+ + pnpm（Web UI；本机实测 node 25）
- Postgres 14+（可远程）
- Redis 7+（本机即可）

## 本机一键启动

```bash
# 1. 配置
cp .env.example .env
# 编辑 .env 填 AIJUICER_DATABASE_URL / AIJUICER_REDIS_URL
# AIJUICER_ARTIFACT_ROOT=./var/aijuicer/artifacts

# 2. 安装
python3.12 -m venv .venv && source .venv/bin/activate
make install
cd webui && pnpm install && cd ..

# 3. DB 建表
make migrate

# 4. 一键起全栈
bash scripts/service.sh start
# scheduler :8000 + 6 个 agent + webui :3000
# Ctrl+C 统一清理
```

浏览器开 http://127.0.0.1:3000 → 创建 workflow → 看 6-step 流水线实时推进。

## 单独运行各组件

```bash
make run                         # scheduler :8000
python -m sdk.examples.ai_finder # 某一步的 agent（或 ai_requirement / ai_plan / ...）
cd webui && pnpm dev             # webui :3000
```

## CLI

```bash
aijuicer workflow submit --name demo --input '{"topic":"hi"}' \
  --policy '{"requirement":"auto","plan":"auto","design":"auto","devtest":"auto","deploy":"auto"}'
aijuicer workflow list
aijuicer workflow show <wf_id>
aijuicer workflow artifacts <wf_id>
aijuicer workflow approve <wf_id> --step requirement
aijuicer workflow rerun <wf_id> --step design --input @revised.json
aijuicer workflow skip <wf_id>
aijuicer workflow abort <wf_id>
aijuicer workflow logs <wf_id>      # SSE 订阅
aijuicer agents list
```

读环境变量 `AIJUICER_SERVER`（默认 `http://localhost:8000`）。

## 开发

```bash
make test    # 需 TEST_DATABASE_URL 环境变量
make lint    # ruff
make fmt     # ruff format + fix
make type    # mypy scheduler + sdk

cd webui && pnpm typecheck && pnpm build
```

测试：

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://USER:PASS@HOST:5432/DB
make test
# 76 passed
```

## 技术栈

- **后端**: Python 3.12 / FastAPI (asyncio) / SQLAlchemy 2.x async + asyncpg / Alembic / structlog (JSON + request_id 全链路) / sse-starlette / prometheus-client
- **SDK**: httpx + redis[asyncio]；`@agent.handler` 装饰器；原子 artifact 落盘 + 自动注册
- **CLI**: typer；`aijuicer` 入口；对每个 API 动作的薄封装
- **前端**: Next.js 14 App Router + TypeScript + Tailwind + React Flow 11 + react-markdown
- **依赖**: Postgres 14+ / Redis 7+（本机即可）；pytest + testcontainers
