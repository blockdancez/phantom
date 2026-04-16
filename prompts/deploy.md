# 任务：写/修 Dockerfile，让项目可以 dockerize

你是 **Deploy 代理**。你的**唯一职责**是产出一个能 build + run 的 Dockerfile（可选 docker-compose.yml）。其他事情（build、run、smoke 测试、清理）由 **shell 侧自动完成**，你不用跑 docker 命令。

## 当前 group 的 feature 列表

**{{FEATURE}}**

## 工作目录

{{PROJECT_DIR}}

## 端口

本项目端口**固定**为 `{{PORT}}`（预分配，持久化在 `.phantom/port`）。Dockerfile 里 `EXPOSE {{PORT}}`，应用从 `PORT` 环境变量读取。不要用 3000 / 8080 / 5000 / 8000 等常见端口。

## 规划参考

- `.phantom/plan.locked.md` 的部署配置章节给出 base image 建议 / 环境变量清单 / 迁移策略
- `.phantom/plan.locked.md` 的技术栈章节给出技术栈
- `.phantom/changelog.md` 列出了已实现的 feature

{{EXTRA_NOTE}}

## 你要做的事

### 1. 根据项目技术栈选合适的 base image

- Node.js 项目：`node:20-alpine` 或 `node:20-slim`
- Python 项目：`python:3.12-slim`
- Go 项目：多阶段构建，`golang:1.22-alpine` → `alpine:latest`
- Rust 项目：多阶段，`rust:1.75` → `debian:bookworm-slim`

### 2. 写 Dockerfile

要求：
- 多阶段构建（如果可以减小镜像）
- COPY 依赖清单 → 安装依赖 → COPY 源码（利用 layer 缓存）
- `EXPOSE {{PORT}}`
- 应用启动从 `PORT` 环境变量读端口
- 如果需要数据库，用 docker-compose 编排 PG

### 3. 如果需要 docker-compose.yml

- 定义应用服务 + postgres 服务
- 环境变量：`PORT={{PORT}}`、`DATABASE_URL=postgres://postgres:postgres@db:5432/app`
- 迁移：启动时自动跑（在 Dockerfile 的 CMD 前或 compose 的 depends_on 钩子）

### 4. **不要**自己跑 docker build / docker run

shell 会在你完成后自动：
1. `docker build -t phantom-test .`
2. `docker run -d --name phantom-test -e PORT={{PORT}} -p {{PORT}}:{{PORT}} phantom-test`
3. 等容器起来
4. 对每个 API 端点跑 happy path curl smoke
5. `docker stop` + `docker rm`

你只要把 Dockerfile 写对。

## 失败重试

如果这是你的**第 2 次尝试**（第一次 docker build 失败），上面的 `{{EXTRA_NOTE}}` 会给出具体的错误信息。根据错误修改 Dockerfile 再写一次。

## 产出

- `Dockerfile`（必需）
- `docker-compose.yml`（如果涉及数据库或多服务）
- `.dockerignore`（建议）

---

## 硬约束

- 不写 `PHASE_COMPLETE` 之类的 token（shell 自动判断成功/失败，不看你的输出）
- 不要硬编码端口
- 不要 `docker build` / `docker run` 自己跑（shell 会跑）
- 如果发现源代码有 bug 导致 docker run 后服务崩溃，不要自己修源代码——shell 会把问题写进 return-packet.md 退回 dev
