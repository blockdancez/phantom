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
  ./phantom.sh --resume [项目目录]

参数:
  需求            可以是文件路径（.md / .txt）或直接输入需求文本
  项目目录        可选，代码生成的目标目录（默认: ./projects/<自动命名>）

选项:
  -h, --help      显示帮助
  --resume [项目名]  从上次中断的阶段继续（从 state.json 恢复）

示例:
  ./phantom.sh requirements.md
  ./phantom.sh "构建一个Todo API，使用Node.js + Express，端口3000"
  ./phantom.sh docs/spec.md ./my-project
  ./phantom.sh --resume
  ./phantom.sh --resume todo-api
EOF
}

RESUME=false
REQ_INPUT=""
PROJECT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --resume) RESUME=true; shift ;;
    *)
      if [[ "$RESUME" == true ]] && [[ -z "$PROJECT_DIR" ]]; then
        # --resume 模式下，参数当作项目目录
        PROJECT_DIR="$1"
      elif [[ -z "$REQ_INPUT" ]]; then
        REQ_INPUT="$1"
      elif [[ -z "$PROJECT_DIR" ]]; then
        PROJECT_DIR="$1"
      fi
      shift
      ;;
  esac
done

# ── Resume 模式 ──────────────────────────────────────────

if [[ "$RESUME" == true ]]; then
  # 如果未指定项目目录，尝试找到最近的项目
  if [[ -z "$PROJECT_DIR" ]]; then
    LATEST=$(find "$SCRIPT_DIR/projects" -name "state.json" -path "*/.phantom/*" -maxdepth 3 2>/dev/null | \
      xargs ls -t 2>/dev/null | head -1)
    if [[ -n "$LATEST" ]]; then
      PROJECT_DIR="$(dirname "$(dirname "$LATEST")")"
    else
      log_error "找不到可恢复的项目。请指定项目名：./phantom.sh --resume todo-api"
      exit 1
    fi
  elif [[ -d "$SCRIPT_DIR/projects/$PROJECT_DIR" ]]; then
    # 传入的是项目名，拼接完整路径
    PROJECT_DIR="$SCRIPT_DIR/projects/$PROJECT_DIR"
  elif [[ ! -d "$PROJECT_DIR" ]]; then
    log_error "项目不存在: $PROJECT_DIR (也不在 projects/ 下)"
    exit 1
  fi

  if [[ ! -f "$PROJECT_DIR/.phantom/state.json" ]]; then
    log_error "项目目录中没有状态文件: $PROJECT_DIR/.phantom/state.json"
    exit 1
  fi

  PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
  cd "$PROJECT_DIR"

  # 从 state.json 恢复需求文件路径
  REQ_FILE=$(jq -r '.requirements_file' .phantom/state.json)
  CURRENT_PHASE=$(jq -r '.current_phase' .phantom/state.json)

  log_phase "Phantom AutoDev 恢复运行"
  log_info "项目目录: $PROJECT_DIR"
  log_info "需求文档: $REQ_FILE"
  log_info "当前阶段: $CURRENT_PHASE"

  check_dependencies

else
  # ── 新项目模式 ──────────────────────────────────────────

  if [[ -z "$REQ_INPUT" ]]; then
    log_error "请提供需求文档路径或需求文本"
    usage
    exit 1
  fi

  # 判断是文件路径还是纯文本需求
  if [[ -f "$REQ_INPUT" ]]; then
    REQ_FILE="$(cd "$(dirname "$REQ_INPUT")" && pwd)/$(basename "$REQ_INPUT")"
  else
    REQ_TEXT="$REQ_INPUT"
    REQ_FILE="$(mktemp "${TMPDIR:-/tmp}/phantom-req-XXXXXX.md")"
    echo "$REQ_TEXT" > "$REQ_FILE"
    log_info "需求文本已写入临时文件: $REQ_FILE"
  fi

  # 如果未指定项目目录，自动生成目录名
  if [[ -z "$PROJECT_DIR" ]]; then
    AUTO_NAME=$(claude -p --dangerously-skip-permissions \
      "Read this file: $REQ_FILE. Based on its content, output ONLY a short kebab-case project directory name (e.g. todo-api, user-auth-service, blog-platform). No explanation, no quotes, just the name." \
      2>/dev/null | tr -d '[:space:]' | head -c 50)

    if [[ -z "$AUTO_NAME" ]] || [[ ! "$AUTO_NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
      AUTO_NAME="project-$(date +%Y%m%d-%H%M%S)"
    fi

    PROJECT_DIR="$SCRIPT_DIR/projects/$AUTO_NAME"
    log_info "自动生成项目目录: $PROJECT_DIR"
  fi

  mkdir -p "$PROJECT_DIR"
  PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

  log_phase "Phantom AutoDev 启动"
  log_info "需求文档: $REQ_FILE"
  log_info "项目目录: $PROJECT_DIR"

  check_dependencies

  cd "$PROJECT_DIR"

  # 初始化 git
  if [[ ! -d .git ]]; then
    git init
    log_ok "Git 仓库已初始化"
  fi

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
