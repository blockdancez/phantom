# 实施计划

## 技术栈
- **运行时**: Node.js
- **Web 框架**: Express.js
- **日志系统**: winston（结构化日志，满足可观测性、可搜索性、可分析性要求）
- **UUID 生成**: crypto.randomUUID()（Node.js 内置）
- **数据存储**: 内存存储（Map）
- **容器化**: Docker

## 项目结构
```
test-project/
├── package.json          # 项目依赖与脚本
├── Dockerfile            # Docker 容器配置
├── .dockerignore         # Docker 忽略文件
├── src/
│   ├── app.js            # Express 应用配置与中间件
│   ├── server.js         # 服务器启动入口
│   ├── routes/
│   │   └── todos.js      # Todo 路由定义
│   ├── store/
│   │   └── todoStore.js  # 内存数据存储层
│   └── logger.js         # 结构化日志配置
└── .phantom/
    └── plan.md           # 本实施计划
```

## 实施步骤

### 步骤 1: 项目初始化
- 创建 `package.json`，定义项目名称、版本、入口、脚本（`start`、`dev`）及依赖（`express`、`winston`）
- 安装依赖：`npm install`

### 步骤 2: 日志系统 (`src/logger.js`)
- 使用 winston 创建结构化日志记录器
- 输出格式：JSON（便于搜索和分析）
- 包含时间戳、日志级别、消息、上下文信息
- 控制台输出，方便本地开发和容器日志收集

### 步骤 3: 内存存储层 (`src/store/todoStore.js`)
- 使用 Map 作为内存存储
- 封装 CRUD 方法：
  - `getAll()` — 返回所有 todo
  - `getById(id)` — 按 ID 查询单个 todo
  - `create(title)` — 创建新 todo，自动生成 uuid、设置 completed=false、记录 created_at
  - `update(id, data)` — 更新 todo 的 title 和/或 completed
  - `remove(id)` — 删除 todo，返回是否成功

### 步骤 4: 路由定义 (`src/routes/todos.js`)
- `GET /todos` — 调用 store.getAll()，返回 200 + todo 列表
- `POST /todos` — 校验 title 必填，调用 store.create()，返回 201 + 新 todo
- `GET /todos/:id` — 调用 store.getById()，找到返回 200，未找到返回 404
- `PUT /todos/:id` — 调用 store.update()，找到返回 200 + 更新后的 todo，未找到返回 404
- `DELETE /todos/:id` — 调用 store.remove()，成功返回 204，未找到返回 404
- 每个接口调用 logger 记录请求信息

### 步骤 5: 应用配置 (`src/app.js`)
- 创建 Express 实例
- 注册 `express.json()` 中间件解析 JSON 请求体
- 注册请求日志中间件（记录 method、url、状态码、响应时间）
- 挂载 `/todos` 路由
- 导出 app 实例

### 步骤 6: 服务器启动 (`src/server.js`)
- 引入 app 实例
- 监听端口 3000
- 启动日志输出

### 步骤 7: Docker 配置
- 创建 `Dockerfile`：基于 `node:20-alpine`，复制代码，安装生产依赖，暴露 3000 端口，启动服务
- 创建 `.dockerignore`：排除 `node_modules`、`.git`、`.phantom`

### 步骤 8: 验证测试
- 启动服务，使用 curl 逐一测试 5 个接口
- 确认返回格式、状态码、日志输出均符合预期
