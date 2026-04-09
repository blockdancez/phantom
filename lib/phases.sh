#!/usr/bin/env bash
# lib/phases.sh - 各阶段执行逻辑

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/state.sh"
source "$SCRIPT_DIR/lib/loop.sh"

# 阶段 1：规划（启动新会话，后续阶段用 -c 接续）
run_plan_phase() {
  local work_dir="$1"
  log_phase "阶段 1/4: 需求分析与计划制定"

  log_info "正在分析需求并制定计划..."

  local prompt_file
  prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/plan.md" "$work_dir")

  claude_new "$(cat "$prompt_file")" "$LOG_DIR/phase-plan-1.log"

  rm -f "$prompt_file"

  # 验证计划文件已生成
  if [[ -f ".phantom/plan.md" ]]; then
    log_ok "计划已生成: .phantom/plan.md"
    set_phase_status "plan" "completed"
    advance_phase
  else
    log_error "计划文件未生成，重试..."
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/plan.md" "$work_dir")
    claude_continue "$(cat "$prompt_file")" "$LOG_DIR/phase-plan-2.log"
    rm -f "$prompt_file"
    if [[ -f ".phantom/plan.md" ]]; then
      log_ok "计划已生成: .phantom/plan.md"
      set_phase_status "plan" "completed"
      advance_phase
    else
      log_error "计划生成失败"
      exit 1
    fi
  fi
}

# 阶段 2：开发（Ralph-loop，最少10次验证，最多50次）
run_dev_phase() {
  local work_dir="$1"
  log_phase "阶段 2/4: 代码开发"

  run_loop "dev" \
    "$SCRIPT_DIR/prompts/develop.md" \
    "$SCRIPT_DIR/prompts/verify-dev.md" \
    10 50 "$work_dir"

  advance_phase
}

# 阶段 3：测试（Ralph-loop，最少2次验证，最多5次）
run_test_phase() {
  local work_dir="$1"
  log_phase "阶段 3/4: 测试验证"

  run_loop "test" \
    "$SCRIPT_DIR/prompts/test.md" \
    "$SCRIPT_DIR/prompts/verify-test.md" \
    2 5 "$work_dir"

  advance_phase
}

# 阶段 4：Docker 部署
run_deploy_phase() {
  local work_dir="$1"
  log_phase "阶段 4/4: Docker 构建与部署验证"

  local max_attempts=3
  local attempt=0

  while [[ $attempt -lt $max_attempts ]]; do
    attempt=$((attempt + 1))
    log_info "Docker 部署尝试 $attempt/$max_attempts..."

    local prompt_file
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/deploy.md" "$work_dir")

    claude_continue "$(cat "$prompt_file")" "$LOG_DIR/phase-deploy-${attempt}.log"

    rm -f "$prompt_file"

    if grep -qi "PHASE_COMPLETE" "$LOG_DIR/phase-deploy-${attempt}.log"; then
      log_ok "Docker 部署验证成功!"
      set_phase_status "deploy" "completed"
      advance_phase
      return 0
    fi

    log_warn "部署未成功，重试..."
  done

  log_error "Docker 部署在 $max_attempts 次尝试后仍未成功"
  set_phase_status "deploy" "failed"
  return 1
}
