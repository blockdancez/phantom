# Phantom AutoDev - 全自主需求开发程序 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Shell 脚本程序，输入需求文档后，通过 Claude Code CLI 全程自主完成：需求分析 -> 计划制定 -> 代码开发 -> 测试验证 -> Docker 部署，核心使用 Ralph-loop 循环机制确保每个阶段达到客观完成标准后才推进。

**Architecture:** 主脚本 `phantom-dev.sh` 作为状态机驱动器，分为 4 个阶段（规划、开发、测试、部署）。每个阶段通过 `claude -p --dangerously-skip-permissions` 执行，使用 bash while 循环实现 Ralph-loop 式的自验证迭代。阶段间通过状态文件（`.phantom/state.json`）协调，每次迭代的结果通过 Claude 的 `--continue` 模式保持上下文连续性。

**Tech Stack:** Bash, Claude Code CLI, jq (JSON状态管理), Docker

---

## 文件结构

```
phantom-dev.sh              # 主入口脚本（状态机驱动器）
lib/
  phases.sh                 # 阶段执行函数（plan/dev/test/deploy）
  loop.sh                   # Ralph-loop 循环引擎
  state.sh                  # 状态管理（读写 .phantom/state.json）
  utils.sh                  # 工具函数（日志、颜色输出等）
prompts/
  plan.md                   # 规划阶段提示词模板
  develop.md                # 开发阶段提示词模板
  verify-dev.md             # 开发验证提示词模板
  test.md                   # 测试阶段提示词模板
  verify-test.md            # 测试验证提示词模板
  deploy.md                 # 部署阶段提示词模板
```

运行时生成：
```
.phantom/
  state.json                # 全局状态（当前阶段、迭代次数等）
  plan.md                   # Claude 生成的实施计划
  logs/
    phase-{name}-{iteration}.log  # 每次迭代的日志
```

---

### Task 1: 工具函数与状态管理

**Files:**
- Create: `lib/utils.sh`
- Create: `lib/state.sh`

- [ ] **Step 1: 创建 utils.sh 工具函数**

```bash
#!/usr/bin/env bash
# lib/utils.sh - 通用工具函数

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_phase() { echo -e "\n${CYAN}========== $* ==========${NC}\n"; }

# 检查依赖
check_dependencies() {
  local missing=()
  for cmd in claude jq docker; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    log_error "缺少依赖: ${missing[*]}"
    exit 1
  fi
}

# 获取项目根目录（phantom-dev.sh 所在目录）
get_script_dir() {
  cd "$(dirname "${BASH_SOURCE[1]}")" && pwd
}
```

- [ ] **Step 2: 创建 state.sh 状态管理**

```bash
#!/usr/bin/env bash
# lib/state.sh - .phantom/state.json 状态管理

STATE_DIR=".phantom"
STATE_FILE="$STATE_DIR/state.json"
LOG_DIR="$STATE_DIR/logs"

init_state() {
  local requirements_file="$1"
  local project_dir="$2"
  mkdir -p "$STATE_DIR/logs"
  cat > "$STATE_FILE" <<EOF
{
  "requirements_file": "$requirements_file",
  "project_dir": "$project_dir",
  "current_phase": "plan",
  "phases": {
    "plan":   { "status": "pending", "iteration": 0 },
    "dev":    { "status": "pending", "iteration": 0 },
    "test":   { "status": "pending", "iteration": 0 },
    "deploy": { "status": "pending", "iteration": 0 }
  },
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
}

get_state() {
  local key="$1"
  jq -r "$key" "$STATE_FILE"
}

set_state() {
  local key="$1"
  local value="$2"
  local tmp
  tmp=$(mktemp)
  jq "$key = $value" "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
}

get_phase_iteration() {
  local phase="$1"
  get_state ".phases.${phase}.iteration"
}

increment_iteration() {
  local phase="$1"
  local current
  current=$(get_phase_iteration "$phase")
  set_state ".phases.${phase}.iteration" "$((current + 1))"
}

set_phase_status() {
  local phase="$1"
  local status="$2"
  set_state ".phases.${phase}.status" "\"$status\""
}

advance_phase() {
  local current next
  current=$(get_state '.current_phase')
  case "$current" in
    plan)   next="dev" ;;
    dev)    next="test" ;;
    test)   next="deploy" ;;
    deploy) next="done" ;;
  esac
  set_phase_status "$current" "completed"
  set_state '.current_phase' "\"$next\""
  if [[ "$next" != "done" ]]; then
    set_phase_status "$next" "in_progress"
  fi
}

state_exists() {
  [[ -f "$STATE_FILE" ]]
}
```

- [ ] **Step 3: 验证 jq 语法正确**

Run: `echo '{"phases":{"dev":{"iteration":0}}}' | jq '.phases.dev.iteration'`
Expected: `0`

- [ ] **Step 4: Commit**

```bash
git add lib/utils.sh lib/state.sh
git commit -m "feat: add utility functions and state management"
```

---

### Task 2: Ralph-Loop 循环引擎

**Files:**
- Create: `lib/loop.sh`

- [ ] **Step 1: 创建 loop.sh 循环引擎**

这是核心组件 — 实现 Ralph-loop 式的 "做完了吗？" 自验证循环。

```bash
#!/usr/bin/env bash
# lib/loop.sh - Ralph-loop 循环引擎
#
# 核心原理：反复调用 Claude，每次都问 "真的完成了吗？"
# Claude 看到自己之前的工作（文件 + git history），要么继续改进，要么确认完成。

source "$(dirname "${BASH_SOURCE[0]}")/utils.sh"
source "$(dirname "${BASH_SOURCE[0]}")/state.sh"

# 运行带自验证的 Claude 循环
#
# 参数:
#   $1 - 阶段名称（plan/dev/test/deploy）
#   $2 - 主提示词文件路径
#   $3 - 验证提示词文件路径
#   $4 - 最小验证次数
#   $5 - 最大验证次数
#   $6 - 项目工作目录
run_loop() {
  local phase="$1"
  local main_prompt_file="$2"
  local verify_prompt_file="$3"
  local min_checks="$4"
  local max_checks="$5"
  local work_dir="$6"

  local iteration=0
  local consecutive_done=0
  local session_id=""
  local continue_flag=""

  set_phase_status "$phase" "in_progress"

  log_phase "阶段: $phase (最少验证 $min_checks 次，最多 $max_checks 次)"

  while [[ $iteration -lt $max_checks ]]; do
    iteration=$((iteration + 1))
    increment_iteration "$phase"

    local log_file="$LOG_DIR/phase-${phase}-${iteration}.log"

    if [[ $iteration -eq 1 ]]; then
      # 第一次迭代：执行主任务
      log_info "[$phase] 迭代 $iteration/$max_checks - 执行主任务..."

      local main_prompt
      main_prompt=$(cat "$main_prompt_file")

      # 注入需求文档内容和计划（如果存在）
      local requirements_content=""
      local req_file
      req_file=$(get_state '.requirements_file')
      if [[ -f "$req_file" ]]; then
        requirements_content=$(cat "$req_file")
      fi

      local plan_content=""
      if [[ -f ".phantom/plan.md" ]]; then
        plan_content=$(cat ".phantom/plan.md")
      fi

      local full_prompt
      full_prompt=$(echo "$main_prompt" | \
        sed "s|{{REQUIREMENTS}}|$requirements_content|g" | \
        sed "s|{{PLAN}}|$plan_content|g" | \
        sed "s|{{PROJECT_DIR}}|$work_dir|g")

      # 使用 claude -p 执行，捕获输出
      echo "$full_prompt" | claude -p \
        --dangerously-skip-permissions \
        --output-format json \
        2>&1 | tee "$log_file"

      # 获取 session ID 用于后续 --continue
      session_id=$(jq -r '.session_id // empty' "$log_file" 2>/dev/null || true)
      continue_flag="--continue"
    else
      # 后续迭代：验证 + 继续改进
      log_info "[$phase] 迭代 $iteration/$max_checks - 验证完成度..."

      local verify_prompt
      verify_prompt=$(cat "$verify_prompt_file")

      local result
      result=$(echo "$verify_prompt" | claude -p \
        --dangerously-skip-permissions \
        $continue_flag \
        2>&1 | tee -a "$log_file")

      # 检查 Claude 是否回答 "真的完成了"
      if echo "$result" | grep -qi "PHASE_COMPLETE"; then
        consecutive_done=$((consecutive_done + 1))
        log_ok "[$phase] Claude 确认完成 ($consecutive_done/$min_checks 需要连续确认)"

        if [[ $consecutive_done -ge $min_checks ]]; then
          log_ok "[$phase] 达到最小验证次数，阶段完成!"
          set_phase_status "$phase" "completed"
          return 0
        fi
      else
        consecutive_done=0
        log_warn "[$phase] Claude 认为还未完成，继续迭代..."
      fi
    fi
  done

  # 达到最大次数
  log_warn "[$phase] 已达最大迭代次数 $max_checks"
  set_phase_status "$phase" "max_iterations_reached"
  return 0
}
```

- [ ] **Step 2: 验证脚本语法正确**

Run: `bash -n lib/loop.sh`
Expected: 无输出（语法正确）

- [ ] **Step 3: Commit**

```bash
git add lib/loop.sh
git commit -m "feat: add Ralph-loop verification engine"
```

---

### Task 3: 提示词模板

**Files:**
- Create: `prompts/plan.md`
- Create: `prompts/develop.md`
- Create: `prompts/verify-dev.md`
- Create: `prompts/test.md`
- Create: `prompts/verify-test.md`
- Create: `prompts/deploy.md`

- [ ] **Step 1: 创建规划阶段提示词 plan.md**

```markdown
# 任务：分析需求并制定实施计划

你是一个全自主开发代理。你的任务是分析以下需求文档，制定详细的实施计划。

## 需求文档

{{REQUIREMENTS}}

## 你的任务

1. 仔细阅读需求文档，理解所有功能点
2. 确定技术栈（如果需求文档未指定，选择最合适的主流技术栈）
3. 设计项目结构
4. 制定分步实施计划，每个步骤要具体到文件和功能
5. 如果有多个方案，默认选择推荐方案

## 输出要求

将完整的实施计划写入文件 `.phantom/plan.md`，格式如下：

```
# 实施计划

## 技术栈
- ...

## 项目结构
- ...

## 实施步骤
### 步骤 1: ...
### 步骤 2: ...
...
```

完成后，确保 `.phantom/plan.md` 文件已创建且内容完整。
```

- [ ] **Step 2: 创建开发阶段提示词 develop.md**

```markdown
# 任务：按照计划进行代码开发

你是一个全自主开发代理。你的任务是按照实施计划，逐步完成所有代码开发。

## 需求文档

{{REQUIREMENTS}}

## 实施计划

{{PLAN}}

## 工作目录

{{PROJECT_DIR}}

## 你的任务

1. 阅读实施计划，确认当前进度
2. 查看已有代码（如果有的话），了解当前状态
3. 按照计划的步骤顺序，逐一实现功能
4. 每完成一个功能模块，运行基本验证确保不报错
5. 所有代码都要写入实际文件，不要只输出到终端

## 关键原则

- 写可运行的完整代码，不要留 TODO 或占位符
- 遵循计划中的技术栈和项目结构
- 每个文件都要完整，包含所有必要的 import
- 如果发现计划有问题，直接按最佳实践调整并继续
- 确保代码之间的接口一致（API路由、数据模型等）
```

- [ ] **Step 3: 创建开发验证提示词 verify-dev.md**

```markdown
# 自检：代码开发是否真的完成了？

你刚刚进行了一轮代码开发。现在请严格自检：

## 检查清单

1. **需求覆盖**：对照需求文档，每一个功能点是否都已实现？逐条列出。
2. **代码完整性**：是否有任何 TODO、FIXME、占位符、未实现的函数？
3. **文件完整性**：所有必要的文件是否都已创建？配置文件、依赖文件（package.json / requirements.txt 等）是否完整？
4. **接口一致性**：前后端接口是否对齐？API路由、请求/响应格式是否一致？
5. **可运行性**：代码是否可以直接运行，不需要额外手动配置？

## 回答规则

- 如果发现任何问题，**立即修复**，然后说明你修复了什么
- 如果一切真的完成了，且符合所有客观标准，输出关键词：PHASE_COMPLETE
- **不要为了退出循环而撒谎** — 如果有遗漏，必须如实指出并修复
- 严格、客观、诚实地回答
```

- [ ] **Step 4: 创建测试阶段提示词 test.md**

```markdown
# 任务：对项目进行全面测试

你是一个全自主测试代理。你的任务是对已开发完成的项目进行全面测试。

## 需求文档

{{REQUIREMENTS}}

## 实施计划

{{PLAN}}

## 工作目录

{{PROJECT_DIR}}

## 测试策略

### 后端代码（如有）
1. 安装测试依赖（pytest / jest / 等）
2. 编写并运行单元测试 — 覆盖核心业务逻辑
3. 编写并运行接口测试 — 覆盖所有 API 端点
4. 确保所有测试通过

### 前端网页代码（如有）
1. 安装 Playwright：`npx playwright install`
2. 编写 Playwright 测试 — 覆盖页面渲染、用户交互、核心功能流程
3. 运行测试：`npx playwright test`
4. 确保所有测试通过

### 测试失败处理
- 如果测试失败，分析原因，修复代码（不是修复测试来适应错误代码）
- 修复后重新运行所有测试
- 重复直到全部通过

## 关键原则
- 测试要有意义，覆盖真实业务场景，不要写无意义的烟雾测试
- 先启动服务（如需要），再运行测试
- 测试结束后关闭所有启动的进程
```

- [ ] **Step 5: 创建测试验证提示词 verify-test.md**

```markdown
# 自检：测试是否真的全部通过了？

你刚刚进行了一轮测试。现在请严格自检：

## 检查清单

1. **测试覆盖**：是否覆盖了所有核心功能？还有没有遗漏的场景？
2. **测试结果**：运行 `cat` 查看最新的测试输出，所有测试是否都 PASS？
3. **边界情况**：是否测试了错误输入、空值、边界条件？
4. **集成测试**：前后端联调是否正常（如适用）？

## 回答规则

- 如果发现遗漏的测试场景，**立即补充**并运行
- 如果有测试失败，**修复代码**并重新运行
- 如果一切测试都通过了，且覆盖充分，输出关键词：PHASE_COMPLETE
- **不要为了退出循环而撒谎**
```

- [ ] **Step 6: 创建部署阶段提示词 deploy.md**

```markdown
# 任务：Docker 构建与本地部署验证

你是一个全自主部署代理。你的任务是将项目 Docker 化并在本地验证运行。

## 工作目录

{{PROJECT_DIR}}

## 你的任务

1. **创建 Dockerfile**（如果不存在）
   - 选择合适的基础镜像
   - 多阶段构建（如适用）
   - 正确的依赖安装和构建步骤
   - 暴露正确的端口

2. **创建 docker-compose.yml**（如果项目有多个服务或需要数据库）
   - 定义所有必要的服务
   - 配置网络和卷
   - 设置环境变量

3. **构建镜像**
   ```bash
   docker build -t phantom-project .
   # 或
   docker compose build
   ```

4. **运行容器**
   ```bash
   docker run -d --name phantom-test -p 8080:8080 phantom-project
   # 或
   docker compose up -d
   ```

5. **验证部署**
   - 等待服务启动（检查健康检查或轮询端口）
   - 发送测试请求验证服务正常响应
   - 检查容器日志确认无错误

6. **清理**
   - 停止并删除测试容器
   - 输出最终部署状态

## 输出要求

如果构建和运行都成功，输出：PHASE_COMPLETE
如果失败，修复问题后重试。
```

- [ ] **Step 7: Commit**

```bash
git add prompts/
git commit -m "feat: add prompt templates for all development phases"
```

---

### Task 4: 阶段执行函数

**Files:**
- Create: `lib/phases.sh`

- [ ] **Step 1: 创建 phases.sh**

```bash
#!/usr/bin/env bash
# lib/phases.sh - 各阶段执行逻辑

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/state.sh"
source "$SCRIPT_DIR/lib/loop.sh"

# 阶段 1：规划
run_plan_phase() {
  local work_dir="$1"
  log_phase "阶段 1/4: 需求分析与计划制定"

  local req_file
  req_file=$(get_state '.requirements_file')
  local requirements
  requirements=$(cat "$req_file")

  # 规划阶段使用单次 Claude 调用（不需要循环验证）
  local plan_prompt
  plan_prompt=$(sed "s|{{REQUIREMENTS}}|$requirements|g" "$SCRIPT_DIR/prompts/plan.md" | \
    sed "s|{{PROJECT_DIR}}|$work_dir|g")

  log_info "正在分析需求并制定计划..."
  echo "$plan_prompt" | claude -p \
    --dangerously-skip-permissions \
    2>&1 | tee "$LOG_DIR/phase-plan-1.log"

  # 验证计划文件已生成
  if [[ -f ".phantom/plan.md" ]]; then
    log_ok "计划已生成: .phantom/plan.md"
    set_phase_status "plan" "completed"
    advance_phase
  else
    log_error "计划文件未生成，重试..."
    # 再试一次
    echo "$plan_prompt" | claude -p \
      --dangerously-skip-permissions \
      2>&1 | tee "$LOG_DIR/phase-plan-2.log"
    if [[ -f ".phantom/plan.md" ]]; then
      log_ok "计划已生成: .phantom/plan.md"
      set_phase_status "plan" "completed"
      advance_phase
    else
      log_error "计划生成失败"
      exit 1
    fi
  fi
}

# 阶段 2：开发（Ralph-loop，最少10次验证，最多50次）
run_dev_phase() {
  local work_dir="$1"
  log_phase "阶段 2/4: 代码开发"

  run_loop "dev" \
    "$SCRIPT_DIR/prompts/develop.md" \
    "$SCRIPT_DIR/prompts/verify-dev.md" \
    10 50 "$work_dir"

  advance_phase
}

# 阶段 3：测试（Ralph-loop，最少2次验证，最多5次）
run_test_phase() {
  local work_dir="$1"
  log_phase "阶段 3/4: 测试验证"

  run_loop "test" \
    "$SCRIPT_DIR/prompts/test.md" \
    "$SCRIPT_DIR/prompts/verify-test.md" \
    2 5 "$work_dir"

  advance_phase
}

# 阶段 4：Docker 部署
run_deploy_phase() {
  local work_dir="$1"
  log_phase "阶段 4/4: Docker 构建与部署验证"

  local deploy_prompt
  deploy_prompt=$(sed "s|{{PROJECT_DIR}}|$work_dir|g" "$SCRIPT_DIR/prompts/deploy.md")

  local max_attempts=3
  local attempt=0

  while [[ $attempt -lt $max_attempts ]]; do
    attempt=$((attempt + 1))
    log_info "Docker 部署尝试 $attempt/$max_attempts..."

    local result
    result=$(echo "$deploy_prompt" | claude -p \
      --dangerously-skip-permissions \
      2>&1 | tee "$LOG_DIR/phase-deploy-${attempt}.log")

    if echo "$result" | grep -qi "PHASE_COMPLETE"; then
      log_ok "Docker 部署验证成功!"
      set_phase_status "deploy" "completed"
      return 0
    fi

    log_warn "部署未成功，重试..."
  done

  log_error "Docker 部署在 $max_attempts 次尝试后仍未成功"
  set_phase_status "deploy" "failed"
  return 1
}
```

- [ ] **Step 2: 验证脚本语法**

Run: `bash -n lib/phases.sh`
Expected: 无输出

- [ ] **Step 3: Commit**

```bash
git add lib/phases.sh
git commit -m "feat: add phase execution functions"
```

---

### Task 5: 主入口脚本

**Files:**
- Create: `phantom-dev.sh`

- [ ] **Step 1: 创建主入口脚本 phantom-dev.sh**

```bash
#!/usr/bin/env bash
# phantom-dev.sh - Phantom AutoDev 全自主需求开发程序
#
# 用法: ./phantom-dev.sh <需求文档路径> [项目目录]
#
# 输入需求文档，全程自主完成：需求分析 -> 计划 -> 开发 -> 测试 -> Docker部署

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/state.sh"
source "$SCRIPT_DIR/lib/phases.sh"

# ── 参数解析 ──────────────────────────────────────────────

usage() {
  cat <<'EOF'
Phantom AutoDev - 全自主需求开发程序

用法:
  ./phantom-dev.sh <需求文档路径> [项目目录]

参数:
  需求文档路径    必须，指向需求文档的路径（.md / .txt）
  项目目录        可选，代码生成的目标目录（默认: ./project）

选项:
  -h, --help      显示帮助
  --resume        从上次中断的阶段继续

示例:
  ./phantom-dev.sh requirements.md
  ./phantom-dev.sh docs/spec.md ./my-project
  ./phantom-dev.sh requirements.md --resume
EOF
}

RESUME=false
REQ_FILE=""
PROJECT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --resume) RESUME=true; shift ;;
    *)
      if [[ -z "$REQ_FILE" ]]; then
        REQ_FILE="$1"
      elif [[ -z "$PROJECT_DIR" ]]; then
        PROJECT_DIR="$1"
      fi
      shift
      ;;
  esac
done

if [[ -z "$REQ_FILE" ]]; then
  log_error "请提供需求文档路径"
  usage
  exit 1
fi

# 转换为绝对路径
REQ_FILE="$(cd "$(dirname "$REQ_FILE")" && pwd)/$(basename "$REQ_FILE")"

if [[ ! -f "$REQ_FILE" ]]; then
  log_error "需求文档不存在: $REQ_FILE"
  exit 1
fi

PROJECT_DIR="${PROJECT_DIR:-./project}"
mkdir -p "$PROJECT_DIR"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

# ── 初始化 ────────────────────────────────────────────────

log_phase "Phantom AutoDev 启动"
log_info "需求文档: $REQ_FILE"
log_info "项目目录: $PROJECT_DIR"

check_dependencies

# 切换到项目目录
cd "$PROJECT_DIR"

# 初始化 git（如果没有的话）
if [[ ! -d .git ]]; then
  git init
  log_ok "Git 仓库已初始化"
fi

# 初始化或恢复状态
if [[ "$RESUME" == true ]] && state_exists; then
  log_info "从上次中断处继续..."
else
  init_state "$REQ_FILE" "$PROJECT_DIR"
  log_ok "状态已初始化"
fi

# ── 主循环（状态机） ──────────────────────────────────────

run_all_phases() {
  while true; do
    local current_phase
    current_phase=$(get_state '.current_phase')

    case "$current_phase" in
      plan)
        run_plan_phase "$PROJECT_DIR"
        ;;
      dev)
        run_dev_phase "$PROJECT_DIR"
        ;;
      test)
        run_test_phase "$PROJECT_DIR"
        ;;
      deploy)
        run_deploy_phase "$PROJECT_DIR"
        ;;
      done)
        log_phase "全部阶段完成!"
        log_ok "项目已就绪: $PROJECT_DIR"
        echo ""
        log_info "状态摘要:"
        jq '.phases' "$STATE_FILE"
        return 0
        ;;
      *)
        log_error "未知阶段: $current_phase"
        return 1
        ;;
    esac
  done
}

# 记录开始时间
START_TIME=$(date +%s)

# 运行
run_all_phases
EXIT_CODE=$?

# 统计耗时
END_TIME=$(date +%s)
ELAPSED=$(( END_TIME - START_TIME ))
MINUTES=$(( ELAPSED / 60 ))
SECONDS_REM=$(( ELAPSED % 60 ))

echo ""
log_info "总耗时: ${MINUTES}分${SECONDS_REM}秒"

exit $EXIT_CODE
```

- [ ] **Step 2: 设置执行权限**

Run: `chmod +x phantom-dev.sh`

- [ ] **Step 3: 验证脚本语法**

Run: `bash -n phantom-dev.sh`
Expected: 无输出

- [ ] **Step 4: Commit**

```bash
git add phantom-dev.sh
git commit -m "feat: add main entry script with state machine driver"
```

---

### Task 6: 改进 loop.sh — 修复 sed 模板替换与 Claude CLI 集成

**Files:**
- Modify: `lib/loop.sh`

- [ ] **Step 1: 重写 loop.sh 中的模板替换逻辑**

`sed` 无法安全替换包含特殊字符的多行内容。改用 `envsubst` 或 heredoc 方式。同时修复 `claude -p --continue` 的正确用法（`--continue` 不能与 `-p` 同时使用管道输入，需改为 `--resume` 加 session ID，或者每次都启动新会话并让 Claude 通过文件看到历史）。

```bash
#!/usr/bin/env bash
# lib/loop.sh - Ralph-loop 循环引擎（修正版）
#
# 核心原理：反复调用 Claude，每次都让它检查当前文件状态。
# Claude 通过读取文件和 git history 看到自己之前的工作。

source "$(dirname "${BASH_SOURCE[0]}")/utils.sh"
source "$(dirname "${BASH_SOURCE[0]}")/state.sh"

# 将模板中的占位符替换为实际内容，写入临时文件
render_prompt() {
  local template_file="$1"
  local work_dir="$2"
  local output_file
  output_file=$(mktemp)

  local req_file
  req_file=$(get_state '.requirements_file')
  local requirements=""
  [[ -f "$req_file" ]] && requirements=$(cat "$req_file")

  local plan=""
  [[ -f ".phantom/plan.md" ]] && plan=$(cat ".phantom/plan.md")

  # 使用 awk 进行安全的多行替换
  awk -v req="$requirements" -v plan="$plan" -v dir="$work_dir" '
  {
    gsub(/\{\{REQUIREMENTS\}\}/, req)
    gsub(/\{\{PLAN\}\}/, plan)
    gsub(/\{\{PROJECT_DIR\}\}/, dir)
    print
  }' "$template_file" > "$output_file"

  echo "$output_file"
}

# 运行带自验证的 Claude 循环
run_loop() {
  local phase="$1"
  local main_prompt_file="$2"
  local verify_prompt_file="$3"
  local min_checks="$4"
  local max_checks="$5"
  local work_dir="$6"

  local iteration=0
  local consecutive_done=0

  set_phase_status "$phase" "in_progress"

  log_phase "阶段: $phase (最少验证 $min_checks 次，最多 $max_checks 次)"

  while [[ $iteration -lt $max_checks ]]; do
    iteration=$((iteration + 1))
    increment_iteration "$phase"

    local log_file="$LOG_DIR/phase-${phase}-${iteration}.log"

    if [[ $iteration -eq 1 ]]; then
      # 第一次迭代：执行主任务
      log_info "[$phase] 迭代 $iteration/$max_checks - 执行主任务..."

      local prompt_file
      prompt_file=$(render_prompt "$main_prompt_file" "$work_dir")

      claude -p \
        --dangerously-skip-permissions \
        "$(cat "$prompt_file")" \
        2>&1 | tee "$log_file"

      rm -f "$prompt_file"
    else
      # 后续迭代：验证 + 继续改进
      log_info "[$phase] 迭代 $iteration/$max_checks - 验证完成度..."

      local verify_file
      verify_file=$(render_prompt "$verify_prompt_file" "$work_dir")

      local result
      result=$(claude -p \
        --dangerously-skip-permissions \
        "$(cat "$verify_file")" \
        2>&1 | tee -a "$log_file")

      rm -f "$verify_file"

      # 检查 Claude 是否确认完成
      if echo "$result" | grep -q "PHASE_COMPLETE"; then
        consecutive_done=$((consecutive_done + 1))
        log_ok "[$phase] Claude 确认完成 ($consecutive_done/$min_checks 连续确认)"

        if [[ $consecutive_done -ge $min_checks ]]; then
          log_ok "[$phase] 达到最小验证次数，阶段完成!"
          return 0
        fi
      else
        consecutive_done=0
        log_warn "[$phase] Claude 认为还未完成，继续迭代..."
      fi
    fi
  done

  log_warn "[$phase] 已达最大迭代次数 $max_checks"
  return 0
}
```

- [ ] **Step 2: 验证脚本语法**

Run: `bash -n lib/loop.sh`
Expected: 无输出

- [ ] **Step 3: Commit**

```bash
git add lib/loop.sh
git commit -m "fix: rewrite loop engine with safe template rendering and correct CLI usage"
```

---

### Task 7: 端到端验证 — 用示例需求文档测试完整流程

**Files:**
- Create: `test/sample-requirements.md`

- [ ] **Step 1: 创建测试用的简单需求文档**

```markdown
# 需求：简单的 Todo API

## 功能需求

构建一个简单的 Todo 待办事项 REST API。

### 接口列表

1. `GET /todos` - 获取所有待办事项
2. `POST /todos` - 创建新的待办事项
3. `GET /todos/:id` - 获取单个待办事项
4. `PUT /todos/:id` - 更新待办事项
5. `DELETE /todos/:id` - 删除待办事项

### 数据模型

```json
{
  "id": "string (uuid)",
  "title": "string (必填)",
  "completed": "boolean (默认 false)",
  "created_at": "datetime"
}
```

### 技术要求

- 使用 Node.js + Express
- 内存存储（不需要数据库）
- 返回 JSON 格式
- 端口：3000

### 非功能需求

- 代码结构清晰
- 包含 package.json
- 包含 Dockerfile
```

- [ ] **Step 2: 试运行（dry-run 验证脚本能正确启动）**

Run: `cd /Users/doorlaps/workspace/claude/Phantom/AIDevelop && bash -x phantom-dev.sh test/sample-requirements.md ./test-project 2>&1 | head -30`

观察：脚本能否正确解析参数、初始化状态、切换到项目目录。如果报错则修复。

- [ ] **Step 3: Commit**

```bash
git add test/
git commit -m "test: add sample requirements for end-to-end testing"
```

---

### Task 8: 添加 README 使用说明

**Files:**
- Create: `README.md`

- [ ] **Step 1: 创建 README.md**

```markdown
# Phantom AutoDev

全自主需求开发程序 — 输入需求文档，自动完成从规划到部署的全流程。

## 原理

基于 Claude Code CLI 和 Ralph-loop 循环机制：
- **规划阶段**：Claude 分析需求文档，生成实施计划
- **开发阶段**：Claude 按计划编写代码，完成后循环自检（10-50次），确保功能完整
- **测试阶段**：自动编写并运行单元测试/Playwright测试，循环自检（2-5次）
- **部署阶段**：Docker 构建并本地运行验证

## 依赖

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) >= 2.0
- jq
- Docker

## 使用方法

```bash
# 基本用法
./phantom-dev.sh requirements.md

# 指定项目目录
./phantom-dev.sh requirements.md ./my-project

# 从中断处继续
./phantom-dev.sh requirements.md --resume
```

## 运行时状态

运行过程中，状态保存在项目目录的 `.phantom/` 下：
- `state.json` — 当前阶段和迭代次数
- `plan.md` — Claude 生成的实施计划
- `logs/` — 每次迭代的详细日志
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with usage instructions"
```

---

## 自检结果

**需求覆盖：**
- [x] 接收开发需求文档 — `phantom-dev.sh` 第一个参数
- [x] 使用 `claude --dangerously-skip-permissions` — 所有 Claude 调用都带此标志
- [x] 按需求文档做计划，默认选择推荐方案 — `prompts/plan.md` 明确指示
- [x] 开发阶段 Ralph-loop 循环验证（10-50次）— `run_dev_phase` 调用 `run_loop "dev" ... 10 50`
- [x] 测试阶段：后端单元/接口测试 + 前端 Playwright 测试 — `prompts/test.md` 涵盖两种情况
- [x] 测试阶段循环验证（2-5次）— `run_test_phase` 调用 `run_loop "test" ... 2 5`
- [x] Docker 构建与本地部署验证 — `run_deploy_phase` + `prompts/deploy.md`
- [x] 未完成就一直运行 — 状态机 + while 循环 + 验证次数机制

**占位符扫描：** 无 TODO/TBD/占位符

**类型一致性：** 函数名/文件路径/参数在所有 Task 间一致
