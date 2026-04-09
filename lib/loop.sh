#!/usr/bin/env bash
# lib/loop.sh - Ralph-loop 循环引擎
#
# 核心原理：在同一个 Claude 会话中反复验证。
# 第一次调用启动新会话，后续用 -c 接续上一次会话。
# Claude 会自动压缩上下文，保持连续性。

source "$(dirname "${BASH_SOURCE[0]}")/utils.sh"
source "$(dirname "${BASH_SOURCE[0]}")/state.sh"

# 将模板中的占位符替换为实际内容，写入临时文件
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

  local req_tmp plan_tmp
  req_tmp=$(mktemp)
  plan_tmp=$(mktemp)
  printf '%s' "$requirements" > "$req_tmp"
  printf '%s' "$plan" > "$plan_tmp"

  python3 - "$template_file" "$req_tmp" "$plan_tmp" "$work_dir" "$output_file" <<'PYEOF'
import sys

template_path, req_path, plan_path, work_dir, out_path = sys.argv[1:]

with open(template_path, 'r') as f:
    content = f.read()
with open(req_path, 'r') as f:
    requirements = f.read()
with open(plan_path, 'r') as f:
    plan = f.read()

content = content.replace('{{REQUIREMENTS}}', requirements)
content = content.replace('{{PLAN}}', plan)
content = content.replace('{{PROJECT_DIR}}', work_dir)

with open(out_path, 'w') as f:
    f.write(content)
PYEOF

  rm -f "$req_tmp" "$plan_tmp"

  echo "$output_file"
}

STREAM_PARSER="$(dirname "${BASH_SOURCE[0]}")/stream-parser.py"

# 调用 Claude（新会话）— 流式输出到控制台，结果保存到日志文件
claude_new() {
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

# 调用 Claude（新会话，plan 模式）— Claude 先规划再执行
claude_new_plan() {
  local prompt="$1"
  local log_file="$2"

  claude -p \
    --dangerously-skip-permissions \
    --permission-mode plan \
    --output-format stream-json \
    --verbose \
    --include-partial-messages \
    "$prompt" \
    2>&1 | python3 "$STREAM_PARSER" "$log_file"
}

# 调用 Claude（接续上一次会话）
claude_continue() {
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

# 运行带实际验证的 Claude 循环
# 参数: phase, main_prompt, verify_prompt, max_checks, work_dir
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
      # 第一轮：执行主任务
      log_info "[$phase] 第 $iteration 轮 - 执行开发任务..."

      local prompt_file
      prompt_file=$(render_prompt "$main_prompt_file" "$work_dir")

      claude_continue "$(cat "$prompt_file")" "$log_file"

      rm -f "$prompt_file"
    else
      # 后续轮次：运行验证，发现问题就修复
      log_info "[$phase] 第 $iteration 轮 - 运行验证..."

      local verify_file
      verify_file=$(render_prompt "$verify_prompt_file" "$work_dir")

      claude_continue "$(cat "$verify_file")" "$log_file"

      rm -f "$verify_file"

      # 检查验证结果：通过即放行
      if grep -q "PHASE_COMPLETE" "$log_file"; then
        log_ok "[$phase] 验证通过，阶段完成!"
        return 0
      else
        log_warn "[$phase] 验证发现问题，Claude 已修复，将再次验证..."
      fi
    fi
  done

  log_warn "[$phase] 已达最大轮次 $max_checks，强制进入下一阶段"
  return 0
}
