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
