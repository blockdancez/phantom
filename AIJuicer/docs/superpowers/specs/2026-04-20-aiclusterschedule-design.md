# AIClusterSchedule — 设计规格

- **项目**: AIClusterSchedule
- **作者**: lapsdoor
- **日期**: 2026-04-20
- **状态**: Draft — 待用户 review

---

## 0. 项目定位

一个专为 **"AI 端到端软件交付流水线"** 设计的准生产级多 Agent 调度平台：

- **平台**: 管理 6-step 固定流水线（Finder → Requirement → Plan → Design → DevTest → Deploy），提供状态持久化、失败恢复、人工介入、Web UI
- **SDK**: 让开发者用装饰器风格快速写一个 agent 接入平台

### 0.1 目标用例

用户（即平台使用者）提交一个"产品构想主题"，平台自动驱动 6 个 AI agent 依次完成：发现产品 idea → 生成需求文档 → 生成计划 → UI 设计 → 代码开发与测试 → 打包部署。每一步可人工审批、修改、重跑。

### 0.2 非目标（第一版不做）

- **通用 DAG 引擎**: 流程固定为 6 步，不支持用户自定义任意 DAG
- **分布式部署 / K8s**: 第一版 Docker Compose 单机部署；K8s 作为预留扩展
- **认证授权**: 第一版无认证，仅本机使用；架构上预留 middleware 扩展点
- **多语言 SDK**: 第一版仅 Python SDK
- **对象存储**: 第一版产物用本地文件系统；接口层预留以便未来替换为 S3/MinIO

---

## 1. 关键决策总览

| # | 决策 | 选定 |
|---|------|------|
| 1 | 项目定位 | 准生产级系统 |
| 2 | Agent 类型 | 多 Agent 协作（专业化 agent 协同） |
| 3 | 协作模式 | 预定义工作流（DAG/流水线） |
| 4 | 执行特性 | 长期可恢复 + 人工介入 |
| 5 | Agent 接入 | Pull 模式（Worker 订阅） |
| 6 | 核心引擎 | 状态机 + 消息队列（非 Temporal，非通用 DAG） |
| 7 | 后端语言 | Python（FastAPI + asyncio） |
| 7 | SDK 语言 | Python（仅） |
| 8 | 产物存储 | 本地文件系统 |
| 9 | 人工介入 UI | 完整 Web UI |
| 10 | 前端栈 | Next.js + TypeScript + React Flow + shadcn/ui |
| 11 | 认证 | 第一版无认证（localhost） |
| 12 | SDK 风格 | 装饰器（`@agent.handler`） |
| 13 | 失败策略 | 心跳超时 + 异常分类 + 指数退避 + 人工兜底 |
| 14 | 实时推送 | SSE（Server-Sent Events） |
| 15 | 可观测性 | structlog JSON + request_id 全链路 + Prometheus |
| 16 | 部署 | Docker Compose（主），K8s 预留 |

---

## 2. 总体架构

```
┌────────────────────────────────────────────────────────────┐
│                      Web UI (Next.js)                      │
│    工作流列表 / DAG 图 / 产物预览 / 审批 / 实时日志        │
└────────────────────┬───────────────────────────────────────┘
                     │ HTTP + SSE
                     ▼
┌────────────────────────────────────────────────────────────┐
│                Scheduler Core (FastAPI + asyncio)          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │   API    │  │ Workflow │  │   Task   │  │  Event   │    │
│  │  Layer   │→ │  Engine  │→ │ Dispatch │  │   Bus    │    │
│  └──────────┘  └─────┬────┘  └──────────┘  └──────────┘    │
│                      │                                     │
└──────────────────────┼─────────────────────────────────────┘
         ┌─────────────┼─────────────┬──────────────┐
         ▼             ▼             ▼              ▼
   ┌─────────┐  ┌────────────┐  ┌────────┐  ┌─────────────┐
   │PostgreSQL│  │  Redis     │  │ 文件FS │  │  结构化日志 │
   │状态+元数据│  │Streams+Pub │  │ 产物   │  │(JSON+reqid)│
   └──────────┘  └─────┬──────┘  └────────┘  └─────────────┘
                       │ Pull
                       ▼
              ┌────────────────────┐
              │  Agent (Python SDK)│
              │  @agent.handler    │
              └────────────────────┘
```

### 2.1 核心组件

| 组件 | 技术 | 职责 |
|------|------|------|
| Web UI | Next.js + TypeScript + React Flow + shadcn/ui | 用户交互界面 |
| Scheduler Core | Python + FastAPI + asyncio | API、状态机、任务分发、审批、SSE 推送 |
| PostgreSQL | v15+ | 工作流/task 状态、审批记录、元数据 |
| Redis | v7+ Streams | 按 step 分 6 个 stream，Pull 任务队列 + ack |
| 文件系统 | `/var/lib/aijuicer/artifacts` | 工作流产物持久化 |
| Agent | Python SDK 装饰器 | 具体执行者，可跑任意位置（需能访问 scheduler HTTP + Redis） |
| CLI | Python 薄封装 | 脚本化操作 API |

---

## 3. 核心数据模型与状态机

### 3.1 固定的 6 步流水线状态机

```
[CREATED]
    │ submit
    ▼
[FINDER_RUNNING] ──fail(fatal or 超重试)─▶ [AWAITING_MANUAL_ACTION]
    │ succeed                                     │
    ▼                                             │ user: resume/skip/rerun/abort
[FINDER_DONE]                                     ▼
    │ policy=auto ──▶ 直接进入下一 RUNNING
    │ policy=manual ──▶
    ▼
[AWAITING_APPROVAL_REQUIREMENT] ──approve──▶ [REQUIREMENT_RUNNING] ──▶ ...
                                 ──reject ──▶ [ABORTED]

(finder → requirement → plan → design → devtest → deploy)
...
[DEPLOY_DONE] ──▶ [COMPLETED]

任何非终态 ──user abort──▶ [ABORTED]
```

**规则：**

- 每个 step 有三个主状态：`<STEP>_RUNNING` / `<STEP>_DONE` / `AWAITING_APPROVAL_<NEXT_STEP>`
- 失败进入 `AWAITING_MANUAL_ACTION`（携带 `failed_step` 字段）
- 审批策略由 workflow 的 `approval_policy` 字段配置，每步可独立设 `auto` 或 `manual`
- 终态：`COMPLETED` / `ABORTED`

**关键不变量：**

1. 每个 workflow 任意时刻只有 **≤ 1 个 running 的 step_execution**（串行流水线）
2. `task_id` 全局唯一且不重用（幂等基础）
3. 状态转换必须通过 `state_machine.py` 中的 `transition` 函数（单一修改点）
4. DB 事务未 commit 前不允许 `XADD` 到 Redis（at-least-once 保证）
5. 产物写入必须走 `.tmp → rename` 原子模式（不出现半写文件）

### 3.2 PostgreSQL 表结构

```sql
-- 工作流实例
CREATE TABLE workflows (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,              -- 状态机中的一个状态
    input JSONB NOT NULL,              -- 初始输入
    approval_policy JSONB NOT NULL,    -- {"finder":"auto","requirement":"manual",...}
    current_step TEXT,
    failed_step TEXT,
    artifact_root TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_workflows_status ON workflows(status);

-- 每步的执行记录（一 step 可能多 attempt）
CREATE TABLE step_executions (
    id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    step TEXT NOT NULL,
    attempt INT NOT NULL,
    status TEXT NOT NULL,              -- pending/running/succeeded/failed/timeout
    agent_id TEXT,
    input JSONB,
    output JSONB,
    error TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    heartbeat_message TEXT,
    request_id TEXT NOT NULL,          -- 贯穿全链路
    UNIQUE(workflow_id, step, attempt)
);
CREATE INDEX idx_step_executions_wf ON step_executions(workflow_id);
CREATE INDEX idx_step_executions_status ON step_executions(status, last_heartbeat_at);

-- 产物元数据（真实文件在 FS）
CREATE TABLE artifacts (
    id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    step TEXT NOT NULL,
    key TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    content_type TEXT,
    sha256 TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(workflow_id, step, key)
);

-- 审批 / 人工介入
CREATE TABLE approvals (
    id UUID PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    step TEXT NOT NULL,
    decision TEXT NOT NULL,            -- approve/reject/skip/rerun/abort
    comment TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Agent 注册
CREATE TABLE agents (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL,              -- online/offline
    last_seen_at TIMESTAMPTZ NOT NULL,
    metadata JSONB
);

-- 事件流水（审计 + Web UI 时间线）
CREATE TABLE workflow_events (
    id BIGSERIAL PRIMARY KEY,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_wf ON workflow_events(workflow_id, id);
```

### 3.3 Redis Streams

```
stream key           consumer group
tasks:finder         agents:finder
tasks:requirement    agents:requirement
tasks:plan           agents:plan
tasks:design         agents:design
tasks:devtest        agents:devtest
tasks:deploy         agents:deploy
```

**消息体：**

```json
{
  "task_id": "uuid",
  "workflow_id": "uuid",
  "step": "finder",
  "attempt": 1,
  "input": {},
  "artifact_root": "/var/lib/aijuicer/artifacts/workflows/<wf_id>/",
  "request_id": "req_...",
  "max_duration_sec": 600
}
```

**可靠性：** `XREADGROUP` + Pending Entries List + 心跳超时 `XAUTOCLAIM` 保证 "agent 挂了任务不丢"。

### 3.4 事务保证

状态转换 + 任务入队的顺序：

```python
async with db.transaction():
    update_workflow_status(wf_id, new_status)
    insert_step_execution(step, attempt)
    insert_event(event_type, payload)
    # ↑ DB 事务 commit 成功后才 XADD
await redis.xadd(f"tasks:{step}", task_payload)
```

**"DB 先 commit 再 XADD"** 保证：如 commit 后进程崩溃、XADD 没做，启动恢复器扫描 `step_executions.status='pending' AND not in redis stream` 补发。at-least-once + SDK 端 task_id 幂等 → effectively exactly-once。

### 3.5 产物文件系统布局

```
/var/lib/aijuicer/artifacts/
  workflows/
    <workflow_id>/
      01_finder/
        idea.md
      02_requirement/
        requirements.md
      03_plan/
        plan.md
      04_design/
        wireframe.png
        prototype.html
      05_devtest/
        repo/                # 可选 git init
      06_deploy/
        artifact.tar.gz
```

写入策略：`<path>.tmp → fsync → rename(<path>)` 保证原子。元数据写入 `artifacts` 表。

---

## 4. Scheduler Core 设计

### 4.1 模块划分

```
scheduler/
├── api/                        # FastAPI 路由层
│   ├── workflows.py
│   ├── tasks.py
│   ├── approvals.py
│   ├── agents.py
│   ├── artifacts.py
│   └── events.py               # SSE
├── engine/                     # 业务核心
│   ├── state_machine.py        # 状态机转换规则
│   ├── workflow_service.py
│   ├── task_service.py         # 含 Redis Streams 操作
│   ├── approval_service.py
│   └── recovery.py             # 启动恢复扫描
├── workers/                    # 后台协程
│   ├── heartbeat_monitor.py
│   ├── retry_scheduler.py      # 延迟任务（指数退避）
│   └── event_publisher.py      # Postgres LISTEN → SSE fan-out
├── storage/
│   ├── db.py
│   ├── redis.py
│   └── fs.py
├── observability/
│   ├── logging.py              # structlog 配置 + request_id
│   ├── metrics.py              # Prometheus
│   └── middleware.py
├── config.py                   # Pydantic Settings
└── main.py
```

**文件大小原则：** 每个模块单一职责，单文件 < 300 行；超出就拆子目录。

### 4.2 关键流程

**A) 提交 workflow：**

```
Client → POST /api/workflows {name, input, approval_policy}
Scheduler:
  1. 生成 request_id；INSERT workflows status=CREATED
  2. 状态机驱动: CREATED → FINDER_RUNNING
     - INSERT step_executions(step=finder, attempt=1, status=pending)
     - INSERT workflow_events
     - 事务 commit
  3. XADD tasks:finder <task_payload>
  4. 返回 workflow_id
```

**B) Agent 拉取并执行：**

```
Agent:
  XREADGROUP tasks:finder → 拿到 task
  PUT /api/tasks/<task_id>/start
    → UPDATE step_executions SET status=running
  [agent handler 执行；期间 SDK 自动 heartbeat；save_artifact 写文件+POST artifact 元数据]
  PUT /api/tasks/<task_id>/complete {output}
    → 事务:
        UPDATE step_executions SET status=succeeded, output, finished_at
        UPDATE workflows SET status=<下一态>
        INSERT workflow_events
        如下一步 policy=auto: XADD tasks:<next_step>
  XACK tasks:finder agents:finder <message_id>
```

**C) 审批推进：**

```
User → POST /api/workflows/<id>/approvals {step, decision}
Scheduler 事务:
  INSERT approvals
  UPDATE workflows SET status=<NEXT>_RUNNING
  INSERT step_executions(next_step)
  INSERT workflow_events
  XADD tasks:<next_step>
```

**D) 心跳超时恢复（heartbeat_monitor，每 15 秒）：**

```sql
SELECT * FROM step_executions
WHERE status='running'
  AND last_heartbeat_at < now() - interval '90 seconds'
```

对每条：
- `attempt < max_attempts` → 标记 `timeout`，插入新 attempt（pending），delayed enqueue（指数退避）
- 否则 → 工作流进入 `AWAITING_MANUAL_ACTION`

**E) 启动恢复（`recovery.run()`）：**

```
扫描 step_executions status='pending' AND workflow.status='*_RUNNING'
  检查是否存在于 Redis (XPENDING + XLEN 扫描)
  不存在的重新 XADD
记录恢复日志
```

### 4.3 配置

```python
class Settings(BaseSettings):
    database_url: str
    redis_url: str
    artifact_root: Path = Path("/var/lib/aijuicer/artifacts")

    heartbeat_timeout_sec: int = 90
    heartbeat_interval_sec: int = 30
    max_retries: int = 3
    retry_backoff_sec: list[int] = [60, 300, 900]

    step_max_duration: dict[str, int] = {
        "finder": 600,
        "requirement": 1800,
        "plan": 1800,
        "design": 3600,
        "devtest": 21600,
        "deploy": 1800,
    }

    log_level: str = "INFO"
    log_format: str = "json"

    class Config:
        env_prefix = "AIJUICER_"
        env_file = ".env"
```

---

## 5. Agent Python SDK

### 5.1 开发者端 API

```python
from aijuicer_sdk import Agent, RetryableError, FatalError

agent = Agent(
    name="ai-finder",
    step="finder",
    server="http://scheduler:8000",
    concurrency=2,
)

@agent.handler
async def handle(ctx, task):
    topic = task.input["topic"]
    await ctx.log.info("finder.start", topic=topic)
    await ctx.heartbeat("调用 LLM 生成 idea")

    try:
        resp = await call_llm(topic)
    except RateLimitError as e:
        raise RetryableError("LLM rate limit") from e
    except BadInputError as e:
        raise FatalError(str(e)) from e

    await ctx.save_artifact("idea.md", resp.text)
    return {"idea_summary": resp.text[:200]}

if __name__ == "__main__":
    agent.run()
```

### 5.2 SDK API 表

**Agent 构造参数：**

| 参数 | 默认 | 说明 |
|------|------|------|
| `name` | 必填 | agent 实例名，允许同 step 多实例 |
| `step` | 必填 | 负责处理的 step |
| `server` | `AIJUICER_SERVER` 环境变量 | scheduler 地址 |
| `redis_url` | `AIJUICER_REDIS_URL` | Redis 地址 |
| `concurrency` | 1 | 同时处理的任务数 |
| `heartbeat_interval` | 30s | 心跳间隔 |

**`ctx: AgentContext`：**

| 方法 | 说明 |
|------|------|
| `ctx.save_artifact(key, data)` | 保存产物（自动写 tmp+rename+注册元数据） |
| `ctx.load_artifact(step, key)` | 读取其他 step 产物 |
| `ctx.heartbeat(msg)` | 手动上报进度（自动心跳也存在） |
| `ctx.log.info/warn/error(event, **kv)` | 结构化日志，自动注入 request_id/workflow_id/step/attempt |
| `ctx.workflow_id` | 只读 |
| `ctx.request_id` | 只读 |
| `ctx.attempt` | 只读 |

**异常类：**

| 类 | 平台行为 |
|----|---------|
| `RetryableError` | 自动重试（上限 3 次 / 指数退避 1m, 5m, 15m） |
| `FatalError` | 不重试，转 `AWAITING_MANUAL_ACTION` |
| 其他 `Exception` | 默认按 `RetryableError`（保守） |

### 5.3 SDK 内部机制

Agent.run() 启动：

1. `POST /api/agents/register` 注册自己 → 拿 agent_id
2. 启动后台协程：
   - `heartbeat_loop`: 30s 上报在线 + 当前任务心跳
   - `fetch_loop`: `XREADGROUP` 拉任务 → 交给 worker pool
   - `idempotency_check`: 执行前查 task_id 是否已完成
3. 每任务一个 `asyncio.Task`，最多 `concurrency` 个并发
4. 执行流程：
   - `PUT /api/tasks/<task_id>/start`
   - 调 `handler(ctx, task)`
   - 成功 → `PUT /complete` + `XACK`
   - `RetryableError` → `PUT /fail?retry=1`
   - `FatalError` → `PUT /fail?retry=0`
5. 优雅退出：收 SIGTERM 停止拉新任务，等当前任务完成

### 5.4 产物跨机器访问

- 第一版假设 agent 与 scheduler 共享 FS（同机或 NFS）
- 若 agent 跑在无共享 FS 的远程机器，SDK 自动 fallback 到 HTTP: `GET /api/artifacts/<id>/download`
- 未来替换对象存储时，只改 `storage/fs.py` 抽象层

---

## 6. 可观测性

### 6.1 结构化日志（强制要求）

使用 `structlog`，JSON 格式输出：

```json
{
  "timestamp": "2026-04-20T10:15:32.123Z",
  "level": "info",
  "message": "step.started",
  "request_id": "req_7f2a9c1d",
  "workflow_id": "wf_b4c5...",
  "step": "finder",
  "attempt": 1,
  "agent_id": "ai-finder-01",
  "logger": "scheduler.engine.task_service"
}
```

**request_id 全链路：**

1. HTTP 入口 middleware：`X-Request-ID` 头沿用，否则生成 `req_<8 chars>`
2. 绑定到 asyncio `contextvar`，日志器自动注入
3. 持久化到 `step_executions.request_id` 与 `workflow_events.request_id`
4. 通过 Redis Streams payload 传给 agent
5. Agent SDK `ctx.log` 自动绑定相同 request_id，日志上报带入
6. 用 `request_id` 可 grep 完整链路：提交 → 调度 → agent → 产物保存

**强制：** 全代码库不得使用 `print` / `console.log`。pre-commit hook 强制检查。

### 6.2 指标（Prometheus）

`/metrics` 暴露：

| Metric | 类型 | 说明 |
|--------|------|------|
| `aijuicer_workflows_total{status}` | Counter | workflow 累计（按终态） |
| `aijuicer_step_duration_seconds{step,result}` | Histogram | step 执行时长 |
| `aijuicer_step_retries_total{step}` | Counter | 重试累计 |
| `aijuicer_agents_online{step}` | Gauge | 在线 agent 数 |
| `aijuicer_task_queue_depth{step}` | Gauge | Redis Stream 待处理长度 |
| `aijuicer_heartbeat_timeout_total{step}` | Counter | 心跳超时累计 |
| `aijuicer_manual_interventions_total` | Counter | 人工介入累计 |

第一版不附带 Grafana dashboard；后期可用 JSON 模板导入。

### 6.3 追踪

OpenTelemetry 在日志层预留，第一版不启用。

---

## 7. 人工介入 / Web UI

### 7.1 页面路由

| 路由 | 页面 | 主要元素 |
|------|------|---------|
| `/` | 工作流列表 | 表格：名称/状态/创建时间/当前 step 进度 |
| `/workflows/new` | 创建 workflow | 表单：名称、input JSON、审批策略 |
| `/workflows/:id` | 详情 | React Flow DAG + 事件时间线 + SSE 实时日志 |
| `/workflows/:id/steps/:step` | 步骤详情/审批 | 产物预览 + 审批按钮 + rerun 控件 |
| `/agents` | Agent 列表 | 在线/离线按 step 分组 |
| `/system/health` | 系统健康 | 队列深度、DB/Redis 连通性、恢复状态 |

### 7.2 审批/操作动作

- **Approve** → `AWAITING_APPROVAL_X` 推进至 `X_RUNNING`
- **Reject** → 终止 workflow (`ABORTED`)，附原因
- **Skip** → 跳过当前 step（仅 `AWAITING_MANUAL_ACTION` 可用）
- **Rerun (same input)** → 重跑当前 step（attempt+1）
- **Rerun (modified input)** → 编辑 input JSON 后重跑
- **Abort** → 任意非终态 → `ABORTED`，清理 pending task

所有动作都走 API，经 scheduler 写 DB 事务，SSE 推送前端刷新。

### 7.3 产物预览

- `.md/.txt/.json/.yml` → 文本渲染（react-markdown）
- `.png/.jpg/.svg` → `<img>`
- 代码目录（`05_devtest/repo/`）→ 文件树 + 单文件查看 + Shiki 高亮
- 二进制/大文件 → 元数据 + 下载链接

### 7.4 实时推送（SSE）

```
GET /api/workflows/<id>/events  (SSE)
```

后端：`event_publisher` worker `LISTEN` PostgreSQL `workflow_events_channel`；收到 NOTIFY 后 fan-out 到订阅客户端。

---

## 8. 部署

### 8.1 Docker Compose（主）

```yaml
# deploy/docker-compose.yml
services:
  scheduler:
    image: aijuicer/scheduler:latest
    ports: ["8000:8000"]
    depends_on: [postgres, redis]
    environment:
      AIJUICER_DATABASE_URL: postgresql+asyncpg://aijuicer:***@postgres/aijuicer
      AIJUICER_REDIS_URL: redis://redis:6379/0
      AIJUICER_ARTIFACT_ROOT: /var/lib/aijuicer/artifacts
    volumes:
      - artifact-data:/var/lib/aijuicer/artifacts

  webui:
    image: aijuicer/webui:latest
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_API_BASE: http://localhost:8000

  postgres:
    image: postgres:15
    volumes: [pgdata:/var/lib/postgresql/data]

  redis:
    image: redis:7
    volumes: [redisdata:/data]

  ai-finder:
    image: aijuicer/example-agents:latest
    command: python -m examples.ai_finder
    environment:
      AIJUICER_SERVER: http://scheduler:8000
      AIJUICER_REDIS_URL: redis://redis:6379/0
    volumes:
      - artifact-data:/var/lib/aijuicer/artifacts

volumes: {artifact-data: {}, pgdata: {}, redisdata: {}}
```

### 8.2 环境分层

- **开发**: `docker-compose.dev.yml` 挂载源码 hot-reload
- **生产**: `docker-compose.yml` + 外置 Postgres/Redis（推荐）+ `.env` 注入
- **K8s**: `deploy/k8s/` 预留目录，v2 任务

### 8.3 CLI

```bash
pip install aijuicer-cli

aijuicer workflow submit --name "..." --input @input.json
aijuicer workflow list
aijuicer workflow show <wf_id>
aijuicer workflow approve <wf_id> --step finder
aijuicer workflow rerun <wf_id> --step requirement --input @revised.json
aijuicer workflow logs <wf_id> --follow      # SSE 流式
```

---

## 9. 测试策略

### 9.1 分层

| 层 | 工具 | 覆盖 |
|---|------|------|
| 单元 | pytest + pytest-asyncio | state_machine 转换、SDK ctx API |
| 集成 | pytest + testcontainers | 起真实 Postgres + Redis，跑完整流水线 |
| 恢复 | pytest | DB commit 后崩溃 / 心跳丢失 / 重试超限 |
| 前端组件 | Vitest + RTL | 关键交互组件 |
| E2E | Playwright | 创建 → mock agent → 审批 → 完成 |

### 9.2 关键测试用例（必须）

1. **不变量**: 状态机任意转换路径不会出现同时 2 个 running step
2. **幂等**: 同一 task_id 重复交付，SDK 只执行一次
3. **恢复**: DB commit 后 kill -9，重启能补 XADD、无重复
4. **心跳超时**: 模拟 90s 不心跳，状态转重试或手工介入
5. **重试上限**: 3 次全失败后进入 `AWAITING_MANUAL_ACTION`

### 9.3 CI

- lint (ruff) + type check (mypy) + pre-commit（含 print 检查）
- pytest 覆盖率 ≥ 80%（engine/ 模块 ≥ 90%）
- 构建 Docker 镜像

---

## 10. 项目目录结构

```
AIClusterSchedule/
├── docs/
│   └── superpowers/specs/
│       └── 2026-04-20-aiclusterschedule-design.md    ← 本文档
├── scheduler/                    # 后端服务
│   ├── api/ engine/ workers/ storage/ observability/
│   ├── config.py main.py
│   └── tests/
├── sdk/
│   ├── aijuicer_sdk/
│   │   ├── agent.py context.py errors.py
│   │   ├── transport.py logging.py
│   ├── examples/
│   │   ├── ai_finder.py
│   │   ├── ai_requirement.py
│   │   ├── ai_plan.py
│   │   ├── ai_design.py
│   │   ├── ai_devtest.py
│   │   └── ai_deploy.py
│   └── tests/
├── webui/                        # Next.js 前端
│   ├── app/ components/ lib/
│   └── tests/
├── cli/
│   └── aijuicer_cli/
├── deploy/
│   ├── docker-compose.yml
│   ├── docker-compose.dev.yml
│   ├── scheduler.Dockerfile
│   ├── webui.Dockerfile
│   └── k8s/                      # 预留
├── .env.example
├── Makefile
├── pyproject.toml
└── README.md
```

---

## 11. 里程碑划分（实现顺序）

每个里程碑可独立验证。writing-plans 阶段会为每个里程碑生成独立实现计划。

| M | 交付 | 验证标准 |
|---|------|---------|
| M1 | **后端骨架**：Postgres schema + state_machine + 核心 API + 结构化日志+request_id | pytest 通过状态机所有转换测试 |
| M2 | **SDK 最小可用**：Agent 装饰器 + ctx.save/load_artifact + 心跳 + 异常分类 | 本地跑 echo agent，完成单 step workflow |
| M3 | **可恢复性**：重试/超时/启动恢复 | 恢复测试套件（kill -9 / 心跳超时）全绿 |
| M4 | **审批与人工介入**：approvals API + rerun/skip/abort | CLI 完整走完审批流程 |
| M5 | **Web UI v1**：列表页 + 详情页 + DAG + SSE + 审批 | 浏览器完整跑通 6 步 |
| M6 | **产物预览**：文本/图片/代码目录预览 | UI 能看到每步产物 |
| M7 | **6 个示例 agent 骨架** + Docker Compose 打包 | 一条命令起全栈 + 端到端 demo |
| M8 | **可观测性**：Prometheus `/metrics` + Grafana JSON 模板 | 能看关键指标 |

---

## 12. 开放问题 / 未来工作

第一版不做、但架构上已预留的扩展点：

- **认证授权**: middleware 扩展点；未来加用户/API Key/RBAC
- **对象存储**: `storage/fs.py` 抽象层；未来替换为 S3/MinIO
- **多语言 SDK**: Go/TypeScript SDK
- **K8s 部署**: `deploy/k8s/` Helm Chart
- **OpenTelemetry 追踪**: 日志层预留
- **多租户**: workflow 级别的 owner 字段和权限隔离
- **可插拔 step**: 将 6-step 硬编码升级为可配置的工作流模板

---

## 附录 A: request_id 流转示例

```
1. User 提交 workflow
   HTTP POST /api/workflows   X-Request-ID 未设置
   middleware 生成 req_7f2a9c1d

2. scheduler 写日志 {"request_id":"req_7f2a9c1d","message":"workflow.created"...}
   INSERT workflows request_id=...（通过 first step execution 关联）
   INSERT step_executions request_id="req_7f2a9c1d"
   INSERT workflow_events request_id="req_7f2a9c1d"

3. XADD tasks:finder {...,"request_id":"req_7f2a9c1d"}

4. Agent XREADGROUP 拿到 task
   SDK 把 request_id 绑到 contextvar
   ctx.log.info("finder.start") → {"request_id":"req_7f2a9c1d","step":"finder",...}

5. Agent 调 PUT /api/tasks/<id>/complete
   HTTP header X-Request-ID: req_7f2a9c1d
   scheduler 处理时日志继续带 req_7f2a9c1d

6. 最终：
   grep req_7f2a9c1d /var/log/aijuicer/*.json
   → 看到从创建到完成的所有日志
```

---

_本文档为 brainstorming 阶段产出的设计规格。下一步：writing-plans 阶段为每个里程碑生成详细的实现计划。_
