#!/usr/bin/env bash
# phantom-dev.sh - Phantom AutoDev 全自主需求开发程序
#
# 用法: ./phantom-dev.sh <需求文档路径> [项目目录]
#
# 输入需求文档，全程自主完成：需求分析 -> 计划 -> 开发 -> 测试 -> Docker部署

set -euo pipefail

# ── 解析 symlink，找到真实脚本所在目录 ──
# 允许通过 `ln -s /path/to/phantom.sh /usr/local/bin/phantom` 安装后直接调用
_SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$_SOURCE" ]]; do
  _DIR="$(cd -P "$(dirname "$_SOURCE")" && pwd)"
  _SOURCE="$(readlink "$_SOURCE")"
  [[ "$_SOURCE" != /* ]] && _SOURCE="$_DIR/$_SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$_SOURCE")" && pwd)"
unset _SOURCE _DIR

# 用户的当前工作目录（生成的项目会落在这里，而非 phantom 仓库内）
INVOKE_CWD="$(pwd)"

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
  项目目录        可选，代码生成的目标目录（默认：当前目录下的 ./<自动命名>/）

  --resume / --delete 默认扫描**当前目录**下的子项目。

选项:
  -h, --help                  显示帮助
  --resume [项目名]            从上次中断的阶段继续
  --delete [项目名]            删除项目
  --strict                    任意阶段达到最大轮次直接失败（不强制推进）
  --backend <claude|codex>    同时设置 generator 和 reviewer 后端
  --generator <claude|codex>  指定 generator 后端
  --reviewer <claude|codex>   指定 reviewer 后端

  位置参数 claude/codex 等同于 --backend（向后兼容）

示例:
  ./phantom.sh requirements.md
  ./phantom.sh --backend codex requirements.md
  ./phantom.sh --generator codex --reviewer claude requirements.md
  ./phantom.sh --strict requirements.md
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
    --strict) export PHANTOM_STRICT=1; shift ;;
    --backend)
      export PHANTOM_BACKEND="$2"; shift 2 ;;
    --generator)
      export PHANTOM_GENERATOR_BACKEND="$2"; shift 2 ;;
    --reviewer)
      export PHANTOM_REVIEWER_BACKEND="$2"; shift 2 ;;
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
  # 当前目录本身就是项目
  if [[ -z "$PROJECT_DIR" ]] && [[ -f "$INVOKE_CWD/.phantom/state.json" ]]; then
    printf "确认清理当前目录的 phantom 状态（.phantom/ 目录将被删除，代码文件保留）？(y/N): "
    read -r CONFIRM
    if [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]]; then
      rm -rf "$INVOKE_CWD/.phantom"
      log_ok "已清理 .phantom/"
    else
      log_info "已取消"
    fi
    exit 0
  fi
  if [[ -z "$PROJECT_DIR" ]]; then
    # 扫描当前目录下含 .phantom/state.json 的子项目
    PROJECTS=()
    for dir in "$INVOKE_CWD"/*/; do
      [[ -d "$dir" ]] || continue
      [[ -f "$dir/.phantom/state.json" ]] || continue
      proj_name="$(basename "$dir")"
      phase=$(jq -r '.current_phase' "$dir/.phantom/state.json" 2>/dev/null || echo "—")
      PROJECTS+=("$dir|$proj_name|$phase")
    done

    if [[ ${#PROJECTS[@]} -eq 0 ]]; then
      log_error "当前目录 ($INVOKE_CWD) 下没有 phantom 项目可删除"
      exit 1
    fi

    echo ""
    log_info "项目列表（当前目录：${INVOKE_CWD}）："
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
    # 指定了项目名或路径
    DEL_NAME="$PROJECT_DIR"
    if [[ -d "$INVOKE_CWD/$DEL_NAME" ]]; then
      DEL_DIR="$INVOKE_CWD/$DEL_NAME"
    elif [[ -d "$DEL_NAME" ]]; then
      DEL_DIR="$(cd "$DEL_NAME" && pwd)"
      DEL_NAME="$(basename "$DEL_DIR")"
    else
      log_error "项目不存在: $DEL_NAME（在 $INVOKE_CWD 下也未找到）"
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
  # 当前目录本身就是项目
  if [[ -z "$PROJECT_DIR" ]] && [[ -f "$INVOKE_CWD/.phantom/state.json" ]]; then
    PROJECT_DIR="$INVOKE_CWD"
  fi
  # 如果未指定项目，扫描当前目录下含 .phantom/state.json 的子项目
  if [[ -z "$PROJECT_DIR" ]]; then
    PROJECTS=()
    while IFS= read -r state_file; do
      proj_dir="$(dirname "$(dirname "$state_file")")"
      proj_name="$(basename "$proj_dir")"
      phase=$(jq -r '.current_phase' "$state_file" 2>/dev/null)
      PROJECTS+=("$proj_dir|$proj_name|$phase")
    done < <(find "$INVOKE_CWD" -maxdepth 3 -name "state.json" -path "*/.phantom/*" 2>/dev/null)

    if [[ ${#PROJECTS[@]} -eq 0 ]]; then
      log_error "当前目录 ($INVOKE_CWD) 下没有找到可恢复的 phantom 项目"
      exit 1
    fi

    echo ""
    log_info "可恢复的项目（当前目录：${INVOKE_CWD}）："
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
  elif [[ -d "$INVOKE_CWD/$PROJECT_DIR" ]]; then
    # 当前目录下的子项目名
    PROJECT_DIR="$INVOKE_CWD/$PROJECT_DIR"
  elif [[ ! -d "$PROJECT_DIR" ]]; then
    log_error "项目不存在: $PROJECT_DIR (也不在当前目录 $INVOKE_CWD 下)"
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

  FORCED_PHASES=$(list_forced_phases)
  if [[ -n "$FORCED_PHASES" ]]; then
    log_warn "以下阶段曾因达到最大轮次被**强制推进**（非正常通过）："
    echo "$FORCED_PHASES" | sed 's/^/  - /'
    log_warn "这些阶段的产物可能不达标。建议核查 .phantom/logs/ 和当前代码状态。"
  fi

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

  # 未指定项目目录时，直接使用当前目录（不再新建子目录）
  if [[ -z "$PROJECT_DIR" ]]; then
    PROJECT_DIR="$INVOKE_CWD"
    if [[ -f "$PROJECT_DIR/.phantom/state.json" ]]; then
      log_error "当前目录已有 phantom 项目（.phantom/state.json 已存在）。使用 --resume 恢复或 --delete 清理。"
      exit 1
    fi
    log_info "将在当前目录生成项目: $PROJECT_DIR"
  elif [[ "$PROJECT_DIR" != /* ]]; then
    # 用户传的是相对路径，按当前目录解析
    PROJECT_DIR="$INVOKE_CWD/$PROJECT_DIR"
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

  PORT=$(ensure_port)
  export PORT
  log_info "已分配端口: $PORT (持久化到 .phantom/port)"
fi

# Resume / 新项目 都需要把 PORT 注入环境，供后续所有阶段使用
if [[ -z "${PORT:-}" ]]; then
  PORT=$(ensure_port)
  export PORT
  log_info "项目端口: $PORT"
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
      devtest)
        run_devtest_phase "$PROJECT_DIR"
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

        # 初始化项目配置文件
        local b=$(get_backend)
        local init_prompt='分析当前目录下的所有代码文件（忽略 .phantom/、node_modules/、.git/），然后用 Write 工具在当前目录创建一个文件，内容为该项目的说明文档，涵盖：项目概述、技术栈、目录结构、关键文件职责、如何运行/测试/部署、开发规范。直接写文件，不要只在终端输出。'
        if [[ "$b" == "claude" ]]; then
          log_info "正在生成 CLAUDE.md..."
          (cd "$PROJECT_DIR" && claude -p --dangerously-skip-permissions \
            "${init_prompt/说明文档/CLAUDE.md 文档}" ) || log_warn "CLAUDE.md 生成失败"
          [[ -f "$PROJECT_DIR/CLAUDE.md" ]] && log_ok "已生成 CLAUDE.md" || log_warn "CLAUDE.md 未生成"
          log_ok "可以使用 cd $PROJECT_DIR && claude 继续开发"
        elif [[ "$b" == "codex" ]]; then
          log_info "正在生成 AGENTS.md..."
          (cd "$PROJECT_DIR" && codex exec --dangerously-bypass-approvals-and-sandbox \
            "${init_prompt/说明文档/AGENTS.md 文档}" ) || log_warn "AGENTS.md 生成失败"
          [[ -f "$PROJECT_DIR/AGENTS.md" ]] && log_ok "已生成 AGENTS.md" || log_warn "AGENTS.md 未生成"
          log_ok "可以使用 cd $PROJECT_DIR && codex 继续开发"
        fi
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
