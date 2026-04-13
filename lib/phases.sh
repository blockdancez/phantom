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
# 文章思想：
#   - Generator/Evaluator 物理分离 → dev 用 develop.md，review 用 review.md
#   - Context Reset → 全程 ai_fresh，跨轮信息靠 .phantom/ 下的交接物
#   - Sprint Contract → reviewer 真跑代码，写结构化 last-review.json
run_devtest_phase() {
  local work_dir="$1"
  local max_cycles=10
  local cycle=0

  log_phase "阶段 2/3: 开发-评审-测试循环 (最多 $max_cycles 轮，独立 reviewer)"

  set_phase_status "devtest" "in_progress"
  ensure_handoff_files

  # ── Stage A：开发 → 独立评审 → 通过为止 ──
  local dev_passed=false
  local dev_round=0
  local dev_max=8

  while [[ "$dev_passed" == false ]] && [[ $dev_round -lt $dev_max ]]; do
    dev_round=$((dev_round + 1))

    # Generator: fresh context，吃 progress + open-issues + last-review
    log_info "[dev] Generator 第 $dev_round 轮 — 写代码..."
    local dev_prompt
    dev_prompt=$(render_prompt "$SCRIPT_DIR/prompts/develop.md" "$work_dir")
    ai_fresh "$(cat "$dev_prompt")" "$LOG_DIR/phase-devtest-dev-${dev_round}.log"
    rm -f "$dev_prompt"

    # Evaluator: fresh context，独立身份评审，写 last-review.json
    log_info "[dev] Reviewer 第 $dev_round 轮 — 独立评审..."
    local review_prompt
    review_prompt=$(render_prompt "$SCRIPT_DIR/prompts/review.md" "$work_dir")
    ai_fresh "$(cat "$review_prompt")" "$LOG_DIR/phase-devtest-review-${dev_round}.log"
    rm -f "$review_prompt"

    if grep -q "PHASE_COMPLETE" "$LOG_DIR/phase-devtest-review-${dev_round}.log"; then
      log_ok "[dev] 独立评审通过!"
      dev_passed=true
    else
      log_warn "[dev] 评审 reject，下一轮 generator 会读 open-issues.md 修复..."
    fi
  done

  if [[ "$dev_passed" == false ]]; then
    log_warn "[dev] 达到 $dev_max 轮仍未通过评审，强制进入测试阶段"
  fi

  # ── Stage B：测试 → 独立评审 → 失败则修复 ──
  while [[ $cycle -lt $max_cycles ]]; do
    cycle=$((cycle + 1))
    increment_iteration "devtest"

    log_phase "测试-评审循环 第 $cycle/$max_cycles 轮"

    # Tester (generator): fresh
    log_info "[test] Tester 编写并运行测试..."
    local test_prompt
    test_prompt=$(render_prompt "$SCRIPT_DIR/prompts/test.md" "$work_dir")
    ai_fresh "$(cat "$test_prompt")" "$LOG_DIR/phase-devtest-test-${cycle}.log"
    rm -f "$test_prompt"

    # Reviewer: fresh
    log_info "[test] Reviewer 独立评审测试与代码..."
    local review_prompt
    review_prompt=$(render_prompt "$SCRIPT_DIR/prompts/review.md" "$work_dir")
    ai_fresh "$(cat "$review_prompt")" "$LOG_DIR/phase-devtest-review-test-${cycle}.log"
    rm -f "$review_prompt"

    if grep -q "PHASE_COMPLETE" "$LOG_DIR/phase-devtest-review-test-${cycle}.log"; then
      log_ok "[test] 评审通过! devtest 完成"
      set_phase_status "devtest" "completed"
      advance_phase
      return 0
    fi

    # 评审 reject → 修复代码（fresh，吃 last-review.json）
    log_warn "[test] 评审 reject，进入修复轮..."
    local fix_prompt
    fix_prompt=$(render_prompt "$SCRIPT_DIR/prompts/fix-from-test.md" "$work_dir")
    ai_fresh "$(cat "$fix_prompt")" "$LOG_DIR/phase-devtest-fix-${cycle}.log"
    rm -f "$fix_prompt"
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

    ai_fresh "$(cat "$prompt_file")" "$LOG_DIR/phase-deploy-${attempt}.log"

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
