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
  ./phantom.sh <需求文档路径或需求文本> [项目目录]

参数:
  需求            必须，可以是文件路径（.md / .txt）或直接输入需求文本
  项目目录        可选，代码生成的目标目录（默认: ./projects/<自动命名>）

选项:
  -h, --help      显示帮助
  --resume        从上次中断的阶段继续

示例:
  ./phantom.sh requirements.md
  ./phantom.sh "构建一个Todo API，使用Node.js + Express，端口3000"
  ./phantom.sh docs/spec.md ./my-project
  ./phantom.sh requirements.md --resume
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
  log_error "请提供需求文档路径或需求文本"
  usage
  exit 1
fi

# 判断是文件路径还是纯文本需求
if [[ -f "$REQ_FILE" ]]; then
  # 是文件路径，转换为绝对路径
  REQ_FILE="$(cd "$(dirname "$REQ_FILE")" && pwd)/$(basename "$REQ_FILE")"
else
  # 是纯文本需求，写入临时文件
  REQ_TEXT="$REQ_FILE"
  REQ_FILE="$(mktemp "${TMPDIR:-/tmp}/phantom-req-XXXXXX.md")"
  echo "$REQ_TEXT" > "$REQ_FILE"
  log_info "需求文本已写入临时文件: $REQ_FILE"
fi

# 如果未指定项目目录，自动生成目录名
if [[ -z "$PROJECT_DIR" ]]; then
  # 用 Claude 从需求文档提取一个简短的英文项目名
  AUTO_NAME=$(claude -p --dangerously-skip-permissions \
    "Read this file: $REQ_FILE. Based on its content, output ONLY a short kebab-case project directory name (e.g. todo-api, user-auth-service, blog-platform). No explanation, no quotes, just the name." \
    2>/dev/null | tr -d '[:space:]' | head -c 50)

  # 回退：如果 Claude 没返回有效名字，用时间戳
  if [[ -z "$AUTO_NAME" ]] || [[ ! "$AUTO_NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    AUTO_NAME="project-$(date +%Y%m%d-%H%M%S)"
  fi

  PROJECT_DIR="./projects/$AUTO_NAME"
  log_info "自动生成项目目录: $PROJECT_DIR"
fi

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
