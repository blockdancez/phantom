#!/usr/bin/env bash
# phantom-dev.sh - Phantom AutoDev 全自主需求开发程序
#
# 用法: ./phantom-dev.sh <需求文档路径> [项目目录]
#
# 输入需求文档，全程自主完成：需求分析 -> 计划 -> 开发 -> 测试 -> 部署

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
  ./phantom.sh <需求文档路径或需求文本> [项目目录]   # 新项目，跑全流程
  ./phantom.sh "<增量需求>"                          # 已有项目，默认走 --plan 增量
  ./phantom.sh --plan [需求]                         # 只跑 plan 模式
  ./phantom.sh --design [需求]                       # 只跑 design 模式
  ./phantom.sh --dev-test [需求]                     # 只跑 dev/code-review/deploy/test 循环
  ./phantom.sh --test [需求]                         # 只重跑 test 一节
  ./phantom.sh --resume [项目目录]

模式 flag 的可选参数：
  - 字符串：作为**增量需求**写入 .phantom/amendment.md（plan/design 模式）
    或作为**必修项**构造 return-packet（dev-test 模式）
    或作为 extra note 给 tester（test 模式）
  - 文件路径：同上，读取文件内容作为增量需求
  - 省略：plan 模式支持"纯重规划"；其他模式要求项目已存在

如果不传任何模式 flag：
  - 无 .phantom/state.json → 全新项目，跑全流程（plan → design → dev-test）
  - 有 .phantom/state.json + 字符串需求 → 默认进入 --plan 增量模式
  - 有 .phantom/state.json + 文件需求 → 报错（歧义：要覆盖还是增量？请显式用 --plan <file>）
  - 有 .phantom/state.json + 无参 → 报错（请用 --resume 继续，或指定模式）

  --resume / --delete 默认扫描**当前目录**下的子项目。

选项:
  -h, --help                       显示帮助
  --resume [项目名]                 从上次中断的阶段继续
  --delete [项目名]                 删除项目
  --strict                         达到 max rounds 时直接失败（不 forced advance）
  --fast                           降低 min rounds 地板，快速跑通（烟测用）
  --plan [需求]                    只跑 plan 模式（plan → plan-review → plan）
  --design [需求]                  只跑 design 模式（design → design-review → design）
  --dev-test [需求]                只跑 dev → code-review → deploy → test 循环（不强制打磨）
  --test [需求]                    只重跑 test 一节（前置：deploy 产物存在、进程在线）
  --backend <claude|codex>         所有 role 的默认后端
  --generator <claude|codex>       指定 generator 后端
  --plan-reviewer <claude|codex>   指定 plan-reviewer 后端
  --code-reviewer <claude|codex>   指定 code-reviewer 后端
  --tester <claude|codex>          指定 tester 后端
  --deploy <claude|codex>          指定 deploy 后端

已弃用（保留兼容一个版本，会 warn）：
  --plan-only    → --plan
  --ui-only      → --design
  --skip-plan    → --dev-test
  --test-only    → --dev-test（保留 PHANTOM_TEST_ONLY 的 "test first per group" 行为）

跨模型默认规则：plan-reviewer / code-reviewer / tester / ui-design-reviewer 默认选一个
和 generator 不同的后端（只装一个后端时降级同后端并 warn）

位置参数 claude/codex 等同于 --backend（向后兼容）

示例:
  ./phantom.sh requirements.md                           # 新项目全流程
  ./phantom.sh "Todo API, Node+Express"                  # 新项目（字符串需求）
  ./phantom.sh "请添加列表搜索功能"                      # 已有项目：默认 plan 增量
  ./phantom.sh --plan "重新考虑一下 rubric 权重"          # 显式 plan 增量
  ./phantom.sh --design "UI 改成暖色调"                   # 只跑 design
  ./phantom.sh --dev-test "feature-3 搜索按钮点了没反应"   # 只跑一圈 dev-test
  ./phantom.sh --test                                    # 只重跑测试
  ./phantom.sh --backend codex requirements.md
  ./phantom.sh --resume
  ./phantom.sh --delete todo-api
EOF
}

RESUME=false
DELETE=false
MODE=""              # plan / design / dev-test / test / ""（空=全流程或自动路由）
REQ_INPUT=""
PROJECT_DIR=""

# 辅助：判断下一个 arg 是不是可以被当作 mode flag 的可选值
# 规则：非空 + 不以 - 开头 + 不是裸 backend 关键字（claude/codex）
_mode_arg_is_value() {
  [[ $# -ge 1 ]] && [[ -n "$1" ]] && [[ "$1" != -* ]] && [[ "$1" != "claude" ]] && [[ "$1" != "codex" ]]
}

_set_mode() {
  local new_mode="$1"
  if [[ -n "$MODE" && "$MODE" != "$new_mode" ]]; then
    log_error "模式 flag 冲突：已设置 --$MODE，又遇到 --$new_mode。一次只能指定一个模式。"
    exit 2
  fi
  MODE="$new_mode"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --resume) RESUME=true; shift ;;
    --delete) DELETE=true; shift ;;
    --strict) export PHANTOM_STRICT=1; shift ;;
    --fast) export PHANTOM_FAST=1; shift ;;

    # ── 新模式 flag（接受可选参数）──
    --plan)
      _set_mode "plan"
      if _mode_arg_is_value "${2:-}"; then REQ_INPUT="$2"; shift 2; else shift; fi ;;
    --design)
      _set_mode "design"
      if _mode_arg_is_value "${2:-}"; then REQ_INPUT="$2"; shift 2; else shift; fi ;;
    --dev-test)
      _set_mode "dev-test"
      if _mode_arg_is_value "${2:-}"; then REQ_INPUT="$2"; shift 2; else shift; fi ;;
    --test)
      _set_mode "test"
      if _mode_arg_is_value "${2:-}"; then REQ_INPUT="$2"; shift 2; else shift; fi ;;

    # ── 已弃用 flag：保留兼容 + warn ──
    --plan-only)
      log_warn "[deprecated] --plan-only → 请改用 --plan"
      _set_mode "plan"; shift ;;
    --ui-only)
      log_warn "[deprecated] --ui-only → 请改用 --design（新模式包含 review + revise 两轮，行为更完整）"
      _set_mode "design"; shift ;;
    --skip-plan)
      log_warn "[deprecated] --skip-plan → 请改用 --dev-test"
      _set_mode "dev-test"; shift ;;
    --test-only)
      log_warn "[deprecated] --test-only → 请改用 --dev-test（保留 PHANTOM_TEST_ONLY 的 test-first 行为）"
      _set_mode "dev-test"
      export PHANTOM_TEST_ONLY=1
      shift ;;

    --backend)
      export PHANTOM_BACKEND="$2"; shift 2 ;;
    --generator)
      export PHANTOM_GENERATOR_BACKEND="$2"; shift 2 ;;
    --plan-reviewer)
      export PHANTOM_PLAN_REVIEWER_BACKEND="$2"; shift 2 ;;
    --code-reviewer)
      export PHANTOM_CODE_REVIEWER_BACKEND="$2"; shift 2 ;;
    --tester)
      export PHANTOM_TESTER_BACKEND="$2"; shift 2 ;;
    --deploy)
      export PHANTOM_DEPLOY_BACKEND="$2"; shift 2 ;;
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

# 辅助：kill 掉项目的运行时进程
_kill_project_runtime() {
  local proj_dir="$1"
  local runtime_dir="$proj_dir/.phantom/runtime"
  [[ -d "$runtime_dir" ]] || return 0
  for pid_file in "$runtime_dir/backend.pid" "$runtime_dir/frontend.pid"; do
    [[ -f "$pid_file" ]] || continue
    local pid
    pid=$(cat "$pid_file" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      log_info "杀掉残留进程 PID=$pid ($(basename "$pid_file"))"
      kill -TERM "$pid" 2>/dev/null || true
      sleep 1
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      pkill -P "$pid" 2>/dev/null || true
    fi
  done
}

if [[ "$DELETE" == true ]]; then
  # 当前目录本身就是项目
  if [[ -z "$PROJECT_DIR" ]] && [[ -f "$INVOKE_CWD/.phantom/state.json" ]]; then
    printf "确认清理当前目录的 phantom 状态（.phantom/ 目录将被删除，代码文件保留）？(y/N): "
    read -r CONFIRM
    if [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]]; then
      _kill_project_runtime "$INVOKE_CWD"
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
      log_error "项目不存在: ${DEL_NAME}（在 ${INVOKE_CWD} 下也未找到）"
      exit 1
    fi
  fi

  printf "确认删除项目 ${RED}$DEL_NAME${NC}？(y/N): "
  read -r CONFIRM
  if [[ "$CONFIRM" == "y" || "$CONFIRM" == "Y" ]]; then
    _kill_project_runtime "$DEL_DIR"
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

  FORCED_FEATURES=$(list_forced_features)
  if [[ -n "$FORCED_FEATURES" ]]; then
    log_warn "以下 feature 曾因达到最大轮次被**强制推进**（非正常通过）："
    echo "$FORCED_FEATURES" | sed 's/^/  - /'
    log_warn "这些 feature 的产物可能不达标。建议核查 .phantom/logs/ 和当前代码状态。"
  fi

  check_dependencies

else
  # ── 非 resume / 非 delete 路径：模式分派 ───────────────
  #
  # 两种大情况：
  #  (A) 当前目录已是 phantom 项目（state.json 存在）—— 继续操作已有项目
  #  (B) 当前目录不是 phantom 项目 —— 创建新项目

  EXISTING_STATE_FILE="$INVOKE_CWD/.phantom/state.json"

  if [[ -f "$EXISTING_STATE_FILE" ]]; then
    # ── (A) 已有项目：按模式分派 ────────────────────────
    PROJECT_DIR="$INVOKE_CWD"
    cd "$PROJECT_DIR"
    REQ_FILE=$(jq -r '.requirements_file' "$EXISTING_STATE_FILE" 2>/dev/null || echo "")

    # 自动路由：有字符串需求 + 无模式 → 默认 --plan 增量
    if [[ -z "$MODE" && -n "$REQ_INPUT" ]]; then
      if [[ -f "$REQ_INPUT" ]]; then
        log_error "当前目录已是 phantom 项目（state.json 存在）。用文件需求在已有项目上属于歧义：要覆盖还是增量？请显式用 --plan <file>。"
        exit 1
      fi
      MODE="plan"
      log_info "已有项目 + 字符串需求 → 默认进入 --plan 增量模式"
    fi

    if [[ -z "$MODE" ]]; then
      log_error "当前目录已是 phantom 项目。请用 --resume 继续中断流程，或指定模式 --plan / --design / --dev-test / --test。"
      exit 1
    fi

    # 各模式的前置条件校验
    case "$MODE" in
      design|dev-test|test)
        if [[ ! -f "$PROJECT_DIR/.phantom/plan.locked.md" ]]; then
          log_error "$MODE 模式需要 .phantom/plan.locked.md 已存在，请先跑 --plan 或无 flag 全流程"
          exit 1
        fi
        ;;
    esac
    if [[ "$MODE" == "test" ]]; then
      if [[ ! -f "$PROJECT_DIR/.phantom/runtime/backend.pid" ]]; then
        log_error "--test 模式需要 deploy 产物已在线（未找到 .phantom/runtime/backend.pid）。请先跑 --dev-test 完成一次部署。"
        exit 1
      fi
    fi

    # 把 REQ_INPUT 按模式转成对应的 handoff 文件
    if [[ -n "$REQ_INPUT" ]]; then
      local_text=""
      if [[ -f "$REQ_INPUT" ]]; then
        local_text="$(cat "$REQ_INPUT")"
      else
        local_text="$REQ_INPUT"
      fi
      case "$MODE" in
        plan|design)
          write_amendment "$local_text"
          log_info "增量需求已写入 .phantom/amendment.md"
          ;;
        dev-test)
          write_user_return_packet "$local_text"
          log_info "增量需求已写成 return-packet，dev 会优先消化"
          ;;
        test)
          printf '%s\n' "$local_text" > "$PROJECT_DIR/.phantom/test-extra-note.md"
          log_info "增量说明已写入 .phantom/test-extra-note.md"
          ;;
      esac
      unset local_text
    elif [[ "$MODE" == "plan" ]]; then
      # 无参数的 --plan 重跑：注入 synthetic refresh amendment 保护现有结构
      write_amendment "用户触发了无参数的 --plan 重跑（pure refresh）。

请读 .phantom/plan.locked.md 作为参考，对照 .phantom/changelog.md 的已完成 iterations，重写 plan.md：
- **保留**已有 feature-N slug 和编号；保留已有 group-N 编号和成员
- **保留**核心章节结构（产品目标 / Feature 列表 / API 约定 / 评分标准）
- 允许的改进范围：章节表述细化、示例补充、rubric 维度描述更准确
- **禁止**：新增 feature、删除 feature、改 feature 编号、调整 group 构成
- 本轮产出的 plan.md 与 plan.locked.md 的 feature/group 结构必须保持一一对应"
      log_info "无参 --plan：注入 synthetic refresh amendment（保留现有结构）"
    fi

    log_phase "Phantom AutoDev --$MODE"
    log_info "项目目录: $PROJECT_DIR"
    log_info "需求文档: $REQ_FILE"
    check_dependencies

  else
    # ── (B) 新项目：MODE 限制 + 初始化 ─────────────────
    if [[ -z "$REQ_INPUT" ]]; then
      log_error "新项目需要提供需求文档路径或需求文本"
      usage
      exit 1
    fi

    # 新项目不支持 design / dev-test / test 模式（需要已有 plan）
    case "$MODE" in
      design|dev-test|test)
        log_error "$MODE 模式不能用于新项目（需先跑 --plan 或无 flag 全流程生成 plan.locked.md）"
        exit 1
        ;;
    esac

    # 决定 PROJECT_DIR
    if [[ -z "$PROJECT_DIR" ]]; then
      PROJECT_DIR="$INVOKE_CWD"
      log_info "将在当前目录生成项目: $PROJECT_DIR"
    elif [[ "$PROJECT_DIR" != /* ]]; then
      PROJECT_DIR="$INVOKE_CWD/$PROJECT_DIR"
    fi

    mkdir -p "$PROJECT_DIR/.phantom"
    PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"

    # 判断是文件路径还是纯文本需求
    if [[ -f "$REQ_INPUT" ]]; then
      REQ_FILE="$(cd "$(dirname "$REQ_INPUT")" && pwd)/$(basename "$REQ_INPUT")"
    else
      REQ_TEXT="$REQ_INPUT"
      REQ_FILE="$PROJECT_DIR/.phantom/requirements.txt"
      printf '%s\n' "$REQ_TEXT" > "$REQ_FILE"
      log_info "需求文本已写入项目: $REQ_FILE"
    fi

    log_phase "Phantom AutoDev 启动（新项目）"
    log_info "需求文档: $REQ_FILE"
    log_info "项目目录: $PROJECT_DIR"
    [[ -n "$MODE" ]] && log_info "模式: --$MODE"
    check_dependencies

    cd "$PROJECT_DIR"

    if [[ ! -d .git ]]; then
      git init
      log_ok "Git 仓库已初始化"
    fi

    init_state "$REQ_FILE" "$PROJECT_DIR"
    log_ok "状态已初始化"
  fi
fi

# 端口不在这里分配；首次 run_dev_phase 时才调用 ensure_ports，分配后直接写死进代码

# ── 主循环（harness-v2 group-per-sprint） ──────────────

# 每 feature 的循环上限
DEV_MAX_ROUNDS=6
DEV_MIN_ROUNDS=2

if [[ "${PHANTOM_FAST:-0}" == "1" ]]; then
  DEV_MIN_ROUNDS=1
fi

# 单个 group 的完整 sprint：dev → code-review → deploy → test 循环
# group_line 格式："group-N:feature-1-slug,feature-2-slug,..."
# 直到 test 分数 ≥ 90 且轮数 ≥ min_rounds；失败上限 max_rounds
run_group_sprint() {
  local group_line="$1"
  local group_name="${group_line%%:*}"
  local features_csv="${group_line#*:}"
  log_phase "═══ Group sprint: ${group_name} (${features_csv}) ═══"

  # --test-only：先跑一次 test，pass 直接算 group 完成，fail 才进 dev 循环
  # 只在第一个 group 生效一次；test 失败后清标志，后续 group 走正常流程
  if [[ "${PHANTOM_TEST_ONLY:-0}" == "1" ]]; then
    log_phase "── ${group_name} test-first（--test-only）──"
    if run_test_phase "$PROJECT_DIR" "$features_csv"; then
      log_ok "group ${group_name} test 一次通过（--test-only），sprint 完成"
      unset PHANTOM_TEST_ONLY
      return 0
    fi
    log_warn "test-first 失败，进入正常 dev → code-review → deploy → test 循环"
    unset PHANTOM_TEST_ONLY
  fi

  local round=0
  while [[ $round -lt $DEV_MAX_ROUNDS ]]; do
    round=$((round + 1))
    log_phase "── ${group_name} round $round/$DEV_MAX_ROUNDS ──"

    # Dev：一次处理整组 feature
    if ! run_dev_phase "$PROJECT_DIR" "$features_csv"; then
      log_error "dev phase 失败"
      return 1
    fi

    # Code review
    if ! run_code_review_phase "$PROJECT_DIR" "$features_csv"; then
      log_warn "code-review reject，继续下一轮 dev"
      continue
    fi

    # Deploy
    if ! run_deploy_phase "$PROJECT_DIR" "$features_csv"; then
      log_warn "deploy 失败，继续下一轮 dev"
      continue
    fi

    # Test
    if ! run_test_phase "$PROJECT_DIR" "$features_csv"; then
      log_warn "test 分数 < 80 或失败，继续下一轮 dev"
      continue
    fi

    # Test 通过且达到 min_rounds → sprint 完成
    if [[ $round -ge $DEV_MIN_ROUNDS ]]; then
      log_ok "group ${group_name} sprint 完成（round=${round}）"
      return 0
    fi

    # --dev-test 模式（PHANTOM_NO_POLISH=1）：跑通就收手，不强制打磨
    if [[ "${PHANTOM_NO_POLISH:-0}" == "1" ]]; then
      log_ok "group ${group_name} sprint 完成（round=${round}，--dev-test 模式跳过打磨）"
      return 0
    fi

    log_info "test 通过但 round=${round} < min=${DEV_MIN_ROUNDS}，强制再跑一轮打磨"
    cat > "$RETURN_PACKET_FILE" <<EOF
---
return_from: test
iteration: $round
feature: $features_csv
triggered_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
---

## 为什么回来

Test 已通过但当前只跑了 ${round} 轮，未达 min_rounds=${DEV_MIN_ROUNDS}。这是**强制打磨轮**。

## 必修项（硬性，dev 必须全部修掉）

- [polish] 回头审视本组 feature（${features_csv}）的代码和测试，找 1-3 处可以提升的地方：
  - 错误处理是否覆盖完整？
  - 空态/加载态文案是否到位？
  - 日志字段是否齐全（request_id、耗时、状态）？
  - 单测覆盖的边界场景是否充分？
  至少做出 1 处改动并在 changelog.md 里写明。

## 建议项（软性）

- （无）

## 全量报告

- \`.phantom/test-report-iter${round}.md\`
EOF
  done

  # 达到 max rounds 仍未通过
  if [[ "${PHANTOM_STRICT:-0}" == "1" ]]; then
    log_error "group ${group_name} 达到 max_rounds=$DEV_MAX_ROUNDS 仍未通过（strict 模式）"
    return 1
  fi

  log_warn "group ${group_name} 达到 max_rounds 强制推进"
  # 标记组内所有 feature 为 forced
  local f
  while IFS= read -r f; do
    mark_forced_feature "$f"
  done < <(echo "$features_csv" | tr ',' '\n')
  return 0
}

# 生成 CLAUDE.md + cp 成 AGENTS.md
generate_docs() {
  log_info "生成 CLAUDE.md（将复制为 AGENTS.md）"
  local forced_note=""
  local forced_list
  forced_list=$(list_forced_features)
  if [[ -n "$forced_list" ]]; then
    forced_note="

**注意**：以下 feature 达到 max_rounds 被强制推进，产物可能不达标：
$(echo "$forced_list" | sed 's/^/- /')
"
  fi

  local init_prompt
  init_prompt="分析当前目录下的所有代码文件（忽略 node_modules/ / .git/ / .phantom/logs/），然后读 .phantom/plan.locked.md 和 .phantom/changelog.md 了解项目完整历史，最后用 Write 工具在当前目录创建 CLAUDE.md，涵盖：

1. 项目概述
2. 技术栈与目录结构
3. 关键文件职责
4. 如何运行 / 测试 / 部署
5. 开发规范
6. **未达标 feature（如有）**：${forced_note:-（无）}
7. **「项目历史与 AI 记忆」章节（必写）**——告诉未来读这个文件的 AI 助手：
   - 本项目由 phantom AutoDev 生成
   - \`.phantom/plan.locked.md\` 是原始完整规划
   - \`.phantom/changelog.md\` 是每轮 dev 的追加记录
   - \`.phantom/test-report-iter*.md\` 是每轮 test 的评分报告
   - \`.phantom/port\` 是本项目预分配端口
   - 修改前**应先读 plan.locked.md**

直接 Write 文件，不要在终端输出整篇。"

  (cd "$PROJECT_DIR" && claude -p --dangerously-skip-permissions "$init_prompt") \
    || log_warn "CLAUDE.md 生成失败"

  if [[ -f "$PROJECT_DIR/CLAUDE.md" ]]; then
    cp "$PROJECT_DIR/CLAUDE.md" "$PROJECT_DIR/AGENTS.md"
    log_ok "已生成 CLAUDE.md 和 AGENTS.md（字节级一致）"
  else
    log_warn "CLAUDE.md 未生成，跳过 AGENTS.md 复制"
  fi
}

# ── Group 循环（被 full 流程和 --dev-test 模式共用） ──
_run_group_sprint_loop() {
  local group_count feature_count
  group_count=$(count_groups)
  feature_count=$(count_features)
  log_info "计划中共 ${group_count} 个 group、${feature_count} 个 feature，开始 group-per-sprint 循环"

  local idx
  idx=$(get_current_group_index)
  while [[ $idx -lt $group_count ]]; do
    local group_line
    group_line=$(get_group_by_index "$idx")
    if [[ -z "$group_line" ]]; then
      log_error "无法取到第 $idx 个 group（idx 溢出）"
      return 1
    fi

    if ! run_group_sprint "$group_line"; then
      log_error "group sprint 失败：${group_line%%:*}"
      return 1
    fi

    advance_group_index
    idx=$(get_current_group_index)
  done
  return 0
}

_finalize_full_run() {
  log_phase "全部 feature sprint 完成！"
  log_ok "项目已就绪: $PROJECT_DIR"
  echo ""
  log_info "状态摘要:"
  jq '.phases' "$STATE_FILE"

  local forced
  forced=$(list_forced_features)
  if [[ -n "$forced" ]]; then
    log_warn "被强制推进的 feature（未达标）:"
    echo "$forced" | sed 's/^/  - /'
  fi

  generate_docs
}

run_all_phases() {
  local current_phase
  current_phase=$(get_state '.current_phase')

  case "${MODE:-}" in
    plan)
      # 只跑 plan R1→R2→R3→落锁，不进后续 phase
      log_info "MODE=plan：只跑 plan 模式"
      run_plan_phase "$PROJECT_DIR" || return 1
      clear_amendment
      log_ok "plan 模式完成，已落锁 .phantom/plan.locked.md"
      return 0
      ;;

    design)
      log_info "MODE=design：只跑 design 模式（design → design-review → design）"
      export PHANTOM_FORCE_UI_DESIGN=1
      run_ui_design_phase "$PROJECT_DIR" || log_warn "design 失败"
      clear_amendment
      log_ok "design 模式完成"
      return 0
      ;;

    dev-test)
      log_info "MODE=dev-test：跑 dev → code-review → deploy → test 循环（不强制打磨）"
      export PHANTOM_NO_POLISH=1

      if return_packet_exists; then
        # 用户通过 --dev-test "xxx" 提了增量需求 → 一次性 sprint 消化 return-packet
        # 不走 group 迭代（用户修改常跨 feature，不属于任何单一 group；current_group_index 不动）
        local all_features
        all_features=$(list_feature_groups_from_plan 2>/dev/null | awk -F: '{print $2}' | tr '\n' ',' | sed 's/,$//')
        [[ -z "$all_features" ]] && all_features="user-amendment"
        log_info "检测到 return-packet，对\"all features\"跑一次 sprint 以消化增量需求（不推进 group 指针）"
        run_group_sprint "user-amendment:$all_features" || return 1
        log_ok "dev-test 模式完成（用户增量已消化）"
        return 0
      fi

      # 无 amendment：从 current_group_index 继续剩余 group（等同旧 --skip-plan）
      if [[ "$(get_current_group_index)" -ge "$(count_groups)" ]]; then
        log_warn "所有 group 都已跑完且无 return-packet。要触发 dev 迭代请用 --dev-test \"<具体要修的事>\"。"
        return 0
      fi
      _run_group_sprint_loop || return 1
      _finalize_full_run
      return 0
      ;;

    test)
      log_info "MODE=test：只重跑 test 一节"
      run_test_only_phase "$PROJECT_DIR" || return 1
      return 0
      ;;

    ""|full)
      # 全流程（等同今天行为）
      if [[ "$current_phase" == "plan" ]]; then
        run_plan_phase "$PROJECT_DIR" || return 1
        set_state '.current_phase' '"dev"'
      fi

      run_ui_design_phase "$PROJECT_DIR" || log_warn "ui-design 失败，主流程继续"

      _run_group_sprint_loop || return 1
      _finalize_full_run
      return 0
      ;;

    *)
      log_error "未知模式: $MODE"
      return 1
      ;;
  esac
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
