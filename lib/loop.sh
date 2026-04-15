#!/usr/bin/env bash
# lib/loop.sh - 模板渲染 + AI 后端抽象层（harness v2）
#
# Harness v2 关键变化：
# 1. 后端角色枚举扩展：generator / plan_reviewer / code_reviewer / tester / deploy
# 2. 强制跨模型（evaluator 角色默认选一个和 generator 不同的后端）
# 3. Compaction 支持：ai_run_continue 用 claude -c / codex resume --last 继续会话
# 4. Handoff 占位符扩展：{{PLAN_LOCKED}} {{RETURN_PACKET}} {{CHANGELOG}} {{FEATURE}}

source "$(dirname "${BASH_SOURCE[0]}")/utils.sh"
source "$(dirname "${BASH_SOURCE[0]}")/state.sh"

STREAM_PARSER="$(dirname "${BASH_SOURCE[0]}")/stream-parser.py"

# ── 模板渲染 ─────────────────────────────────────────────
# 占位符：
#   {{REQUIREMENTS}} {{PLAN_LOCKED}} {{PLAN}} {{CHANGELOG}} {{RETURN_PACKET}}
#   {{FEATURE}} {{EXTRA_NOTE}} {{PROJECT_DIR}} {{HOME}} {{PORT}}

render_prompt() {
  local template_file="$1"
  local work_dir="$2"
  local output_file
  output_file=$(mktemp)

  local state_req_file requirements="" plan="" plan_locked=""
  local changelog="" return_packet="" port=""
  state_req_file=$(get_state '.requirements_file')
  [[ -f "$state_req_file" ]]                  && requirements=$(cat "$state_req_file")
  [[ -f ".phantom/plan.md" ]]                 && plan=$(cat ".phantom/plan.md")
  [[ -f ".phantom/plan.locked.md" ]]          && plan_locked=$(cat ".phantom/plan.locked.md")
  [[ -f ".phantom/changelog.md" ]]            && changelog=$(cat ".phantom/changelog.md")
  [[ -f ".phantom/return-packet.md" ]]        && return_packet=$(cat ".phantom/return-packet.md")
  [[ -f ".phantom/port" ]]                    && port=$(cat ".phantom/port")

  TPL_REQUIREMENTS="$requirements" \
  TPL_PLAN="$plan" \
  TPL_PLAN_LOCKED="$plan_locked" \
  TPL_CHANGELOG="$changelog" \
  TPL_RETURN_PACKET="$return_packet" \
  TPL_FEATURE="${PHANTOM_FEATURE:-}" \
  TPL_EXTRA_NOTE="${PHANTOM_EXTRA_NOTE:-}" \
  TPL_PROJECT_DIR="$work_dir" \
  TPL_HOME="$HOME" \
  TPL_PORT="$port" \
  TPL_TEMPLATE="$template_file" \
  TPL_OUTPUT="$output_file" \
  python3 - <<'PYEOF'
import os
mapping = {
    '{{REQUIREMENTS}}':  os.environ['TPL_REQUIREMENTS'],
    '{{PLAN}}':          os.environ['TPL_PLAN'],
    '{{PLAN_LOCKED}}':   os.environ['TPL_PLAN_LOCKED'],
    '{{CHANGELOG}}':     os.environ['TPL_CHANGELOG'],
    '{{RETURN_PACKET}}': os.environ['TPL_RETURN_PACKET'],
    '{{FEATURE}}':       os.environ['TPL_FEATURE'],
    '{{EXTRA_NOTE}}':    os.environ['TPL_EXTRA_NOTE'],
    '{{PROJECT_DIR}}':   os.environ['TPL_PROJECT_DIR'],
    '{{HOME}}':          os.environ['TPL_HOME'],
    '{{PORT}}':          os.environ['TPL_PORT'],
}
content = open(os.environ['TPL_TEMPLATE']).read()
for k, v in mapping.items():
    content = content.replace(k, v)
with open(os.environ['TPL_OUTPUT'], 'w') as f:
    f.write(content)
PYEOF

  echo "$output_file"
}

# ── 后端选择 ─────────────────────────────────────────────
# 解析规则（每个角色独立）：
#   1. PHANTOM_<ROLE>_BACKEND（显式设置则尊重用户）
#   2. 若该角色在 CROSS_MODEL_ROLES 列表且用户没显式设置，强制选与 generator 不同的后端
#   3. PHANTOM_BACKEND
#   4. claude（默认）

# 哪些角色默认强制跨模型
CROSS_MODEL_ROLES=(plan_reviewer code_reviewer tester)

_is_cross_model_role() {
  local role="$1"
  local r
  for r in "${CROSS_MODEL_ROLES[@]}"; do
    [[ "$r" == "$role" ]] && return 0
  done
  return 1
}

_detect_available_backends() {
  local result=()
  command -v claude >/dev/null 2>&1 && result+=("claude")
  command -v codex  >/dev/null 2>&1 && result+=("codex")
  printf '%s\n' "${result[@]}"
}

resolve_backend() {
  local role="${1:-generator}"
  local upper var val
  upper=$(echo "$role" | tr '[:lower:]' '[:upper:]')
  upper=${upper//-/_}
  var="PHANTOM_${upper}_BACKEND"
  val="${!var:-}"

  if [[ -n "$val" ]]; then
    echo "$val"
    return
  fi

  if _is_cross_model_role "$role"; then
    # 尝试选一个和 generator 不同的后端
    local gen_backend other
    gen_backend=$(resolve_backend generator)
    while IFS= read -r other; do
      [[ -z "$other" ]] && continue
      if [[ "$other" != "$gen_backend" ]]; then
        echo "$other"
        return
      fi
    done < <(_detect_available_backends)
    # 只装一个后端 → 降级同 generator 并 warn（只 warn 一次避免刷屏）
    local warn_flag_var="_PHANTOM_CROSS_WARN_${upper}"
    if [[ -z "${!warn_flag_var:-}" ]]; then
      log_warn "角色 [$role] 需要跨模型但系统只装了一个后端，降级为 $gen_backend"
      export "$warn_flag_var=1"
    fi
    echo "$gen_backend"
    return
  fi

  echo "${PHANTOM_BACKEND:-claude}"
}

# 兼容旧名
get_backend() {
  resolve_backend "${1:-generator}"
}

# ── 后端执行函数 ─────────────────────────────────────────
# 每个后端有两个模式：new（新会话）/ continue（用 compaction 继续上一次会话）

_claude_run_new() {
  local prompt="$1" log_file="$2"
  claude -p \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    "$prompt" \
    2>&1 | python3 -u "$STREAM_PARSER" "$log_file"
}

_claude_run_continue() {
  local prompt="$1" log_file="$2"
  claude -c -p \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    "$prompt" \
    2>&1 | python3 -u "$STREAM_PARSER" "$log_file"
}

_codex_run_new() {
  local prompt="$1" log_file="$2"
  codex exec \
    --dangerously-bypass-approvals-and-sandbox \
    --json \
    -o "$log_file" \
    "$prompt" \
    2>&1 | python3 -u "$STREAM_PARSER" "$log_file" codex
}

_codex_run_continue() {
  local prompt="$1" log_file="$2"
  codex exec resume --last \
    --dangerously-bypass-approvals-and-sandbox \
    --json \
    -o "$log_file" \
    "$prompt" \
    2>&1 | python3 -u "$STREAM_PARSER" "$log_file" codex
}

# ── 统一调用接口 ────────────────────────────────────────
#
# ai_run <role> <prompt> <log_file>
#   首次（会话不存在）→ 后端 new；否则 → 后端 continue（compaction）
#
# 每个 role 维护一个"是否已开始会话"的状态，存在 .phantom/sessions/ 下
# 重置某个 role 的会话：rm .phantom/sessions/<role>

_session_flag_file() {
  local role="$1"
  local backend="$2"
  mkdir -p "$STATE_DIR/sessions"
  echo "$STATE_DIR/sessions/${role}-${backend}"
}

# 标记 role+backend 的会话已启动
_mark_session_started() {
  local role="$1" backend="$2"
  touch "$(_session_flag_file "$role" "$backend")"
}

# 检查 role+backend 会话是否已启动
_session_started() {
  local role="$1" backend="$2"
  [[ -f "$(_session_flag_file "$role" "$backend")" ]]
}

# 重置某个 role 的所有会话标记（例如 feature-per-sprint 跨 feature 时可选）
reset_session_flags() {
  local role="$1"
  rm -f "$STATE_DIR/sessions/${role}-"* 2>/dev/null || true
}

ai_run() {
  local role="$1" prompt="$2" log_file="$3"
  local b
  b=$(resolve_backend "$role")

  local mode="new"
  if _session_started "$role" "$b"; then
    mode="continue"
  fi

  log_info "→ $role ($b, $mode)  开始调用，首次输出可能需要 10-30 秒"

  case "$b" in
    claude)
      if [[ "$mode" == "new" ]]; then
        _claude_run_new "$prompt" "$log_file"
      else
        _claude_run_continue "$prompt" "$log_file"
      fi
      ;;
    codex)
      if [[ "$mode" == "new" ]]; then
        _codex_run_new "$prompt" "$log_file"
      else
        _codex_run_continue "$prompt" "$log_file"
      fi
      ;;
    *)
      log_error "不支持的后端: $b"
      return 1
      ;;
  esac

  local rc=$?
  _mark_session_started "$role" "$b"
  return $rc
}

# 一次性调用（不使用 compaction）——用于 plan phase 的 R1/R2/R3 短会话
ai_run_oneshot() {
  local role="$1" prompt="$2" log_file="$3"
  local b
  b=$(resolve_backend "$role")
  log_info "→ $role ($b)  开始调用，首次输出可能需要 10-30 秒"
  case "$b" in
    claude) _claude_run_new "$prompt" "$log_file" ;;
    codex)  _codex_run_new  "$prompt" "$log_file" ;;
    *) log_error "不支持的后端: $b"; return 1 ;;
  esac
}
