# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 仓库性质

Phantom 是一个 **聚合仓库**(monorepo),八个子目录是各自独立的项目,不共享构建系统、不共享虚拟环境、不共享依赖。**永远不要在仓库根目录跑命令**,所有开发命令都必须 `cd` 到子项目目录后再运行。子项目之间唯一的耦合是 AIJuicer SDK(其他 agent 作为 worker 接入 AIJuicer 调度器)。

各子项目角色见根目录 `README.md`,这里只列写代码时必须知道的事。

## 统一服务管理

所有子项目(除 `PhantomCLI/`)都用同一套接口:`<Project>/scripts/service.sh {start|stop|restart|status|logs} [<svc>|all] [--no-follow]`。根目录 `./scripts/all.sh` 是一键编排器(按依赖顺序起停)。共享逻辑在 `scripts/lib/service-lib.sh`,**修改启停行为务必改 lib,不要在子项目里偏离接口**。
- PID 文件:`<Project>/.pids/<svc>.pid`
- 日志文件:`${LOG_DIR:-/Users/lapsdoor/phantom/logs}/<service-name>-<svc>.log`
- 子服务列表:见各 `service.sh` 顶部的 `SERVICES=(...)` 数组

## 子项目分层与协作

```
            (顶层编排)
   AIJuicer (FastAPI :8000 + Next.js webui)  ← 6 步固定流水线状态机
        │ Redis Streams 任务队列(每 step 一个 stream + consumer group)
        ▼
   ┌────────────┬─────────────┬─────────────┬─────────────┐
 AIIdea      AIRequirement   AIPlan      AIDesign    AIDevTest
 (完整 webapp) (完整 webapp)   ↑           ↑             ↑
  + worker     + worker     phantom CLI 的 SDK 薄包装(三者结构高度相似)
                              │
                              ▼
                          PhantomCLI/phantom.sh
                          (bash 编排 Claude Code / Codex CLI)
                              │
                              ▼
                       目标项目工作区
                       /Users/lapsdoor/phantom/<project_name>/
```

**关键不变量:**
- `AIPlan / AIDesign / AIDevTest` 是 **无状态 worker**,工作区状态全部存在目标项目的 `.phantom/` 目录里(`state.json`、`plan.locked.md`、`design.locked.md` 等),worker 只是把 phantom CLI 包了一层
- 这三个 worker 的判重逻辑 **不看 `ctx.attempt`**,看 `workspace_has_phantom_state()` —— 修改它们时务必保持这个原则
- phantom 子进程的 cwd **必须** 是项目目录(`PHANTOM_PROJECTS_BASE / project_name`,默认 `/Users/lapsdoor/phantom`),不是 agent 自己的目录
- phantom CLI 的 `rc=0` **不等于成功**,必须额外校验产物文件(如 `.phantom/plan.locked.md`)是否存在
- 失败分类:agent 内部 `_RETRYABLE_PATTERNS` 和 `_FATAL_PATTERNS` 是约定,新增错误模式时同步两份

## 子项目常用命令

每个子项目有自己的 README/CLAUDE.md 给出完整说明,这里只列高频入口。**单测/lint 命令一律在该子项目目录内执行**。

### AIJuicer(中央调度器,Python 3.12 + Node 20)
```bash
make install          # 装后端 + SDK
make migrate          # 建表
bash scripts/service.sh start   # 起 scheduler(:8000) + webui;或在根目录 `./scripts/all.sh start` 一键起所有服务
make test             # pytest;默认用 testcontainers,可设 TEST_DATABASE_URL 重用本地 PG
pytest scheduler/tests/test_state_machine.py::test_xxx -v   # 单条测试
```

### AIIdea(完整 webapp,FastAPI + Next.js)
```bash
cp .env.example .env                  # 必须填 OPENAI_API_KEY 等
./scripts/service.sh start backend            # uvicorn :53839
./scripts/service.sh start frontend           # vite :53840
cd backend && pytest                  # 后端 143 条测试
pytest tests/test_api/test_xxx.py::test_yyy -v
```

### AIRequirement(完整 webapp + AIJuicer worker,FastAPI + React)
```bash
cd backend && pip install -r requirements.txt
./scripts/service.sh start backend     # uvicorn :8010
./scripts/service.sh start frontend    # vite :3010
./scripts/service.sh start worker      # AIJuicer 节点
```

### AIPlan / AIDesign / AIDevTest(phantom 包装 worker,结构相同)
```bash
pip install -e '.[dev]'
pytest -v                              # 单测
pytest tests/test_agent.py::test_xxx -v
./scripts/service.sh start             # 后台启 worker(连 AIJuicer scheduler)
./scripts/service.sh status            # 查看 worker 状态
./scripts/service.sh logs worker       # tail 日志
```

### PhantomCLI(phantom CLI 主入口,Bash + Python)
```bash
bash install.sh                                # 软链到 /usr/local/bin/phantom
phantom requirements.md                        # 全流程跑
phantom --plan "<增量需求>"                     # 只跑 plan 阶段(可重入)
phantom --design "<UI 调整>"                    # 只跑 design 阶段
phantom --dev-test "<bugfix>"                  # dev → code-review → deploy → test
phantom --resume [project]                     # 失败恢复
```
phantom.sh 不是普通 CLI,而是 bash 写的 **AI agent 状态机**,内部 fork Claude Code 或 OpenAI Codex CLI。修改 phantom.sh 时注意:
- 可机械化的判断(产物存在性、grep 关键字、HTTP 状态码、端口就绪)**全部由 shell 完成**,绝不交给 AI 主观判断
- plan_reviewer / code_reviewer / tester 强制选与 generator 不同的后端模型(打破"同模型自检"盲区),改任何调度逻辑时务必保留这个约束
- prompts 在 `prompts/`,7 个 Markdown 文件分别对应 plan / ui-design / develop / code-review / deploy / test / requirements

## 工作区与端口约定

- **目标项目根目录**:`/Users/lapsdoor/phantom/<project_name>/`(`PHANTOM_PROJECTS_BASE` 可覆盖)
- **AIIdea 端口**:后端 53839、前端 53840(写死在 `.phantom/port.*`)
- **AIRequirement 端口**:后端 8010、前端 3010
- **AIJuicer 端口**:scheduler 8000、webui 默认 3000

## 修改注意事项

- **`.env` 永不入仓**(根 `.gitignore` 已统一排除),只提交 `.env.example`
- 各子项目的 Python 虚拟环境 `.venv/` 各自独立,不要假设它们共享依赖版本
- AIJuicer 的状态机有 18 个状态(6 step × 3 phase),改流转时改 `scheduler/engine/state_machine.py` **必须** 同时更新单测
- AIIdea / AIRequirement 在 rerun 时是 **删旧 Document 后重建**,不是 update —— 改 rerun 逻辑时不要改成 in-place update,会破坏一对一关系约束
