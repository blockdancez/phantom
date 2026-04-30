#!/usr/bin/env bash
# lib/state.sh - .phantom/state.json 状态管理（harness v2）

STATE_DIR=".phantom"
STATE_FILE="$STATE_DIR/state.json"
LOG_DIR="$STATE_DIR/logs"

# Handoff artifacts（harness v2：compaction + return-packet 模式）
PLAN_FILE="$STATE_DIR/plan.md"                          # Phase 1 工作文件
PLAN_LOCKED_FILE="$STATE_DIR/plan.locked.md"            # Phase 1 冻结版，主循环读
PLAN_REVIEW_COMMENTS_FILE="$STATE_DIR/plan-review-comments.md"
CHANGELOG_FILE="$STATE_DIR/changelog.md"                # dev 每轮追加
RETURN_PACKET_FILE="$STATE_DIR/return-packet.md"        # 当前回流包
LAST_CODE_REVIEW_FILE="$STATE_DIR/last-code-review.json"
BACKEND_PORT_FILE="$STATE_DIR/port.backend"
FRONTEND_PORT_FILE="$STATE_DIR/port.frontend"
RUNTIME_DIR="$STATE_DIR/runtime"                        # 本地运行时：PID + 日志
UI_DESIGN_FILE="$STATE_DIR/ui-design.md"                # UI design 总览（含 project_id / screen 列表）
UI_DESIGN_DIR="$STATE_DIR/ui-design"                    # 每个 screen 的 HTML/JSON 落盘目录
UI_DESIGN_REVIEW_COMMENTS_FILE="$STATE_DIR/ui-design-review-comments.md"  # design R2 产物
AMENDMENT_FILE="$STATE_DIR/amendment.md"                # --plan/--design "xxx" 注入的增量需求文本

# ── 端口预分配 ──────────────────────────────────────────

# 分配一个空闲端口到指定文件（如果文件不存在或为空）
_allocate_port_to() {
  local target="$1"
  [[ -s "$target" ]] && return 0
  mkdir -p "$(dirname "$target")"
  python3 -c "import socket;s=socket.socket();s.bind(('',0));print(s.getsockname()[1]);s.close()" > "$target"
}

# 确保 backend 端口已分配，返回端口号
ensure_backend_port() {
  mkdir -p "$STATE_DIR"
  _allocate_port_to "$BACKEND_PORT_FILE"
  cat "$BACKEND_PORT_FILE"
}

# 确保 frontend 端口已分配，返回端口号
ensure_frontend_port() {
  mkdir -p "$STATE_DIR"
  _allocate_port_to "$FRONTEND_PORT_FILE"
  cat "$FRONTEND_PORT_FILE"
}

# 一次性分配两个端口（首次 dev phase 调用，已分配则幂等跳过）
ensure_ports() {
  ensure_backend_port >/dev/null
  ensure_frontend_port >/dev/null
}

# ── 初始化 ──────────────────────────────────────────────

init_state() {
  local requirements_file="$1"
  local project_dir="$2"
  mkdir -p "$STATE_DIR/logs"
  cat > "$STATE_FILE" <<EOF
{
  "requirements_file": "$requirements_file",
  "project_dir": "$project_dir",
  "current_phase": "plan",
  "current_group_index": 0,
  "phases": {
    "plan":        { "status": "pending", "iteration": 0 },
    "ui_design":   { "status": "pending", "iteration": 0 },
    "dev":         { "status": "pending", "iteration": 0 },
    "code_review": { "status": "pending", "iteration": 0 },
    "deploy":      { "status": "pending", "iteration": 0 },
    "test":        { "status": "pending", "iteration": 0, "forced_features": [] }
  },
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
  [[ -f "$CHANGELOG_FILE" ]] || printf '# Phantom Dev Changelog\n\n' > "$CHANGELOG_FILE"
}

# ── 基础读写 ──────────────────────────────────────────

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

state_exists() {
  [[ -f "$STATE_FILE" ]]
}

# ── Phase 与迭代 ──────────────────────────────────────

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

# ── Group 索引（group-per-sprint） ─────────────

get_current_group_index() {
  local val
  val=$(get_state '.current_group_index // 0')
  echo "${val:-0}"
}

advance_group_index() {
  local current
  current=$(get_current_group_index)
  set_state '.current_group_index' "$((current + 1))"
}

# ── Return packet 校验 ─────────────────────────────

return_packet_exists() {
  [[ -f "$RETURN_PACKET_FILE" && -s "$RETURN_PACKET_FILE" ]]
}

# 校验 return-packet.md 的 front-matter 与必修项
# 返回 0 合法，1 不合法
validate_return_packet() {
  [[ -f "$RETURN_PACKET_FILE" ]] || return 1
  grep -q '^return_from:' "$RETURN_PACKET_FILE" || return 1
  grep -q '^iteration:' "$RETURN_PACKET_FILE" || return 1
  grep -q '^feature:' "$RETURN_PACKET_FILE" || return 1
  grep -q '## 必修项' "$RETURN_PACKET_FILE" || return 1
  # 必修项必须至少有一条非空条目
  awk '
    /^## 必修项/ { in_section=1; next }
    /^## / { in_section=0 }
    in_section && /^- / { found=1 }
    END { exit (found ? 0 : 1) }
  ' "$RETURN_PACKET_FILE"
}

# 归档当前 return-packet 到 logs/return-packet-iter<N>.md
archive_return_packet() {
  local iter="$1"
  [[ -f "$RETURN_PACKET_FILE" ]] || return 0
  mkdir -p "$LOG_DIR"
  cp "$RETURN_PACKET_FILE" "$LOG_DIR/return-packet-iter${iter}.md"
}

# ── Code-review verdict ─────────────────────────────

last_code_review_valid_json() {
  [[ -f "$LAST_CODE_REVIEW_FILE" ]] && jq empty "$LAST_CODE_REVIEW_FILE" 2>/dev/null
}

read_code_review_verdict() {
  if ! last_code_review_valid_json; then
    echo "invalid"
    return
  fi
  jq -r '.verdict // "none"' "$LAST_CODE_REVIEW_FILE" 2>/dev/null || echo "invalid"
}

reset_last_code_review() {
  printf '{"verdict":"none","issues":[]}\n' > "$LAST_CODE_REVIEW_FILE"
}

# ── Forced advance 标记（达到最大轮次但非 strict 模式时） ──

mark_forced_feature() {
  local feature_slug="$1"
  local tmp
  tmp=$(mktemp)
  jq --arg f "$feature_slug" '.phases.test.forced_features += [$f]' "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
}

list_forced_features() {
  jq -r '.phases.test.forced_features[]?' "$STATE_FILE" 2>/dev/null
}

# ── Amendment（增量需求文本，--plan/--design "xxx" 注入） ──

# 把字符串写入 .phantom/amendment.md，供 render_prompt 注 {{AMENDMENT}} 占位符
write_amendment() {
  local text="$1"
  mkdir -p "$STATE_DIR"
  printf '%s\n' "$text" > "$AMENDMENT_FILE"
}

has_amendment() {
  [[ -f "$AMENDMENT_FILE" && -s "$AMENDMENT_FILE" ]]
}

# 模式跑完后清空（防止跨模式泄漏）
clear_amendment() {
  rm -f "$AMENDMENT_FILE"
}

# 用户通过 --dev-test "xxx" 提出的修改请求：构造成 return-packet 让 dev 当成"必修项"消化
write_user_return_packet() {
  local text="$1"
  mkdir -p "$STATE_DIR"
  local iter
  iter=$(get_state '.phases.dev.iteration' 2>/dev/null || echo 0)
  local ts
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  cat > "$RETURN_PACKET_FILE" <<EOF
---
return_from: user-amendment
iteration: $iter
feature: user-requested
triggered_at: $ts
---

## 为什么回来

用户通过 \`phantom --dev-test\` 提出了针对现有实现的修改请求。请把本条需求视作**最高优先级必修项**，在当前 round 完成。

## 必修项（硬性，dev 必须全部修掉）

- $text

## 建议项（软性，dev 自行判断改不改）

- （无）

## 全量报告

（用户直接给出需求，无前置报告）
EOF
}
