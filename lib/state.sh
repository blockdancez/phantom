#!/usr/bin/env bash
# lib/state.sh - .phantom/state.json 状态管理

STATE_DIR=".phantom"
STATE_FILE="$STATE_DIR/state.json"
LOG_DIR="$STATE_DIR/logs"

# Handoff artifacts — Context Reset 模式下跨会话传递信息
PROGRESS_FILE="$STATE_DIR/progress.md"
OPEN_ISSUES_FILE="$STATE_DIR/open-issues.md"
FILE_MAP_FILE="$STATE_DIR/file-map.md"
LAST_REVIEW_FILE="$STATE_DIR/last-review.json"
PORT_FILE="$STATE_DIR/port"

# 分配一个空闲端口并持久化到 .phantom/port
# 已存在就直接读取；调用方可用 `export PORT=$(ensure_port)` 注入
ensure_port() {
  mkdir -p "$STATE_DIR"
  if [[ ! -s "$PORT_FILE" ]]; then
    python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()" > "$PORT_FILE"
  fi
  cat "$PORT_FILE"
}

ensure_handoff_files() {
  mkdir -p "$STATE_DIR"
  [[ -f "$PROGRESS_FILE" ]] || printf '# 进度\n\n（尚无已完成步骤）\n' > "$PROGRESS_FILE"
  [[ -f "$OPEN_ISSUES_FILE" ]] || printf '# 待解决问题\n\n（无）\n' > "$OPEN_ISSUES_FILE"
  [[ -f "$FILE_MAP_FILE" ]] || printf '# 关键文件索引\n\n（尚未生成）\n' > "$FILE_MAP_FILE"
  [[ -f "$LAST_REVIEW_FILE" ]] || printf '{"verdict":"none","failures":[],"evidence":[]}\n' > "$LAST_REVIEW_FILE"
}

reset_handoff_files() {
  rm -f "$PROGRESS_FILE" "$OPEN_ISSUES_FILE" "$FILE_MAP_FILE" "$LAST_REVIEW_FILE"
  ensure_handoff_files
}

init_state() {
  local requirements_file="$1"
  local project_dir="$2"
  mkdir -p "$STATE_DIR/logs"
  ensure_handoff_files
  cat > "$STATE_FILE" <<EOF
{
  "requirements_file": "$requirements_file",
  "project_dir": "$project_dir",
  "current_phase": "plan",
  "phases": {
    "plan":    { "status": "pending", "iteration": 0 },
    "devtest": { "status": "pending", "iteration": 0 },
    "deploy":  { "status": "pending", "iteration": 0 }
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
    plan)    next="devtest" ;;
    devtest) next="deploy" ;;
    deploy)  next="done" ;;
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

# ── Reviewer verdict / 校验 ──────────────────────────────

last_review_valid_json() {
  [[ -f "$LAST_REVIEW_FILE" ]] && jq empty "$LAST_REVIEW_FILE" 2>/dev/null
}

read_review_verdict() {
  if ! last_review_valid_json; then
    echo "invalid"
    return
  fi
  jq -r '.verdict // "none"' "$LAST_REVIEW_FILE" 2>/dev/null || echo "invalid"
}

reset_last_review() {
  printf '{"verdict":"none","failures":[],"evidence":[],"stage":""}\n' > "$LAST_REVIEW_FILE"
}

# ── Forced advance 标记（达到最大轮次但非 strict 模式时） ──

mark_forced_advance() {
  local phase="$1"
  set_state ".phases.${phase}.forced_advance" "true"
}

list_forced_phases() {
  jq -r '.phases | to_entries[] | select(.value.forced_advance == true) | .key' \
    "$STATE_FILE" 2>/dev/null
}
