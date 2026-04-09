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

# 运行带自验证的 Claude 循环
run_loop() {
  local phase="$1"
  local main_prompt_file="$2"
  local verify_prompt_file="$3"
  local min_checks="$4"
  local max_checks="$5"
  local work_dir="$6"

  local iteration=0
  local consecutive_done=0

  set_phase_status "$phase" "in_progress"

  log_phase "阶段: $phase (最少验证 $min_checks 次，最多 $max_checks 次)"

  while [[ $iteration -lt $max_checks ]]; do
    iteration=$((iteration + 1))
    increment_iteration "$phase"

    local log_file="$LOG_DIR/phase-${phase}-${iteration}.log"

    if [[ $iteration -eq 1 ]]; then
      # 第一次迭代：执行主任务
      log_info "[$phase] 迭代 $iteration/$max_checks - 执行主任务..."
      log_info "提示词模板: $main_prompt_file"

      local prompt_file
      prompt_file=$(render_prompt "$main_prompt_file" "$work_dir")

      claude_continue "$(cat "$prompt_file")" "$log_file"

      rm -f "$prompt_file"
    else
      # 后续迭代：在同一会话中验证 + 继续改进
      log_info "[$phase] 迭代 $iteration/$max_checks - 验证完成度..."
      log_info "提示词模板: $verify_prompt_file"

      local verify_file
      verify_file=$(render_prompt "$verify_prompt_file" "$work_dir")

      claude_continue "$(cat "$verify_file")" "$log_file"

      rm -f "$verify_file"

      # 从日志文件检查 Claude 是否确认完成
      if grep -q "PHASE_COMPLETE" "$log_file"; then
        consecutive_done=$((consecutive_done + 1))
        log_ok "[$phase] Claude 确认完成 ($consecutive_done/$min_checks 连续确认)"

        if [[ $consecutive_done -ge $min_checks ]]; then
          log_ok "[$phase] 达到最小验证次数，阶段完成!"
          return 0
        fi
      else
        consecutive_done=0
        log_warn "[$phase] Claude 认为还未完成，继续迭代..."
      fi
    fi
  done

  log_warn "[$phase] 已达最大迭代次数 $max_checks"
  return 0
}
