# Phantom AutoDev

全自主需求开发程序 — 输入需求，自动完成从规划到部署的全流程。支持 Claude Code 和 OpenAI Codex 两种 AI 后端。

## 使用方法

```bash
# 从需求文件启动
./phantom.sh requirements.md

# 直接输入需求文本
./phantom.sh "构建一个Todo API，使用Node.js + Express，端口3000"

# 指定 AI 后端（默认 claude）
./phantom.sh codex requirements.md

# 指定项目输出目录
./phantom.sh requirements.md ./projects/my-app

# 恢复中断的项目
./phantom.sh --resume                # 交互式选择项目
./phantom.sh --resume todo-api       # 指定项目名

# 删除项目
./phantom.sh --delete                # 交互式选择
./phantom.sh --delete todo-api       # 指定项目名
```

## 工作流程

```
输入需求
  │
  ▼
┌─────────────────────────────────┐
│  阶段 1: 规划 (Plan 模式)        │
│  分析需求 → 生成 .phantom/plan.md │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  阶段 2: 开发 (最多 20 轮)       │
│  按计划编写代码                   │
│  ↓                              │
│  验证：安装依赖 → 启动项目 →      │
│  curl 测试端点 → 检查占位符       │
│  ↓                              │
│  通过 → 下一阶段                 │
│  失败 → 修复 → 再次验证          │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  阶段 3: 测试 (最多 10 轮)       │
│  编写单元测试 / Playwright 测试   │
│  ↓                              │
│  运行所有测试 → 分析覆盖率        │
│  ↓                              │
│  全部通过 → 下一阶段             │
│  有失败 → 修复代码 → 重新运行     │
└──────────────┬──────────────────┘
               ▼
┌─────────────────────────────────┐
│  阶段 4: 部署 (最多 3 次)        │
│  创建 Dockerfile →              │
│  docker build → docker run →    │
│  验证服务响应 → 清理容器          │
└──────────────┬──────────────────┘
               ▼
            完成
```

## 核心机制

### 同一会话

所有阶段在同一个 AI 会话中执行。规划阶段启动新会话，后续阶段通过 `-c`（Claude）或 `resume --last`（Codex）接续，AI 自动压缩上下文保持连续性。

### 证据驱动验证

验证不是问 AI "你觉得完成了吗"，而是让它用实际操作证明：

1. 对照需求逐条核对 ✅/❌
2. `grep` 扫描代码中的 TODO/FIXME
3. 安装依赖并启动项目
4. `curl` 逐个端点验证返回值
5. 全部通过才算完成，否则修复后重新验证

### 流式输出

使用 `--output-format stream-json` + `stream-parser.py` 实时显示：
- AI 的文本输出（逐字流式）
- 工具调用（`[tool] $ npm install`、`[tool] Editing src/index.js`）
- 最终结果保存到日志文件供完成状态检测

## 项目结构

```
phantom.sh                  # 主入口：参数解析、状态机驱动
lib/
  utils.sh                  # 日志函数、依赖检查
  state.sh                  # .phantom/state.json 读写
  loop.sh                   # AI 后端抽象层 + 验证循环引擎
  stream-parser.py          # 流式 JSON 解析器（支持 Claude / Codex）
prompts/
  plan.md                   # 规划阶段提示词
  develop.md                # 开发阶段提示词
  verify-dev.md             # 开发验证提示词（5步证据检查）
  test.md                   # 测试阶段提示词
  verify-test.md            # 测试验证提示词
  deploy.md                 # Docker 部署提示词
```

### 运行时生成

每个项目在 `projects/<项目名>/` 下，包含：

```
projects/todo-api/
  .phantom/
    state.json              # 当前阶段、迭代次数、需求文件路径
    plan.md                 # AI 生成的实施计划
    logs/                   # 每轮迭代的日志
  src/                      # AI 生成的项目代码
  Dockerfile
  ...
```

`state.json` 示例：

```json
{
  "requirements_file": "/path/to/requirements.md",
  "project_dir": "/path/to/projects/todo-api",
  "current_phase": "dev",
  "phases": {
    "plan":   { "status": "completed", "iteration": 1 },
    "dev":    { "status": "in_progress", "iteration": 3 },
    "test":   { "status": "pending", "iteration": 0 },
    "deploy": { "status": "pending", "iteration": 0 }
  },
  "started_at": "2026-04-09T04:29:07Z"
}
```

## AI 后端支持

| 功能 | Claude Code | OpenAI Codex |
|------|------------|--------------|
| 执行 | `claude -p` | `codex exec` |
| 跳过权限 | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` |
| 接续会话 | `-c` | `resume --last` |
| Plan 模式 | `--permission-mode plan` | 提示词注入 |
| 流式输出 | `stream-json` | `--json` (JSONL) |

默认使用 Claude，通过第一个参数切换：

```bash
./phantom.sh claude requirements.md   # Claude Code
./phantom.sh codex requirements.md    # OpenAI Codex
./phantom.sh requirements.md          # 默认 Claude
```

## 依赖

- **Claude Code CLI** >= 2.0 或 **OpenAI Codex CLI**（至少安装一个）
- **jq** — JSON 状态管理
- **python3** — 流式输出解析
- **Docker** — 部署阶段
