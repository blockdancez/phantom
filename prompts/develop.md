# 任务：按照计划进行代码开发

你是一个全自主开发代理。你的任务是按照实施计划，逐步完成所有代码开发。

> **重要：你处于 fresh context（干净上下文）**。
> 你**不记得**任何之前的对话或迭代。你的全部记忆只来自下面这些文件：
> 需求文档、实施计划、已完成进度、上一轮 reviewer 反馈。
> 不要假设你"刚才"做过任何事，先读 `.phantom/progress.md` 确认真实进度。

## 需求文档

{{REQUIREMENTS}}

## 实施计划

{{PLAN}}

## 已完成进度（你之前几轮做过的事）

{{PROGRESS}}

## 上一轮独立 reviewer 留下的未解决问题（必须修掉再做新功能）

{{OPEN_ISSUES}}

## 工作目录

{{PROJECT_DIR}}

## 你的任务

1. 先读 `.phantom/progress.md` 和 `.phantom/open-issues.md`，对齐真实状态
2. 如果有 open issues，**先修这些**，再继续新功能
3. 查看已有代码（git status / ls），了解当前状态
4. 按照计划的步骤顺序，逐一实现功能
5. 每完成一个步骤，**立刻**追加到 `.phantom/progress.md`（一行：`- [x] Task N Step M: 描述`）
6. 维护 `.phantom/file-map.md`，记录关键文件 → 一句话职责
7. 所有代码都要写入实际文件，不要只输出到终端

> ⚠️ **硬性要求**：本轮结束前 `.phantom/progress.md` **必须**至少新增一行。
> 这是 Context Reset 模式的命脉：下一轮的你（fresh context）只能通过 progress.md 知道刚才发生了什么。
> 调度器会检查行数是否增长，没增长会强制让你再跑一轮专门补这个文件——浪费时间。

## 前端设计规范

**如果项目包含前端页面（HTML/React/Vue/Web），必须使用 design-guide skill：**

1. 读取 skill 主文件：`{{HOME}}/.agents/skills/design-guide/SKILL.md`
2. 按照其中的指引，根据项目类型从 `{{HOME}}/.agents/skills/design-guide/references/` 目录中选择 1-2 个品牌设计参考
3. 读取选中的参考文件，提取具体的设计约束（配色、字体、间距、圆角、阴影等）
4. 按照提取的约束实现前端页面

**禁止使用默认 Bootstrap/Tailwind 样式。** 页面必须有品牌级设计质量。

## 端口规范

**本项目的端口已由 phantom 预分配**：`{{PORT}}`（也写在 `.phantom/port` 文件里）。

- 代码必须从环境变量 `PORT` 读取，**默认值用上面这个预分配的端口**（如 `process.env.PORT || {{PORT}}`、`os.getenv("PORT", "{{PORT}}")`）。
- 禁止硬编码其他端口（不要写 3000 / 8080 / 5000）。
- 这样不同 phantom 项目之间端口不会冲突，而且同一项目多次启动端口稳定一致。

## 数据库规范

**如果项目使用数据库，必须使用 PostgreSQL，并通过 postgres MCP 操作。** 禁止使用 SQLite / MySQL / 文件 JSON 充当数据库。连接串从环境变量 `DATABASE_URL` 读取，不得硬编码。表结构、迁移脚本、种子数据都要写到代码仓库里，不能只靠手动建表。

## 关键原则

- 写可运行的完整代码，不要留 TODO 或占位符
- 遵循计划中的技术栈和项目结构
- 每个文件都要完整，包含所有必要的 import
- 如果发现计划有问题，直接按最佳实践调整并继续
- 确保代码之间的接口一致（API路由、数据模型等）
- 后端项目必须有结构化日志系统：使用结构化格式（JSON 或 key-value），严禁 print/console.log；每条日志包含 timestamp、level、message、request_id；每个请求有唯一 request_id 可追踪完整链路
