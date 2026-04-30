# AI 榨汁机 · Python SDK 使用文档

`aijuicer_sdk` 是 AI 榨汁机（AIJuicer）的 Python Agent SDK。
你用它写出的小脚本，就能作为流水线里某一 step 的执行者：从任务队列里拉任务、处理、写产物、上报结果——调度、重试、心跳、幂等、跨步读产物这些琐事 SDK 全都替你处理好。

适用人群：想把自己的 agent 接入 AI 榨汁机流水线的 Python 开发者。

---

## 目录

- [它是什么](#它是什么)
- [安装](#安装)
- [5 分钟上手](#5-分钟上手)
- [核心概念](#核心概念)
- [完整 API](#完整-api)
  - [`Agent` 构造参数](#agent-构造参数)
  - [`@agent.handler` 装饰器](#agenthandler-装饰器)
  - [`agent.run()` 与 `agent.arun()`](#agentrun-与-agentarun)
  - [`AgentContext`](#agentcontext)
  - [`SchedulerClient`（可单独用）](#schedulerclient可单独用)
  - [异常类](#异常类)
- [产物（artifact）规则](#产物artifact规则)
- [跨步骤读取上游产物](#跨步骤读取上游产物)
- [错误处理与重试](#错误处理与重试)
- [心跳与超时](#心跳与超时)
- [幂等与重复投递](#幂等与重复投递)
- [日志与链路追踪](#日志与链路追踪)
- [环境变量](#环境变量)
- [常见问题](#常见问题)
- [完整示例：把 AI Idea 展开成需求](#完整示例把-ai-idea-展开成需求)
- [目前的限制](#目前的限制)

---

## 它是什么

AI 榨汁机的流水线是 **固定 6 步**（按顺序）：

```
idea → requirement → plan → design → devtest → deploy
```

每一步都需要一个专门的 agent 来做实际工作。SDK 帮你写出这样一个 agent——一个进程，以装饰器风格注册 handler，然后常驻 → 拉任务 → 处理 → 上报。**你只需要关心"拿到输入、产出结果"，其他都是 SDK 的事。**

SDK 负责的事：

- 向 scheduler 注册（`POST /api/agents/register`），失败时**指数退避重试**（0.4.0+）
- 从 Redis Streams 拉任务（`XREADGROUP tasks:<step> agents:<step>`）
- 并发控制（`asyncio.Semaphore`）
- **两种心跳并行**：presence 心跳（每 5s 续 Redis TTL）+ task 心跳（handler 执行期每 30s）
- handler 成功 → 调 `PUT /api/tasks/<id>/complete`
- handler 抛异常 → 按异常类型分类上报 `/fail`（决定是否重试）
- XACK 消息消费完成
- **产物通过 HTTP 上传给 scheduler**（0.3.0+，字节直接进 DB），不再依赖共享 FS
- **暴露 /health HTTP 端点**（host:port 自动报给 scheduler，UI 可点）
- **自愈 Redis NOGROUP / 网络断**（0.4.0+，scheduler/Redis 重启不需要手动重启 agent）
- SIGTERM 优雅退出：停止拉新任务，等当前任务跑完

你负责的事：

- 写一个 `async def handle(ctx): ...` 函数
- 里面爱咋处理咋处理（调 LLM、爬数据、写代码、画 UI 原型 …）
- 用 `ctx.save_artifact(...)` 写产物
- 成功就 `return dict`；恢复不了就 `raise FatalError`；暂时挂了就 `raise RetryableError`

---

## 安装

**推荐：从 PyPI 装**

```bash
pip install aijuicer-sdk            # 默认装最新
pip install aijuicer-sdk==0.7.0     # 锁定版本
```

依赖（httpx / redis / structlog）会自动拉齐。装完即可 `from aijuicer_sdk import Agent`。

**开发态：从主仓库装（联调时改 SDK 源码）**

```bash
git clone git@github.com:blockdancez/ai-juicer.git
cd aijuicer
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'        # 整个 monorepo（含 scheduler）
# 或只要 SDK：
pip install -e sdk
```

---

## 5 分钟上手

写一个 `my_agent.py`：

```python
from aijuicer_sdk import Agent

agent = Agent(
    name="my-requirement-agent",   # 这个 agent 实例的名字，允许同 step 有多实例
    step="requirement",            # 负责哪一步（6 选 1）
    server="http://127.0.0.1:8000",
    redis_url="redis://127.0.0.1:6379/0",
    concurrency=1,
)


@agent.handler
async def handle(ctx):
    topic = ctx.input.get("text") or ""
    await ctx.heartbeat("正在写需求文档")

    # 读上一步 idea 的产出
    idea = (await ctx.load_artifact("idea", "idea.md")).decode("utf-8")

    # 做你的活儿
    req_md = f"# 需求文档\n\n源自 idea：\n```\n{idea[:300]}\n```\n..."

    # 写产物（原子落盘 + 自动注册到 scheduler）
    await ctx.save_artifact("requirements.md", req_md, content_type="text/markdown")

    # 返回的 dict 会写进 step_executions.output，供审计与后续步骤查看
    return {"features": 8, "stories": 5}


if __name__ == "__main__":
    agent.run()        # 阻塞跑到 SIGTERM
```

启动：

```bash
python my_agent.py
```

这个进程会持续活着，每当有新的 `requirement` 任务进来就处理一次。Ctrl+C 退出时 SDK 会等当前任务跑完再停。

---

## 核心概念

**`Agent`** — 一个 agent 进程。由 `name` 和 `step` 唯一标识这一类消费者，`concurrency` 控制同一进程内能并发处理几个任务。同一个 `step` 可以起多个进程（扩容），它们会通过 Redis consumer group 均衡拉任务。

**`@agent.handler`** — 业务逻辑入口。一个 Agent 只能有一个 handler。它会被每个拉到的任务调用一次。

**`AgentContext`（ctx）** — 每次 handler 被调用时 SDK 传给你的上下文对象。提供：
- 只读属性：`task_id` / `workflow_id` / `step` / `attempt` / `input` / `artifact_root` / `request_id`
- 副作用方法：`save_artifact`、`load_artifact`、`heartbeat`
- 结构化日志：`ctx.log.info/warn/error("event.name", k1=v1, ...)`

**`ctx.raw_payload`** — Redis Streams 里下发的原始 task payload（dict），结构：

```python
{
  "task_id": "uuid...",
  "workflow_id": "uuid...",
  "project_name": "ai-email-classifier",
  "step": "requirement",
  "attempt": 1,
  "input": {"text": "...", "user_feedback": {...}},   # workflow 创建时 + 历次重跑写入
  "request_id": "req_...",
  "artifact_root": "var/.../<wf>",                    # legacy，HTTP 模式不用
}
```

handler 里**别直接用** `raw_payload`——SDK 把每个字段都解构成 `ctx.<field>`，直接用 `ctx.input` / `ctx.attempt` / `ctx.project_name` 就行。`raw_payload` 只在做"自定义字段透传"等高级场景需要。

---

## 完整 API

### `Agent` 构造参数

```python
Agent(
    *,
    name: str,                        # 必填，agent 实例名
    step: str,                        # 必填，流水线的哪一步
    server: str | None = None,        # scheduler base URL；默认读 env AIJUICER_SERVER
    redis_url: str | None = None,     # Redis URL；不传则注册时由 scheduler 下发
    concurrency: int = 1,             # 同进程内的最大并发任务数
    block_ms: int = 5000,             # XREADGROUP 阻塞的毫秒数
    heartbeat_interval: float = 30.0, # handler 执行期间任务级自动心跳间隔（秒）
    presence_interval: float = 5.0,   # Agent 在线名册（Redis presence key）续期间隔
    health_host: str | None = None,   # /health HTTP server bind host；默认 0.0.0.0
                                      # 也可设 env AIJUICER_AGENT_HOST
    health_port: int | None = None,   # /health 端口；默认 0=系统分配；env AIJUICER_AGENT_PORT
    configure_logging: bool = True,   # 是否让 SDK 帮你配置 structlog JSON 输出
)
```

参数对应 6 个 step 的合法取值：

```
idea / requirement / plan / design / devtest / deploy
```

**`redis_url` 优先级**：构造参数 > `AIJUICER_REDIS_URL` 环境变量 > 注册响应里 scheduler 下发的 url。
推荐部署时只配 `server`，不配 redis——保证 SDK 与 scheduler 必然连同一个 Redis。

**`/health` HTTP 端点**：SDK 进程会监听一个本地 HTTP 端口（默认 `0.0.0.0` + 系统分配），
对外提供 `GET /health` 返回 `{status, name, step, pid}`。host:port 会随注册一起上报，
UI 的 Agent 列表会展示成可点击链接。多机部署时建议把 `AIJUICER_AGENT_HOST` 设为对外可达的真实 IP。

### `@agent.handler` 装饰器

#### 函数签名（0.6.0+）

```python
from aijuicer_sdk import Agent, AgentContext, HandlerOutput

agent = Agent(name="my-agent", step="idea")

@agent.handler
async def handle(ctx: AgentContext) -> HandlerOutput | None:
    ...
```

**单参数**：`ctx` 同时承载数据（task_id / workflow_id / project_name / step / attempt /
input / request_id）和方法（heartbeat / save_artifact / load_artifact / log）。
不再单独传 `task` dict——之前那是 ctx 字段的重复，0.6.0 移除。

> 历史版本 0.5.0 及之前是 `async def handle(ctx, task)` 双参数；升级 0.6.0
> 时把 `task["..."]` 改成 `ctx....`，把签名第二个参数删掉即可。需要原始 dict 时
> 用 `ctx.raw_payload`。

每个 Agent 实例只能注册**一个** handler；重复装饰会 `RuntimeError`。

#### 唯一入参：`ctx: AgentContext`

handler 操作"这一次执行"的载体。**字段都是只读**，由 SDK 从 task payload 注入：

| 字段 | 类型 | 含义 |
|---|---|---|
| `ctx.task_id` | `str` | 该次执行的 UUID（= `step_executions.id`） |
| `ctx.workflow_id` | `str` | 工作流 UUID |
| `ctx.project_name` | `str` | 项目 slug（小写英文 + 短横线），全局唯一。后续做仓库目录、数据库名、项目文件夹命名都基于这个值 |
| `ctx.step` | `str` | 6 步之一：`idea` / `requirement` / `plan` / `design` / `devtest` / `deploy` |
| `ctx.attempt` | `int` | 第几次尝试。`1` = 首跑；`2+` = 重跑（每次重跑递增）|
| `ctx.input` | `dict` | 工作流的 input 字典；详见下面 |
| `ctx.request_id` | `str` | 链路追踪 id；SDK 自动写进所有上行 HTTP header 和日志 contextvars |
| `ctx.raw_payload` | `dict` | scheduler 派发的原始 task payload（含上面所有字段）；只在做"自定义字段透传"时用 |
| `ctx.log` | `structlog.BoundLogger` | 已绑定全部业务字段的日志器；用 `await ctx.log.ainfo("xxx", k=v)` |
| `ctx.artifact_root` | `str` | _legacy_：旧共享 FS 模式下的本地目录路径；HTTP 模式不用 |

**`ctx.input` 的常见结构**：

```python
{
    # 用户在"新建工作流"页面输入的文本
    "text": "做一个面向大学生的 AI 课程笔记助手",

    # 历次重跑指令（按 step 分别保留）。每次用户在 UI 点"重新执行 X"
    # 写指令并提交时，scheduler 把指令写到 user_feedback[X]——
    # 注意：当前实现是覆盖式（保留最新一次），不是 append 数组。
    "user_feedback": {
        "idea": "标题再短一些",
        "requirement": "去掉非功能性需求",
    },
}
```

可调方法：

```python
# 1. 上报当前进度（手动心跳）；SDK 自动每 30s 也会发一次
await ctx.heartbeat("正在调用 LLM ...")

# 2. 上传产物字节给 scheduler；scheduler 写进 DB（artifacts.content BYTEA）
ref = await ctx.save_artifact(
    "idea.md",
    "# hello",            # str 或 bytes 都行
    content_type="text/markdown",
)
# ref.key / ref.size_bytes / ref.sha256

# 3. 拉某个 step 的最新产物字节（不限本 step，可跨步骤读上游）
raw = await ctx.load_artifact("idea", "idea.md")
text = raw.decode("utf-8")
```

> handler 可以混合 `ctx.input["text"]`（首次输入） + `ctx.input.get("user_feedback", {}).get(ctx.step)`（最新重跑指令） + `await ctx.load_artifact(ctx.step, "<key>")`（**上次输出**）来自由拼 LLM prompt。
> 想看更早的 attempt 输出，目前 SDK 只暴露"最新 attempt"——历史 attempt 要走
> `GET /api/workflows/{wf}/artifacts` 自己列 + `GET /api/artifacts/{id}/content` 取。

#### 出参：`HandlerOutput | None`

返回值类型 = `dict[str, Any]`（JSON-serializable）或 `None`：

- 写进 `step_executions.output`（Postgres JSONB 列）
- 通过 SSE `task.succeeded` 事件广播，UI 能看到
- 返回 `None` 等同 `{}`

**约定**：output 应放些**轻量摘要信息**（`{"chosen": "...", "tokens_used": 1234, "score": 0.87}` 之类），**真正的产物**用 `ctx.save_artifact(key, content)` 落 DB。
output 不是用来传大段文本或字节的。

#### 异常约定

```python
from aijuicer_sdk import RetryableError, FatalError
```

| 抛出 | 行为 |
|---|---|
| `FatalError(...)` | scheduler 不重试，workflow 进入 `AWAITING_MANUAL_ACTION`，等用户处理 |
| `RetryableError(...)` | 在 `max_retries`（默认 3）内自动重试；超过转 `AWAITING_MANUAL_ACTION` |
| 任意其它 `Exception` | 兜底按 `RetryableError` 处理（避免一个隐藏 bug 让任务永远丢失） |

#### 完整最小示例

```python
from aijuicer_sdk import Agent, AgentContext, FatalError, HandlerOutput, RetryableError

agent = Agent(name="my-requirement-agent", step="requirement", server="http://aijuicer:8000")

@agent.handler
async def handle(ctx: AgentContext) -> HandlerOutput:
    # 1. 拉上一步（idea）的最新产物作为输入
    try:
        idea_md = (await ctx.load_artifact("idea", "idea.md")).decode("utf-8")
    except FileNotFoundError:
        raise FatalError("upstream idea step has no artifact")

    # 2. 看是不是重跑，有没有用户反馈
    feedback = (ctx.input.get("user_feedback") or {}).get(ctx.step)
    is_rerun = ctx.attempt > 1 or feedback is not None

    # 3. 上报心跳（可选；SDK 也自动发 30s 心跳）
    await ctx.heartbeat("调用 LLM 生成需求")

    # 4. 业务逻辑（这里假设有 generate_prd 函数；失败时手动选异常类型）
    try:
        prd = await generate_prd(idea_md, feedback=feedback)
    except RateLimitError as e:
        raise RetryableError(f"LLM rate limited: {e}") from e
    except ValidationError as e:
        raise FatalError(f"LLM 输出格式不合规: {e}") from e

    # 5. 保存产物
    await ctx.save_artifact("requirement.md", prd["content"], content_type="text/markdown")

    # 6. 返回轻量摘要
    return {"title": prd["title"], "tokens": prd["tokens_used"], "rerun": is_rerun}

if __name__ == "__main__":
    agent.run()
```

### `agent.run()` 与 `agent.arun()`

`run()` 是同步阻塞入口（内部 `asyncio.run(arun())`），收到 `SIGTERM` / `SIGINT` 优雅退出。
当你想在自己的 asyncio 主循环里**和别的协程并行跑**（比如 example `ai_idea` 的"周期性
产生工作流"逻辑），改用 async 版的 `arun()`：

```python
async def main():
    # 自己的后台任务（如周期性 producer）
    producer = asyncio.create_task(my_loop())
    try:
        await agent.arun()              # 阻塞直到 shutdown
    finally:
        producer.cancel()

asyncio.run(main())
```

主循环内部做的事：

1. 启动本地 `/health` HTTP server，拿到实际监听的 host:port
2. `POST /api/agents/register`（带 host/port/pid metadata）拿到 `agent_id` + `redis_url`
3. 用最终生效的 `redis_url` 初始化 Redis 客户端
4. 确保自己的 consumer group 存在（`XGROUP CREATE ... MKSTREAM`，`BUSYGROUP` 视为已存在）
5. 启动 presence heartbeat 协程（每 `presence_interval` 秒续 `agent:<step>:<id>` Redis TTL key）
6. 进入主循环：`XREADGROUP` 拉一批消息 → 每条 spawn 一个 worker（受 `concurrency` 信号量限制）
7. 每个 worker：
   - `PUT /api/tasks/<id>/start`（收到 `started=False` 说明重复投递，直接跳过）
   - 启动**任务级**自动心跳 sibling task（`heartbeat_interval` 秒一次）
   - 调你的 handler
   - 成功：`PUT /complete` + XACK
   - `FatalError`：`PUT /fail?retryable=false` + XACK
   - `RetryableError` / 其它：`PUT /fail?retryable=true` + XACK
   - 无论成功失败：取消心跳 task + XACK + 释放信号量
8. 收到信号：设置 `_shutdown` event → 停止拉新任务 → `asyncio.gather` 等当前 inflight 跑完
   → 取消 presence heartbeat → 关闭 health server

### `AgentContext`

```python
class AgentContext:
    # 只读属性
    task_id: str              # 这次任务的 UUID
    workflow_id: str          # 所属 workflow 的 UUID
    step: str                 # 你负责的 step（= Agent 构造时的 step）
    attempt: int              # 本次是第几次尝试（从 1 开始；失败重试会递增）
    input: dict               # workflow 的原始 input（不随 step 变）
    artifact_root: Path       # 本 workflow 的产物根目录
    request_id: str           # 全链路 request_id
    log: structlog.BoundLogger  # 预绑定好上下文的日志器

    # 方法
    async def save_artifact(key: str, data: str | bytes, *,
                            content_type: str | None = None) -> ArtifactRef: ...
    def     load_artifact(step: str, key: str) -> bytes: ...
    async def heartbeat(message: str | None = None) -> None: ...
```

`ArtifactRef`（`save_artifact` 返回）：

```python
@dataclass
class ArtifactRef:
    key: str         # 你传的 key
    path: Path       # 磁盘上的绝对路径
    size_bytes: int  # 字节数
    sha256: str      # 内容 sha256
```

### `SchedulerClient`（可单独用）

`SchedulerClient` 是 SDK 内部对 scheduler HTTP API 的封装。一般 handler 里用不到
（`AgentContext` 已经替你包好了 `save_artifact` / `heartbeat`），但你可以**直接
import 它来主动创建工作流**——比如写一个"持续生产 idea 的 producer"。

#### 用法 1：只给一个 topic，由 idea agent 展开

`project_name` 是项目 slug（小写英文 + 短横线），用作仓库 / DB schema / 文件夹命名，
**由调用方自己生成**。撞名时 scheduler 自动加 4 位随机后缀，无需预先查重。
SDK 提供 `slugify_idea` 作便利工具，caller 想自定义可以不用。

```python
from aijuicer_sdk import slugify_idea
from aijuicer_sdk.transport import SchedulerClient

async def submit():
    client = SchedulerClient("http://aijuicer:8000")
    try:
        topic = "做一个 AI 简历优化工具"
        wf = await client.create_workflow(
            name="auto · 我的想法",
            project_name=slugify_idea(topic),  # 例：ai
            input={"text": topic},
            approval_policy={},
        )
        print(wf["id"], wf["project_name"])
    finally:
        await client.close()
```

scheduler 会入队 `tasks:idea`，等某个注册了 `step="idea"` 的 agent 把 input 展开成
完整 idea.md 才进下一步。

#### 用法 2：producer 已经有完整 idea，**跳过 idea step**（0.7.0+）

producer 自己已经写好 idea 内容时（比如 AIIdea 那种"产品体验报告"是直接拿来就能
用的成品），不必让 idea agent 再二次加工。把 idea 产物随 create_workflow 一起传，
scheduler 直接落盘并跳过 idea 的 RUNNING：

```python
await client.create_workflow(
    name="产品体验 · Culina Core",
    project_name="culina-core",
    input={"text": "Culina Core 产品体验报告"},
    approval_policy={"requirement": "manual"},
    initial_artifacts=[
        {
            "step": "idea",
            "key": "idea.md",
            "content": "<完整 markdown 字符串>",
            "content_type": "text/markdown",
        },
    ],
)
```

这条工作流被创建出来时**直接进入 `AWAITING_APPROVAL_REQUIREMENT`**（如果
`approval_policy.requirement == "auto"` 则继续推进）；不会 XADD 到 `tasks:idea`，
不会触发任何 idea agent。

**因此 producer 可以选择不再注册 `step="idea"` 的 handler**——纯做提交方，避免"自己提
交、自己消费"的回环。

`initial_artifacts` 的元素结构：

| 字段 | 类型 | 含义 |
|---|---|---|
| `step` | `str` | 6 步之一。一般给 `"idea"`；其它步骤也支持但少见用法 |
| `key` | `str` | 产物文件名，如 `"idea.md"` |
| `content` | `str` | utf-8 文本内容 |
| `content_type` | `str?` | MIME，省略由后端根据 key 后缀推断 |

> 只有当 `initial_artifacts` 里**有 step="idea" 的条目**时，scheduler 才会跳过
> idea step。给其它 step 的产物只是预填，不影响状态机推进顺序。

#### 可用方法

- `register_agent(*, name, step, metadata=None)` —— 注册（SDK 自动用，一般无需手调）
- `agent_heartbeat(*, agent_id, name, step, metadata=None)` —— 续 presence TTL（SDK 自动用）
- `task_start / task_complete / task_fail / task_heartbeat` —— 任务生命周期（SDK 自动用）
- **`upload_artifact(*, workflow_id, step, key, data, content_type, request_id)`** —— multipart 上传产物字节（`AgentContext.save_artifact` 内部已调，0.3.0+）
- **`fetch_artifact_by_key(*, workflow_id, step, key) -> bytes`** —— 按 (wf, step, key) 拉产物字节（`AgentContext.load_artifact` 内部已调，0.3.0+）
- `create_artifact(...)` —— 旧版仅注册元数据（path 指向共享 FS），仅留作向前兼容；新代码用 `upload_artifact`
- **`create_workflow(*, name, project_name, input, approval_policy=None, initial_artifacts=None)`** —— 主动建工作流；`project_name` 由调用方生成（可用 `aijuicer_sdk.slugify_idea`），`initial_artifacts` 可跳过 idea step（0.8.0+）
- `close()` —— 关 httpx client

### 异常类

```python
from aijuicer_sdk import RetryableError, FatalError

raise RetryableError("LLM rate limit, 稍后重试")
raise FatalError("input 缺少 topic 字段，人工检查")
```

---

## 产物（artifact）规则

**0.3.0 起：产物字节通过 HTTP 上传给 scheduler，存进 Postgres `artifacts.content`
（BYTEA 列）。**Agent 不再写本地文件系统，scheduler 是唯一权威——**Agent 与 scheduler
可以跑在不同机器/容器/云**，无需共享 FS 或 NFS。

`ctx.save_artifact(key, data, content_type=...)` 内部做的事：

1. 把字符串 / bytes 拼成 multipart 字段
2. `POST /api/artifacts/upload`（form: `workflow_id` `step` `key` `content_type_hint` + file）
3. scheduler 流式收 → 计算 sha256 → INSERT/UPSERT `artifacts(content=BYTEA, sha256, size_bytes, content_type)`
4. 返回元数据；本地 `ArtifactRef` 含 `key / size_bytes / sha256`

保证：

- **幂等**：同一 `(workflow_id, step, key)` 再次调用走 `ON CONFLICT DO UPDATE`，重试不会留下孤儿行
- **sha256**：服务端流式计算，不依赖客户端
- **content_type 推断**：不传 `content_type` 时按 `key` 后缀用 `mimetypes.guess_type` 推断
- **大小**：BYTEA 走 Postgres TOAST，单条 ~1GB 上限。短文本（markdown / URL / JSON）完全没压力；想存视频请走对象存储另设方案

```python
# 字符串或字节都行
await ctx.save_artifact("idea.md", "# hello")
await ctx.save_artifact("bundle.tar.gz", raw_bytes, content_type="application/gzip")

ref = await ctx.save_artifact("plan.json", json.dumps(plan))
ctx.log.info("saved", key=ref.key, size=ref.size_bytes, sha256=ref.sha256)
```

> **`.first.*` 副本约定**（example agents 的惯例，非 SDK 强制）：在 `ctx.attempt == 1`
> 时**多保存一份** `<key>.first.<ext>` 副本，以后重跑不再覆盖它。这样工作流详情页的
> "产物对比"面板能拿到首次输出和当前输出做 diff。
>
> ```python
> await ctx.save_artifact("idea.md", body, content_type="text/markdown")
> if ctx.attempt == 1:
>     await ctx.save_artifact("idea.first.md", body, content_type="text/markdown")
> ```

---

## 跨步骤读取上游产物

`load_artifact` **是 async**（0.3.0 起），通过 HTTP 从 scheduler 拉取：

```python
# 在 requirement agent 里读 idea 那一步写的 idea.md
raw = await ctx.load_artifact("idea", "idea.md")   # 返回 bytes
text = raw.decode("utf-8")
```

内部走 `GET /api/workflows/{wf_id}/artifacts/by-key/content?step=...&key=...`。
找不到时抛 `FileNotFoundError`（与旧 FS 版语义一致）。

⚠️ 升级提示：从 0.2.0 升 0.3.0 的 agent 代码必须把所有 `ctx.load_artifact(...)` 改成
`await ctx.load_artifact(...)`，且如果链式调了 `.decode()` 等方法要加括号：

```python
# 0.3.0 之后必须这样写
prev = (await ctx.load_artifact("idea", "idea.md")).decode("utf-8")
```

---

## 错误处理与重试

三种结局：

| 抛出 | SDK 上报 | 调度器行为 |
|---|---|---|
| `return dict` | `PUT /complete` | step 标 succeeded，按 policy 推进到下一步 |
| `raise RetryableError(...)` | `PUT /fail?retryable=true` | 如果 `attempt < max_retries` 自动重试（新 attempt 入队）；否则转 `AWAITING_MANUAL_ACTION` |
| `raise FatalError(...)` | `PUT /fail?retryable=false` | 不重试，直接转 `AWAITING_MANUAL_ACTION` |
| `raise <其它 Exception>` | 当作 Retryable 处理 | 同 `RetryableError`（保守策略，避免 bug 静默丢任务） |

`max_retries` 由 scheduler 侧配置（默认 3，读自 `AIJUICER_MAX_RETRIES`）。

典型用法：

```python
@agent.handler
async def handle(ctx):
    try:
        resp = await call_llm(ctx.input.get("text", ""))
    except RateLimitError as e:
        raise RetryableError(f"LLM 限流：{e}") from e
    except BadInputError as e:
        raise FatalError(f"输入有问题，人工看一下：{e}") from e

    await ctx.save_artifact("result.md", resp.text)
    return {"tokens": resp.usage.total_tokens}
```

---

## 心跳与超时

SDK 跑两种独立心跳，它们互不依赖：

| 心跳 | 何时跑 | 频率 | 端点 | 作用 |
|---|---|---|---|---|
| **Presence 心跳** | 注册成功后**一直跑**到 shutdown | `presence_interval`（默认 5s） | `POST /api/agents/{id}/heartbeat` | 续 Redis TTL key（`agent:<step>:<id>` TTL=15s）→ 维持 UI 在线名册 |
| **Task 心跳** | handler 执行**期间**起 sibling task | `heartbeat_interval`（默认 30s） | `PUT /api/tasks/{id}/heartbeat` | 让 scheduler 知道任务没卡死，避免被 heartbeat_monitor 判超时 |

- **手动心跳**：可以随时 `await ctx.heartbeat("当前进度描述")` 上报进度消息（写进 `step_executions.heartbeat_message`，UI 可见）。
- **超时判定在 scheduler 侧**：`heartbeat_monitor` 每 `heartbeat_interval_sec // 2` 秒扫一次，对 `status='running' AND last_heartbeat_at < now() - heartbeat_timeout_sec`（默认 90s）的 step，按 `retryable=True` 调 `TaskService.fail`——要么进入下一个 attempt，要么转人工介入。

只要 handler 不卡死超过 90s 不心跳就安全。LLM 调用、长下载等"慢但还在跑"的场景，SDK 的自动心跳是**同级 asyncio task**，不受 handler 阻塞影响。

### 自愈：scheduler / Redis 重启不需要重启 agent

0.4.0 起所有连接环节都带退避重试，agent **顺序无关**、**重启自愈**：

| 故障 | SDK 行为 |
|---|---|
| 启动时 scheduler 还没起（先 agent 后 scheduler） | `register_agent` 失败 → 指数退避 1→2→4→…→30s 一直重试到成功 |
| 运行中 scheduler 重启 | presence/task 心跳几次 connection refused 被吞掉，scheduler 起回来后立即续 Redis key 并恢复（heartbeat 端点无状态、不需要 agent_id 已知） |
| Redis 重启（流和 consumer group 全没了） | XREADGROUP 抛 `NOGROUP` → SDK 捕获 → 调 `XGROUP CREATE` 重建 → 继续消费 |
| Redis 网络断了 | XREADGROUP 抛 `ConnectionError` → 退避 1→30s 重试，shutdown 信号能立即唤醒 |
| 长时间 scheduler 不可达 | presence 心跳头一次失败打 1 行 warning，后续静默退避，恢复后打 1 行 `presence.recovered`——不刷屏 |

---

## 幂等与重复投递

分布式系统中，任务被投递多次是常态（scheduler 启动恢复、agent 挂掉后心跳超时等）。SDK 对此的处理：

1. `PUT /start` 时 scheduler 检查 step 当前状态。如果 step 已经不是 `pending`（说明别人已经接走了），API 返回 `{"started": false}`，SDK **跳过 handler，只 XACK**，不会二次执行。
2. 你自己也最好让产物生成路径**内容可重现**（相同 input → 相同产出）。`save_artifact` 的 UPSERT 会兜底，但 handler 里不要有"第一次跑就消费一次配额"的副作用。

如果你的 handler 本身有强副作用（调付费 API、发邮件等），可以额外用 `ctx.task_id` 作为幂等 key 自己做去重。

---

## 日志与链路追踪

SDK 默认启用 `structlog` + JSON 输出：

```python
ctx.log.info("fetching.llm", model="gpt-4.1", tokens_in=1200)
ctx.log.warning("rate.limited", retry_after_sec=30)
```

输出示例：

```json
{
  "timestamp": "2026-04-24T02:53:14.123Z",
  "level": "info",
  "message": "fetching.llm",
  "request_id": "req_a1b2c3",
  "workflow_id": "uuid...",
  "step": "requirement",
  "attempt": 1,
  "task_id": "uuid...",
  "model": "gpt-4.1",
  "tokens_in": 1200
}
```

`request_id` 全链路贯通：从提交 workflow 的 HTTP 请求 → scheduler 日志 → Redis payload → SDK handler 日志 → 你调回 scheduler 的 HTTP header → scheduler 二次日志。用 `grep req_a1b2c3 *.log` 能看到完整链路。

不喜欢 SDK 默认日志格式？构造时传 `configure_logging=False`，自己配 `structlog.configure(...)` 即可。

---

## 环境变量

SDK 会读取（构造参数优先，环境变量兜底）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `AIJUICER_SERVER` | `http://localhost:8000` | scheduler HTTP base URL（**必配**） |
| `AIJUICER_REDIS_URL` | _空_ | Redis URL；**留空时** SDK 会用注册响应里 scheduler 下发的 URL |
| `AIJUICER_AGENT_HOST` | `0.0.0.0` | `/health` HTTP server bind host；多机部署时建议设对外 IP |
| `AIJUICER_AGENT_PORT` | `0`（系统分配） | `/health` HTTP server 端口 |

典型本机 `.env` 片段：

```bash
export AIJUICER_SERVER=http://127.0.0.1:8000
# Redis 让 scheduler 下发，留空即可
export AIJUICER_AGENT_HOST=127.0.0.1   # 让 UI 上的 /health 链接能直接点开
```

---

## 常见问题

**Q: 同一个 step 可以跑多个 agent 进程吗？**
A: 可以。它们通过同一个 Redis consumer group 均衡拉任务（`XREADGROUP` 原生语义）。这是水平扩容的主要方式。

**Q: `name` 必须唯一吗？**
A: 不需要。`name` 只是人类可读标识，`agent_id` 是 scheduler 分配的 UUID。多进程用同一 `name` 没问题。

**Q: handler 里可以启动别的 asyncio task 吗？**
A: 可以，但建议在 handler 返回前 `await` 掉它们。handler 返回就意味着任务完成，scheduler 会把 step 标 succeeded，再启动的 task 不会影响状态但可能被进程退出 cancel。

**Q: 能处理同步函数吗？**
A: handler 本身必须 `async def`，但里面可以 `await asyncio.to_thread(sync_fn, ...)` 跑同步代码。

**Q: 产物很大（几 GB）怎么办？**
A: `save_artifact` 当前是一次性写整块 `bytes`，适合中小文件（< 几十 MB）。巨大产物建议你自己流式写到 `ctx.artifact_root / <step_dir> / key`，然后手动 `ctx._client.create_artifact(...)`（未来 SDK 会提供更正式的流式接口）。

**Q: 我的 agent 起不来，卡在 `agent.registered` 之前？**
A: 99% 概率是 scheduler 或 Redis 没连上。检查：
- `curl $AIJUICER_SERVER/health` 应该返回 `{"status":"ok"}`
- `redis-cli -u $AIJUICER_REDIS_URL ping` 应该返回 `PONG`

**Q: 如何本地测试我的 handler 逻辑，不想真的连 scheduler / Redis？**
A: 直接单元测试：用 `AsyncMock` 替换 `SchedulerClient`，手动构造 `AgentContext`：

```python
from unittest.mock import AsyncMock
from aijuicer_sdk.context import AgentContext

async def test_my_handler(tmp_path):
    client = AsyncMock()
    ctx = AgentContext(
        task_id="t", workflow_id="w", step="requirement", attempt=1,
        input={"topic": "hi"}, artifact_root=str(tmp_path),
        request_id="req_test", client=client,
    )
    out = await handle(ctx, {"input": {"topic": "hi"}})
    assert out["features"] > 0
    assert (tmp_path / "02_requirement" / "requirements.md").exists()
```

SDK 自己的单测（`sdk/tests/`）就是这个模式。

---

## 完整示例：把 AI Idea 展开成需求

```python
"""ai_requirement.py —— 流水线第二步 agent。"""
from __future__ import annotations

import json

from aijuicer_sdk import Agent, FatalError, RetryableError

agent = Agent(
    name="ai-requirement",
    step="requirement",
    concurrency=2,                 # 允许同时处理 2 个任务
    heartbeat_interval=20.0,       # 每 20 秒自动心跳
)


async def call_llm(prompt: str) -> str:
    """占位：真实场景改成你自己的 LLM 调用。"""
    import asyncio
    await asyncio.sleep(0.1)
    return f"# 需求文档\n\n输入:\n{prompt}\n\n..."


@agent.handler
async def handle(ctx):
    if "text" not in ctx.input:
        raise FatalError("input.text 缺失，人工介入")

    await ctx.heartbeat("读取上游 idea")
    try:
        idea = (await ctx.load_artifact("idea", "idea.md")).decode("utf-8")
    except FileNotFoundError as e:
        raise RetryableError(f"上游 idea 产物还没准备好: {e}") from e

    await ctx.heartbeat("调用 LLM 展开需求")
    try:
        md = await call_llm(f"text={ctx.input['text']}\n\nidea:\n{idea}")
    except TimeoutError as e:
        raise RetryableError(f"LLM 超时: {e}") from e

    await ctx.save_artifact("requirements.md", md, content_type="text/markdown")
    await ctx.save_artifact(
        "summary.json",
        json.dumps({"source": "idea.md", "length": len(md)}, ensure_ascii=False),
        content_type="application/json",
    )
    ctx.log.info("requirement.done", length=len(md))
    return {"bytes": len(md)}


if __name__ == "__main__":
    agent.run()
```

启动：

```bash
AIJUICER_SERVER=http://127.0.0.1:8000 \
AIJUICER_REDIS_URL=redis://127.0.0.1:6379/0 \
python ai_requirement.py
```

触发一次完整流水线（需要 6 个 step 的 agent 都在跑）：

```bash
# AIFinder 作为 "投喂者"——不是 SDK 的消费者，而是通过 HTTP 直接提交 workflow
python -m sdk.examples.ai_finder --topic "AI 代码审查助手" --auto
# 🧃 AIJuicer 接单：<wf_id> ← topic: AI 代码审查助手
```

然后在 Web UI http://127.0.0.1:3000 看流水线 6 个 step 依次变绿，每步的产物都出现在详情页。

---

## 目前的限制

| 限制 | 备注 |
|---|---|
| 只有 Python SDK | Go / TypeScript SDK 是 v2 任务 |
| 没有 pull 式 Admin API | 想动态列出自己注册过的 agent 实例，只能查 `/api/agents` |
| 单进程代理不做 PEL 扫描 | Redis PEL 里被 claim 没 ack 的消息依赖 scheduler 的启动恢复兜底；未来在 SDK 侧加主动 `XPENDING + XCLAIM` |
| 大产物（>50 MB）走 BYTEA 不理想 | 现在产物字节进 Postgres `artifacts.content`（TOAST 后单条上限 ~1GB）。视频 / 模型权重等大文件请走 S3，未来给 SDK 加 `presigned_upload` 选项 |
| 不支持 Python 3.11 及以下 | 要求 Python 3.12+（用了 `StrEnum`、新版类型语法等） |

欢迎在主仓库提 issue / PR。
