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
  -h, --help              显示帮助
  --resume [项目名]        从上次中断的阶段继续
  --delete [项目名]        删除项目

  第一个参数如果是 claude 或 codex，则指定 AI 后端（默认 claude）

示例:
  ./phantom.sh requirements.md
  ./phantom.sh claude requirements.md
  ./phantom.sh codex requirements.md
  ./phantom.sh "构建一个Todo API，使用Node.js + Express，端口3000"
  ./phantom.sh --resume
  ./phantom.sh --resume todo-api
  ./phantom.sh --delete todo-api
EOF
}

RESUME=false
DELETE=false
REQ_INPUT=""
PROJECT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --resume) RESUME=true; shift ;;
    --delete) DELETE=true; shift ;;
    claude|codex)
      export PHANTOM_BACKEND="$1"; shift ;;
    *)
      if [[ "$RESUME" == true || "$DELETE" == true ]] && [[ -z "$PROJECT_DIR" ]]; then
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

# ── Delete 模式 ──────────────────────────────────────────

if [[ "$DELETE" == true ]]; then
  if [[ -z "$PROJECT_DIR" ]]; then
    # 列出所有项目让用户选择
    PROJECTS=()
    for dir in "$SCRIPT_DIR/projects"/*/; do
      [[ -d "$dir" ]] || continue
      proj_name="$(basename "$dir")"
      phase="—"
      if [[ -f "$dir/.phantom/state.json" ]]; then
        phase=$(jq -r '.current_phase' "$dir/.phantom/state.json" 2>/dev/null)
      fi
      PROJECTS+=("$dir|$proj_name|$phase")
    done

    if [[ ${#PROJECTS[@]} -eq 0 ]]; then
      log_error "没有项目可删除"
      exit 1
    fi

    echo ""
    log_info "项目列表："
    echo ""
    for i in "${!PROJECTS[@]}"; do
      IFS='|' read -r dir name phase <<< "${PROJECTS[$i]}"
      printf "  ${CYAN}[%d]${NC} %-30s (阶段: %s)\n" "$((i + 1))" "$name" "$phase"
    done
    echo ""
    printf "请选择要删除的项目编号（输入 0 取消）: "
    read -r CHOICE

    if [[ "$CHOICE" == "0" ]]; then
      log_info "已取消"
      exit 0
    fi

    if [[ ! "$CHOICE" =~ ^[0-9]+$ ]] || [[ "$CHOICE" -lt 1 ]] || [[ "$CHOICE" -gt ${#PROJECTS[@]} ]]; then
      log_error "无效的选择"
      exit 1
    fi

    IFS='|' read -r DEL_DIR DEL_NAME _ <<< "${PROJECTS[$((CHOICE - 1))]}"
  else
    # 指定了项目名
    DEL_NAME="$PROJECT_DIR"
    DEL_DIR="$SCRIPT_DIR/projects/$DEL_NAME"
    if [[ ! -d "$DEL_DIR" ]]; then
      log_error "项目不存在: $DEL_NAME"
      exit 1
    fi
  fi

  printf "确认删除项目 ${RED}$DEL_NAME${NC}？(y/N): "
  read -r CONFIRM
  if [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]]; then
    rm -rf "$DEL_DIR"
    log_ok "已删除项目: $DEL_NAME"
  else
    log_info "已取消"
  fi
  exit 0
fi

# ── Resume 模式 ──────────────────────────────────────────

if [[ "$RESUME" == true ]]; then
  # 如果未指定项目，列出所有项目让用户选择
  if [[ -z "$PROJECT_DIR" ]]; then
    # 收集所有含 state.json 的项目
    PROJECTS=()
    while IFS= read -r state_file; do
      proj_dir="$(dirname "$(dirname "$state_file")")"
      proj_name="$(basename "$proj_dir")"
      phase=$(jq -r '.current_phase' "$state_file" 2>/dev/null)
      PROJECTS+=("$proj_dir|$proj_name|$phase")
    done < <(find "$SCRIPT_DIR/projects" -name "state.json" -path "*/.phantom/*" -maxdepth 3 2>/dev/null)

    if [[ ${#PROJECTS[@]} -eq 0 ]]; then
      log_error "没有找到可恢复的项目"
      exit 1
    fi

    echo ""
    log_info "可恢复的项目："
    echo ""
    for i in "${!PROJECTS[@]}"; do
      IFS='|' read -r dir name phase <<< "${PROJECTS[$i]}"
      printf "  ${CYAN}[%d]${NC} %-30s (阶段: %s)\n" "$((i + 1))" "$name" "$phase"
    done
    echo ""
    printf "请选择项目编号: "
    read -r CHOICE

    if [[ ! "$CHOICE" =~ ^[0-9]+$ ]] || [[ "$CHOICE" -lt 1 ]] || [[ "$CHOICE" -gt ${#PROJECTS[@]} ]]; then
      log_error "无效的选择"
      exit 1
    fi

    IFS='|' read -r PROJECT_DIR _ _ <<< "${PROJECTS[$((CHOICE - 1))]}"
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
    REQ_FILE="$(mktemp "${TMPDIR:-/tmp}/phantom-req-XXXXXX")"
    echo "$REQ_TEXT" > "$REQ_FILE"
    log_info "需求文本已写入临时文件: $REQ_FILE"
  fi

  # 如果未指定项目目录，自动生成目录名
  if [[ -z "$PROJECT_DIR" ]]; then
    NAME_PROMPT="Read this file: $REQ_FILE. Based on its content, output ONLY a short kebab-case project directory name (e.g. todo-api, user-auth-service, blog-platform). No explanation, no quotes, just the name."
    if [[ "${PHANTOM_BACKEND:-claude}" == "codex" ]]; then
      AUTO_NAME=$(codex exec --dangerously-bypass-approvals-and-sandbox "$NAME_PROMPT" 2>/dev/null | tr -d '[:space:]' | head -c 50)
    else
      AUTO_NAME=$(claude -p --dangerously-skip-permissions "$NAME_PROMPT" 2>/dev/null | tr -d '[:space:]' | head -c 50)
    fi

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
