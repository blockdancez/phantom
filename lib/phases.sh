#!/usr/bin/env bash
# lib/phases.sh - 各阶段执行逻辑

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/state.sh"
source "$SCRIPT_DIR/lib/loop.sh"

# 阶段 1：规划（使用 Plan 模式，先规划再执行）
run_plan_phase() {
  local work_dir="$1"
  log_phase "阶段 1/3: 需求分析与计划制定 (Plan 模式)"

  log_info "正在使用 Plan 模式分析需求并制定计划..."

  local prompt_file
  prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/plan.md" "$work_dir")

  ai_new_plan "$(cat "$prompt_file")" "$LOG_DIR/phase-plan-1.log"

  rm -f "$prompt_file"

  # 验证计划文件已生成
  if [[ -f ".phantom/plan.md" ]]; then
    log_ok "计划已生成: .phantom/plan.md"
    set_phase_status "plan" "completed"
    advance_phase
  else
    log_error "计划文件未生成，重试..."
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/plan.md" "$work_dir")
    ai_new_plan "$(cat "$prompt_file")" "$LOG_DIR/phase-plan-2.log"
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

# 阶段 2：开发-测试循环
# 流程：开发 → 验证开发 → 测试 → 验证测试 → 失败则修复 → 重新测试
run_devtest_phase() {
  local work_dir="$1"
  local max_cycles=10
  local cycle=0

  log_phase "阶段 2/3: 开发-测试循环 (最多 $max_cycles 轮)"

  set_phase_status "devtest" "in_progress"

  # ── 第一步：开发代码 ──
  log_info "[dev] 开始代码开发..."
  local prompt_file
  prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/develop.md" "$work_dir")
  ai_continue "$(cat "$prompt_file")" "$LOG_DIR/phase-devtest-dev-1.log"
  rm -f "$prompt_file"

  # ── 第二步：验证开发 ──
  local dev_verified=false
  local dev_round=0
  local dev_max=10

  while [[ "$dev_verified" == false ]] && [[ $dev_round -lt $dev_max ]]; do
    dev_round=$((dev_round + 1))
    log_info "[dev] 验证开发 (第 $dev_round 轮)..."

    local verify_file
    verify_file=$(render_prompt "$SCRIPT_DIR/prompts/verify-dev.md" "$work_dir")
    ai_continue "$(cat "$verify_file")" "$LOG_DIR/phase-devtest-verify-dev-${dev_round}.log"
    rm -f "$verify_file"

    if grep -q "PHASE_COMPLETE" "$LOG_DIR/phase-devtest-verify-dev-${dev_round}.log"; then
      log_ok "[dev] 开发验证通过!"
      dev_verified=true
    else
      log_warn "[dev] 验证发现问题，已修复，再次验证..."
    fi
  done

  # ── 第三步：开发-测试循环 ──
  while [[ $cycle -lt $max_cycles ]]; do
    cycle=$((cycle + 1))
    increment_iteration "devtest"

    log_phase "开发-测试循环 第 $cycle/$max_cycles 轮"

    # 编写并运行测试
    log_info "[test] 编写并运行测试..."
    local test_file
    test_file=$(render_prompt "$SCRIPT_DIR/prompts/test.md" "$work_dir")
    ai_continue "$(cat "$test_file")" "$LOG_DIR/phase-devtest-test-${cycle}.log"
    rm -f "$test_file"

    # 验证测试结果
    log_info "[test] 验证测试结果..."
    local verify_test_file
    verify_test_file=$(render_prompt "$SCRIPT_DIR/prompts/verify-test.md" "$work_dir")
    ai_continue "$(cat "$verify_test_file")" "$LOG_DIR/phase-devtest-verify-test-${cycle}.log"
    rm -f "$verify_test_file"

    if grep -q "PHASE_COMPLETE" "$LOG_DIR/phase-devtest-verify-test-${cycle}.log"; then
      log_ok "[test] 所有测试通过! 开发-测试循环完成"
      set_phase_status "devtest" "completed"
      advance_phase
      return 0
    fi

    # 测试失败 → 修复代码 → 重新测试
    log_warn "[test] 测试未通过，返回修复代码..."
    local fix_file
    fix_file=$(render_prompt "$SCRIPT_DIR/prompts/fix-from-test.md" "$work_dir")
    ai_continue "$(cat "$fix_file")" "$LOG_DIR/phase-devtest-fix-${cycle}.log"
    rm -f "$fix_file"
  done

  log_warn "[devtest] 已达最大循环次数 $max_cycles，强制进入下一阶段"
  set_phase_status "devtest" "max_cycles_reached"
  advance_phase
}

# 阶段 3：Docker 部署
run_deploy_phase() {
  local work_dir="$1"
  log_phase "阶段 3/3: Docker 构建与部署验证"

  local max_attempts=3
  local attempt=0

  while [[ $attempt -lt $max_attempts ]]; do
    attempt=$((attempt + 1))
    log_info "Docker 部署尝试 $attempt/$max_attempts..."

    local prompt_file
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/deploy.md" "$work_dir")

    ai_continue "$(cat "$prompt_file")" "$LOG_DIR/phase-deploy-${attempt}.log"

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
