#!/usr/bin/env bash
# lib/loop.sh - 循环引擎 + AI 后端抽象层
#
# 支持多种 AI CLI 后端（Claude Code / Codex）
# 通过环境变量 PHANTOM_BACKEND 切换，默认自动检测

source "$(dirname "${BASH_SOURCE[0]}")/utils.sh"
source "$(dirname "${BASH_SOURCE[0]}")/state.sh"

# ── 模板渲染 ─────────────────────────────────────────────

render_prompt() {
  local template_file="$1"
  local work_dir="$2"
  local output_file
  output_file=$(mktemp)

  local state_req_file
  state_req_file=$(get_state '.requirements_file')
  local requirements=""
  [[ -f "$state_req_file" ]] && requirements=$(cat "$state_req_file")

  local plan=""
  [[ -f ".phantom/plan.md" ]] && plan=$(cat ".phantom/plan.md")

  # Handoff artifacts (Context Reset 模式)
  local progress="" open_issues="" file_map="" last_review=""
  [[ -f ".phantom/progress.md" ]]     && progress=$(cat ".phantom/progress.md")
  [[ -f ".phantom/open-issues.md" ]]  && open_issues=$(cat ".phantom/open-issues.md")
  [[ -f ".phantom/file-map.md" ]]     && file_map=$(cat ".phantom/file-map.md")
  [[ -f ".phantom/last-review.json" ]] && last_review=$(cat ".phantom/last-review.json")

  local req_tmp plan_tmp prog_tmp issues_tmp map_tmp review_tmp
  req_tmp=$(mktemp)
  plan_tmp=$(mktemp)
  prog_tmp=$(mktemp)
  issues_tmp=$(mktemp)
  map_tmp=$(mktemp)
  review_tmp=$(mktemp)
  printf '%s' "$requirements" > "$req_tmp"
  printf '%s' "$plan" > "$plan_tmp"
  printf '%s' "$progress" > "$prog_tmp"
  printf '%s' "$open_issues" > "$issues_tmp"
  printf '%s' "$file_map" > "$map_tmp"
  printf '%s' "$last_review" > "$review_tmp"

  python3 - "$template_file" "$req_tmp" "$plan_tmp" "$work_dir" "$output_file" \
    "$prog_tmp" "$issues_tmp" "$map_tmp" "$review_tmp" <<'PYEOF'
import sys, os

(template_path, req_path, plan_path, work_dir, out_path,
 prog_path, issues_path, map_path, review_path) = sys.argv[1:]

def read(p):
    with open(p, 'r') as f:
        return f.read()

content = read(template_path)
content = content.replace('{{REQUIREMENTS}}', read(req_path))
content = content.replace('{{PLAN}}', read(plan_path))
content = content.replace('{{PROGRESS}}', read(prog_path))
content = content.replace('{{OPEN_ISSUES}}', read(issues_path))
content = content.replace('{{FILE_MAP}}', read(map_path))
content = content.replace('{{LAST_REVIEW}}', read(review_path))
content = content.replace('{{PROJECT_DIR}}', work_dir)
content = content.replace('{{HOME}}', os.path.expanduser('~'))

with open(out_path, 'w') as f:
    f.write(content)
PYEOF

  rm -f "$req_tmp" "$plan_tmp" "$prog_tmp" "$issues_tmp" "$map_tmp" "$review_tmp"

  echo "$output_file"
}

# ── AI 后端抽象层 ────────────────────────────────────────

STREAM_PARSER="$(dirname "${BASH_SOURCE[0]}")/stream-parser.py"

# 获取后端（延迟检测，默认 claude）
get_backend() {
  echo "${PHANTOM_BACKEND:-claude}"
}

# ── Claude Code 后端 ─────────────────────────────────────

_claude_new() {
  local prompt="$1"
  local log_file="$2"

  claude -p \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file"
}

_claude_new_plan() {
  # 规划方法论已写入 prompts/plan.md，直接执行即可
  _claude_new "$@"
}

_claude_continue() {
  local prompt="$1"
  local log_file="$2"

  claude -p -c \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file"
}

# Fresh context — 不带 -c，每次都是干净会话
# 用于 Generator/Evaluator 分离 + Context Reset 模式
_claude_fresh() {
  local prompt="$1"
  local log_file="$2"

  claude -p \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file"
}

# ── Codex 后端 ───────────────────────────────────────────

_codex_new() {
  local prompt="$1"
  local log_file="$2"

  codex exec \
    --dangerously-bypass-approvals-and-sandbox \
    --json \
    -o "$log_file" \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file" codex
}

_codex_new_plan() {
  # Codex 没有 plan 模式，在提示词前加规划指令
  local prompt="$1"
  local log_file="$2"
  local plan_prompt="Please first create a detailed plan, then execute it step by step.

$prompt"

  codex exec \
    --dangerously-bypass-approvals-and-sandbox \
    --json \
    -o "$log_file" \
    "$plan_prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file" codex
}

_codex_continue() {
  local prompt="$1"
  local log_file="$2"

  codex exec resume --last \
    --dangerously-bypass-approvals-and-sandbox \
    --json \
    -o "$log_file" \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file" codex
}

# Fresh context for Codex — 不 resume，每次干净会话
_codex_fresh() {
  local prompt="$1"
  local log_file="$2"

  codex exec \
    --dangerously-bypass-approvals-and-sandbox \
    --json \
    -o "$log_file" \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file" codex
}

# ── 统一接口 ─────────────────────────────────────────────

ai_new() {
  local b=$(get_backend)
  log_info "后端: $b"
  case "$b" in
    claude) _claude_new "$@" ;;
    codex)  _codex_new "$@" ;;
    *) log_error "不支持的后端: $b"; exit 1 ;;
  esac
}

ai_new_plan() {
  local b=$(get_backend)
  log_info "后端: $b (plan 模式)"
  case "$b" in
    claude) _claude_new_plan "$@" ;;
    codex)  _codex_new_plan "$@" ;;
    *) log_error "不支持的后端: $b"; exit 1 ;;
  esac
}

ai_continue() {
  local b=$(get_backend)
  case "$b" in
    claude) _claude_continue "$@" ;;
    codex)  _codex_continue "$@" ;;
    *) log_error "不支持的后端: $b"; exit 1 ;;
  esac
}

# 干净上下文调用 — 用于 Context Reset + 独立 Reviewer
ai_fresh() {
  local b=$(get_backend)
  case "$b" in
    claude) _claude_fresh "$@" ;;
    codex)  _codex_fresh "$@" ;;
    *) log_error "不支持的后端: $b"; exit 1 ;;
  esac
}

# ── 循环引擎 ─────────────────────────────────────────────

run_loop() {
  local phase="$1"
  local main_prompt_file="$2"
  local verify_prompt_file="$3"
  local max_checks="$4"
  local work_dir="$5"

  local iteration=0

  set_phase_status "$phase" "in_progress"

  log_phase "阶段: $phase (最多 $max_checks 轮)"

  while [[ $iteration -lt $max_checks ]]; do
    iteration=$((iteration + 1))
    increment_iteration "$phase"

    local log_file="$LOG_DIR/phase-${phase}-${iteration}.log"

    if [[ $iteration -eq 1 ]]; then
      log_info "[$phase] 第 $iteration 轮 - 执行开发任务..."

      local prompt_file
      prompt_file=$(render_prompt "$main_prompt_file" "$work_dir")

      ai_continue "$(cat "$prompt_file")" "$log_file"

      rm -f "$prompt_file"
    else
      log_info "[$phase] 第 $iteration 轮 - 运行验证..."

      local verify_file
      verify_file=$(render_prompt "$verify_prompt_file" "$work_dir")

      ai_continue "$(cat "$verify_file")" "$log_file"

      rm -f "$verify_file"

      if grep -q "PHASE_COMPLETE" "$log_file"; then
        log_ok "[$phase] 验证通过，阶段完成!"
        return 0
      else
        log_warn "[$phase] 验证发现问题，已修复，将再次验证..."
      fi
    fi
  done

  log_warn "[$phase] 已达最大轮次 $max_checks，强制进入下一阶段"
  return 0
}
