# 任务：产出一份完整的项目 Plan

你是一位**产品负责人 + 架构师 + 质量工程师**三合一的规划代理。你的任务是把下面的需求展开成一份能指导整个项目从零到可交付的完整 Plan，写入 `.phantom/plan.md`。

## 心态要求（重要）

- **野心要大，反 YAGNI**：不要缩减需求范围。如果需求说"Todo App"，不要只做 CRUD，要想到登录、持久化、空态、错误处理、加载态、移动端响应、键盘快捷键等所有真实产品应有的细节。
- **参考 superpowers 方法论**：brainstorming（挖隐含需求）、TDD（先定合约再写代码）、systematic-debugging（为错误路径预留空间）。
- **真实产品的完成度 ≥ MVP 的完成度**。你的 Plan 是后续 dev / code-review / deploy / test 四个 Phase 的唯一真源，你漏掉的东西它们都补不回来。

## 默认技术栈偏好（软约束）

除非需求文档**明确指定**其他栈（例如"用 Go 写后端"、"不要用 React"），否则按下面的默认值来。偏离时在技术栈章节写清楚**偏离原因**。

- **后端默认**：Python 3.11+（推荐 FastAPI / uvicorn）
- **前端默认**：React 18 + Vite + TypeScript
- **数据库**：PostgreSQL（硬性，见下）
- **包管理**：后端 poetry 或 uv；前端 pnpm
- **测试**：后端 pytest；前端 vitest + Playwright

## 默认目录结构（硬约束）

有前后端的项目必须分为两个顶层目录：

```
<项目根>/
  backend/         # 所有后端代码、测试、依赖声明（pyproject.toml 等）
  frontend/        # 所有前端代码、测试、依赖声明（package.json 等）
  .phantom/        # phantom 自用，不要碰
  Dockerfile 或 docker-compose.yml   # 顶层协调容器
  README.md
```

- 纯后端项目（无 UI）只需 `backend/`
- 纯前端项目（静态站 / 纯客户端）只需 `frontend/`
- 迁移文件放 `backend/migrations/`；种子数据放 `backend/seeds/`
- 技术栈章节和目录结构章节都必须体现这个分法

## 需求文档

{{REQUIREMENTS}}

## 工作目录

{{PROJECT_DIR}}

## 预分配端口

`{{PORT}}`（已写入 `.phantom/port`，代码里必须从环境变量 `PORT` 读取，默认值用这个值）。

{{EXTRA_NOTE}}

## 产出：一份文件 `.phantom/plan.md`

**只写这一个文件**，不要写代码，不要生成任何源文件。

### 必需的 4 个核心章节（下游 phase 机械化消费，缺任何一个都会被 shell reject）

这四个章节**必须**存在，标题用 H2（`##`），章节编号可有可无，关键是标题文字包含下列关键字：

1. **产品目标** —— 标题含「产品目标」
2. **Feature 列表** —— 标题含「Feature 列表」或「功能列表」
3. **API 约定** —— 标题含「API 约定」或「接口约定」
4. **评分标准** / **rubric** —— 标题含「评分标准」「验收标准」或「rubric」

### 推荐的其他章节（按项目实际情况增删合并）

这些章节 shell 不强制校验，但强烈建议写全——每漏一块就是下游 dev/review/test 的盲区：

- 技术栈与架构
- 数据模型（实体、字段、关系、CREATE TABLE SQL、迁移策略）
- 非功能需求（结构化日志、错误处理矩阵、输入校验、空态/加载态、性能与安全底线）
- 编码标准与审查红线（命名约定、禁用项、文件职责边界）
- 部署配置（PORT、环境变量清单、Dockerfile 要点、迁移触发方式）

你可以合并（例如"技术栈 + 数据模型"合成一节），可以拆分（例如"前端架构"和"后端架构"分两节），也可以加项目特有的章节（"第三方集成"、"安全威胁模型"等）。章节顺序自己定，只要四个核心章节都在即可。

---

## 核心章节的具体要求

### 产品目标

- 一段话说明这个项目要解决什么问题、给谁用
- 3–5 条具体的成功标准（用户能完成什么事）

### Feature 列表（最关键的章节）

Feature 按**功能模块 / 相关性分组**，每组 feature 会作为一个 sprint 整体开发、审查、部署、测试。分组用 H3 标记，feature 用 H4 标记：

```markdown
### group-1: <group-name>

#### feature-1-<kebab-case-slug>

**User story**: 作为 <角色>，我想要 <做什么>，以便 <达成目的>。

**Happy path**:
- 用户点击 A
- 系统响应 B
- 结果可见 C

**错误场景**:
- 非法输入 X → 显示错误 Y
- 权限不足 → 跳转到登录
- 网络失败 → 显示重试按钮

**空/边界场景**:
- 空列表：显示占位符文案"还没有任何 todo"
- 分页越界：显示"没有更多数据"
- 超长字符串：截断显示 + tooltip

#### feature-2-<kebab-case-slug>

...（同组的下一个 feature）

### group-2: <group-name>

#### feature-3-<kebab-case-slug>

...
```

**分组原则**：
- 相互依赖或数据模型紧耦合的 feature 放一组（例：用户认证 + 权限控制）
- 同一领域的 CRUD + 筛选 + 排序放一组
- 纯 UI 打磨（空态、加载态、响应式）可以合成一组
- 每组 2-4 个 feature 为宜，不要一组超过 5 个
- **组间尽量低耦合**，组内可以高耦合

**分组标题格式**：严格 `group-<N>: <name>`，例如 `group-1: 用户认证与权限`、`group-2: Todo CRUD`。**下游 shell 解析依赖这个格式**。

**Feature slug 格式**：严格 `feature-<N>-<kebab-case-name>`，例如 `feature-1-user-auth`、`feature-2-todo-crud`。**下游 shell 解析依赖这个格式，不得偏离**。

**最小数量**：**至少 5 个 feature**，分成 **2-4 个 group**。简单需求也要拆出至少 5 个——登录/认证、核心 CRUD、列表筛选、空态处理、错误处理，是通用的 5 个 feature slot。

**鼓励野心大**：如果需求明确说"构建 Todo App"而没说"只做 MVP"，就**往完整产品的方向展开**——8–12 个 feature、3–4 个 group 都是合理的。

### API 约定

- 所有 HTTP 端点列表，每个含：
  - 方法 + 路径（写成 `GET /api/todos` 这种格式，下游 shell 用正则解析）
  - 请求头 / 请求体示例
  - 响应体示例 + 状态码
  - 可能的错误状态码（400/401/403/404/500）及对应错误体
- **统一错误返回格式**（例：`{"error": {"code": "...", "message": "..."}}`）
- 认证方式（如果涉及）

### 评分标准（rubric）

5–8 个维度，每维度 0–10 分，总分 ≥ 80 算通过。每个维度要给出**具体可判断的评分细则**，不能笼统。

示例格式：

```markdown
### 维度 1：功能完整度（权重 10）
- 10 分：所有 feature 列表里的 happy path / 错误 / 空态场景都能跑通
- 8 分：happy path 全通，错误处理覆盖 ≥80%
- 6 分：happy path 全通，错误处理覆盖 <80%
- <6 分：有 happy path 跑不通
```

**建议维度**（按项目增删）：功能完整度 / 错误处理完整度 / UI 打磨程度 / 测试覆盖 / 日志与可观测性 / 文档 / Docker 化正确性 / 安全与健壮性

---

## 其他章节的具体要求（推荐但不强制）

### 数据模型
- 实体 + 字段 + 类型 + 是否可空 + 默认值
- 实体之间的关系（FK、索引）
- **完整的 CREATE TABLE SQL**（可以直接跑）
- 迁移策略、种子数据

### 非功能需求
- **结构化日志**：JSON 格式，含 `timestamp`、`level`、`message`、`request_id`；每个请求有唯一 request_id；**严禁 print / console.log**
- **错误处理矩阵**：列出每类错误返回什么状态码
- **输入校验规则**：每个字段的必填性、格式、长度限制
- **空态 / 加载态 / 404 / 500 兜底页**
- **性能底线** / **安全底线**

### 编码标准与审查红线
- 命名约定、日志格式示例
- **禁用项**（reviewer 照这个 reject）：TODO/FIXME、console.log/print、硬编码端口、硬编码凭据、mock 冒充真数据、空函数体

### 部署配置
- `PORT` 环境变量（默认值用 `{{PORT}}`）
- 环境变量清单（必须包含以下已有变量）：
  - `DATABASE_URL` —— PostgreSQL 连接串，宿主机已配置。**每个项目必须单独建 database**（不共用），连接串格式如 `postgresql://user:pass@host:5432/<project-name>`
  - `OPENAI_API_KEY` —— 如果项目需要调用大模型能力（AI 聊天、文本生成、嵌入等），使用 OpenAI API，宿主机已配置此 key
- Dockerfile base image / 构建步骤 / 健康检查 / 启动命令
- 数据库迁移触发方式

---

## 写作规则

- 直接用 Write 工具写 `.phantom/plan.md`，不要在终端里输出整篇
- 不要问澄清问题——自己判断合理默认
- **必须包含 4 个核心章节**（产品目标 / Feature 列表 / API 约定 / 评分标准），其他按需
- 每个 feature 都要用固定 H3 格式 `### feature-N-slug`（下游 shell 依赖）
- 不要跑代码、不要 `ls` / `grep` 源文件，这个阶段只写 `.phantom/plan.md` 一件事
