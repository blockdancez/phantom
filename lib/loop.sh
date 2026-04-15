#!/usr/bin/env bash
# lib/loop.sh - 模板渲染 + AI 后端抽象层（角色化）
#
# 后端选择优先级（每个角色独立）：
#   PHANTOM_<ROLE>_BACKEND  →  PHANTOM_BACKEND  →  claude
# 角色：generator | reviewer | plan | deploy

source "$(dirname "${BASH_SOURCE[0]}")/utils.sh"
source "$(dirname "${BASH_SOURCE[0]}")/state.sh"

STREAM_PARSER="$(dirname "${BASH_SOURCE[0]}")/stream-parser.py"

# ── 模板渲染 ─────────────────────────────────────────────
# 占位符：{{REQUIREMENTS}} {{PLAN}} {{PROGRESS}} {{OPEN_ISSUES}}
#        {{FILE_MAP}} {{LAST_REVIEW}} {{REVIEW_STAGE}} {{EXTRA_NOTE}}
#        {{PROJECT_DIR}} {{HOME}}

render_prompt() {
  local template_file="$1"
  local work_dir="$2"
  local output_file
  output_file=$(mktemp)

  local state_req_file requirements="" plan=""
  local progress="" open_issues="" file_map="" last_review=""
  state_req_file=$(get_state '.requirements_file')
  [[ -f "$state_req_file" ]]           && requirements=$(cat "$state_req_file")
  [[ -f ".phantom/plan.md" ]]          && plan=$(cat ".phantom/plan.md")
  [[ -f ".phantom/progress.md" ]]      && progress=$(cat ".phantom/progress.md")
  [[ -f ".phantom/open-issues.md" ]]   && open_issues=$(cat ".phantom/open-issues.md")
  [[ -f ".phantom/file-map.md" ]]      && file_map=$(cat ".phantom/file-map.md")
  [[ -f ".phantom/last-review.json" ]] && last_review=$(cat ".phantom/last-review.json")

  TPL_REQUIREMENTS="$requirements" \
  TPL_PLAN="$plan" \
  TPL_PROGRESS="$progress" \
  TPL_OPEN_ISSUES="$open_issues" \
  TPL_FILE_MAP="$file_map" \
  TPL_LAST_REVIEW="$last_review" \
  TPL_REVIEW_STAGE="${PHANTOM_REVIEW_STAGE:-}" \
  TPL_EXTRA_NOTE="${PHANTOM_EXTRA_NOTE:-}" \
  TPL_PROJECT_DIR="$work_dir" \
  TPL_HOME="$HOME" \
  TPL_TEMPLATE="$template_file" \
  TPL_OUTPUT="$output_file" \
  python3 - <<'PYEOF'
import os
mapping = {
    '{{REQUIREMENTS}}': os.environ['TPL_REQUIREMENTS'],
    '{{PLAN}}':         os.environ['TPL_PLAN'],
    '{{PROGRESS}}':     os.environ['TPL_PROGRESS'],
    '{{OPEN_ISSUES}}':  os.environ['TPL_OPEN_ISSUES'],
    '{{FILE_MAP}}':     os.environ['TPL_FILE_MAP'],
    '{{LAST_REVIEW}}':  os.environ['TPL_LAST_REVIEW'],
    '{{REVIEW_STAGE}}': os.environ['TPL_REVIEW_STAGE'],
    '{{EXTRA_NOTE}}':   os.environ['TPL_EXTRA_NOTE'],
    '{{PROJECT_DIR}}':  os.environ['TPL_PROJECT_DIR'],
    '{{HOME}}':         os.environ['TPL_HOME'],
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

resolve_backend() {
  local role="${1:-generator}"
  local upper var val
  upper=$(echo "$role" | tr '[:lower:]' '[:upper:]')
  var="PHANTOM_${upper}_BACKEND"
  val="${!var:-}"
  [[ -z "$val" ]] && val="${PHANTOM_BACKEND:-claude}"
  echo "$val"
}

# 兼容旧名（phantom.sh 末尾用 get_backend 输出 init 提示）
get_backend() {
  resolve_backend "${1:-generator}"
}

# ── 单一后端执行函数（每个后端只有一份） ────────────────

_claude_run() {
  local prompt="$1" log_file="$2"
  claude -p \
    --dangerously-skip-permissions \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file"
}

_codex_run() {
  local prompt="$1" log_file="$2"
  codex exec \
    --dangerously-bypass-approvals-and-sandbox \
    --json \
    -o "$log_file" \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file" codex
}

# ── 统一调用接口 ────────────────────────────────────────
# ai_run <role> <prompt> <log_file>

ai_run() {
  local role="$1" prompt="$2" log_file="$3"
  local b
  b=$(resolve_backend "$role")
  log_info "后端[$role]: $b"
  case "$b" in
    claude) _claude_run "$prompt" "$log_file" ;;
    codex)  _codex_run  "$prompt" "$log_file" ;;
    *) log_error "不支持的后端: $b"; return 1 ;;
  esac
}

# Plan 阶段：codex 没有原生 plan 模式，注入英文规划指令
ai_run_plan() {
  local prompt="$1" log_file="$2"
  local b
  b=$(resolve_backend "plan")
  log_info "后端[plan]: $b"
  case "$b" in
    claude)
      _claude_run "$prompt" "$log_file"
      ;;
    codex)
      local plan_prompt="Please first create a detailed plan, then write it to .phantom/plan.md before doing anything else.

$prompt"
      _codex_run "$plan_prompt" "$log_file"
      ;;
    *) log_error "不支持的后端: $b"; return 1 ;;
  esac
}
