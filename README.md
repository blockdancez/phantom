# Phantom

Phantom 是一组围绕 AI 驱动的软件研发流水线的子项目集合,聚合在同一个仓库中维护。

## 子项目分工

| 目录 | 角色 | 技术栈 |
| --- | --- | --- |
| `AIIdea/` | **创意采集**:多源采集行业动态,LLM 打分/摘要,生成创意候选 | FastAPI + Next.js + Postgres |
| `AIRequirement/` | **需求生成**:把 idea 转换成结构化中文 PRD | FastAPI + React + Postgres |
| `AIPlan/` | **规划阶段 worker**:调 PhantomCLI 生成 `plan.locked.md` | Python + AIJuicer SDK |
| `AIDesign/` | **UI 设计阶段 worker**:调 PhantomCLI 生成 `ui-design/` 产物 | Python + AIJuicer SDK |
| `AIDevTest/` | **开发测试阶段 worker**:调 PhantomCLI 跑 dev → review → deploy → test | Python + AIJuicer SDK |
| `PhantomCLI/` | **底层 CLI 工具(`phantom` 命令)**:被上面三个 worker 调用,真正驱动 Claude Code / Codex 完成代码工作 | Bash + Python |
| `AIDeploy/` | **部署阶段**(占位,未实现) | — |
| `AIJuicer/` | **中央调度平台**:6 步固定流水线状态机、任务队列、Web UI | FastAPI + Next.js + Postgres + Redis |

> **`PhantomCLI` 不是阶段,是工具**。它提供 `phantom` 这个 CLI 命令(`phantom --plan`、`phantom --design`、`phantom --dev-test`),`AIPlan / AIDesign / AIDevTest` 三个 worker 都是它的薄包装。

## 调用关系

```
                ┌─────────────────────────────────────────────┐
                │            AIJuicer Scheduler               │
                │   (6 步固定流水线 / Postgres 状态机)         │
                │   Idea → Requirement → Plan → Design →    │
                │            DevTest  → Deploy                │
                └──────┬──────────────────────────────────────┘
                       │ Redis Streams(每个 step 一个队列 + consumer group)
        ┌──────────────┼──────────┬──────────┬──────────┐
        ▼              ▼          ▼          ▼          ▼
    AIIdea       AIRequirement  AIPlan   AIDesign  AIDevTest
   (worker     (worker        (worker)  (worker)   (worker)
    + webapp)   + webapp)        │         │          │
                                 │         │          │
                                 └─────────┼──────────┘
                                           ▼
                                  PhantomCLI / phantom CLI
                                  (bash 编排状态机)
                                           │
                                           ▼
                                  Claude Code / Codex CLI
                                           │
                                           ▼
                            目标项目工作区(产出代码与产物)
                            /Users/lapsdoor/phantom/<project_name>/
                            ├─ .phantom/state.json
                            ├─ requirements.md
                            ├─ .phantom/plan.locked.md
                            ├─ ui-design/
                            ├─ backend/  frontend/  ...
                            └─ test-report/
```

## 数据流转

按 AIJuicer 流水线一次完整运行:

1. **Idea(AIIdea worker)** — 采集器抓取 RSS / HackerNews / Reddit / Product Hunt / GitHub Trending 等数据源 → LLM 打分摘要 → ReAct Agent 生成创意报告 → 输出 `idea.md` artifact 到 AIJuicer。
2. **Requirement(AIRequirement worker)** — 读上游 `idea.md` → Tavily 调研 + GPT-4o 撰写 → 输出中文 PRD `requirements.md` 到工作区根目录,同时落库 `Idea + Document` 表。
3. **Plan(AIPlan worker)** — 在工作区目录执行 `phantom --plan <requirements.md>`,phantom 内部驱动 plan_generator + 跨模型 plan_reviewer 多轮迭代 → 产出 `.phantom/plan.locked.md`。
4. **Design(AIDesign worker)** — 执行 `phantom --design`,phantom 驱动 ui-design 提示词三轮(design → design-review → design)→ 产出 `ui-design/` 目录(组件、样式、原型)。
5. **DevTest(AIDevTest worker)** — 执行 `phantom --dev-test`,phantom 内部按 sprint 分组循环跑 dev → code-review → deploy → test 一圈,失败回流到 dev → 产出可运行的 `backend/`、`frontend/`、部署日志、`test-report/`。
6. **Deploy** — 占位(`AIDeploy/` 暂未实现)。

**贯穿始终的不变量:**

- 工作区根目录 = `PHANTOM_PROJECTS_BASE/<project_name>`(默认 `/Users/lapsdoor/phantom/<project_name>`),所有 worker 共用同一目录,通过 `.phantom/state.json` 协调状态,通过文件产物(`*.locked.md`)交接。
- `AIPlan / AIDesign / AIDevTest` 是无状态 worker:**所有持久状态都在工作区里**,worker 只是 phantom CLI 的薄包装,可以随时重启 / 多进程。
- `AIIdea / AIRequirement` 既是 AIJuicer 的 worker 节点,**也是独立的 webapp** —— 可以脱离 AIJuicer 单独通过 Web UI 使用。

## 运行服务

所有子项目(除 `PhantomCLI/`)使用**同一套**服务管理脚本,接口完全统一:

```bash
# 顶层一键管理(推荐)
./scripts/all.sh start                  # 按依赖顺序启动所有服务
./scripts/all.sh stop                   # 反序停止
./scripts/all.sh restart
./scripts/all.sh status                 # 汇总状态
./scripts/all.sh logs AIIdea/backend    # tail 某个服务日志

# 单项目管理(同样接口)
./<Project>/scripts/service.sh start [<svc>|all] [--no-follow]
./<Project>/scripts/service.sh stop    [<svc>|all]
./<Project>/scripts/service.sh restart [<svc>|all] [--no-follow]
./<Project>/scripts/service.sh status
./<Project>/scripts/service.sh logs    <svc>
```

**统一约定:**

| 项 | 位置 |
| --- | --- |
| PID 文件 | `<Project>/.pids/<svc>.pid` |
| 日志文件 | `${LOG_DIR:-/Users/lapsdoor/phantom/logs}/<service-name>-<svc>.log` |
| service-name | `ai-juicer / ai-idea / ai-requirement / ai-plan / ai-design / ai-devtest` |
| 子服务 | AIJuicer: `scheduler webui` · AIIdea: `backend frontend` · AIRequirement: `backend frontend worker` · AIPlan/AIDesign/AIDevTest: `worker` |

**启动顺序**(`scripts/all.sh start` 内置):

1. **AIJuicer** scheduler + webui(中央调度器,必须先起)
2. **Workers**: AIPlan / AIDesign / AIDevTest / AIRequirement worker(连 scheduler 拉任务)
3. **Webapps**: AIIdea / AIRequirement(独立 webapp)

`stop` 反序进行。所有 stop 操作 5s 内 SIGTERM,超时升级 SIGKILL。

## 端口约定(本机开发)

| 服务 | 端口 |
| --- | --- |
| AIJuicer scheduler | 8000 |
| AIJuicer webui | 3000 |
| AIIdea backend | 53839 |
| AIIdea frontend | 53840 |
| AIRequirement backend | 8010 |
| AIRequirement frontend | 3010 |
