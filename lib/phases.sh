#!/usr/bin/env bash
# lib/phases.sh - 各阶段执行逻辑

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/state.sh"
source "$SCRIPT_DIR/lib/loop.sh"

# 严格模式：达到最大轮次时直接 fail，而非 forced_advance
PHANTOM_STRICT="${PHANTOM_STRICT:-0}"

# ── 通用：跑一轮 generator，并校验 progress.md 真的被更新 ──
run_generator_round() {
  local label="$1" prompt_template="$2" work_dir="$3" log_file="$4"

  local progress_before=0
  [[ -f "$PROGRESS_FILE" ]] && progress_before=$(wc -l < "$PROGRESS_FILE" | tr -d ' ')

  local prompt_file
  prompt_file=$(render_prompt "$prompt_template" "$work_dir")
  ai_run generator "$(cat "$prompt_file")" "$log_file"
  rm -f "$prompt_file"

  local progress_after=0
  [[ -f "$PROGRESS_FILE" ]] && progress_after=$(wc -l < "$PROGRESS_FILE" | tr -d ' ')

  if [[ "$progress_after" -le "$progress_before" ]]; then
    log_warn "[$label] generator 未更新 progress.md（$progress_before → $progress_after），触发补救轮"
    local fix_prompt
    fix_prompt=$(mktemp)
    cat > "$fix_prompt" <<'EOF'
你刚刚完成了一轮工作，但**没有更新 .phantom/progress.md**。
这是 Context Reset 模式的命脉——下一轮的你会因此失忆，无法接着干。

请**只做以下事情**，不要写新代码：
1. 运行 `git status` 和 `git diff --stat HEAD` 看自己刚做了什么
2. 把刚完成的步骤逐条追加到 .phantom/progress.md（每行一条 `- [x] Task N Step M: 描述`）
3. 同步更新 .phantom/file-map.md 中变更或新建的文件 → 一句话职责
4. 完成后停止，不要继续开发新功能
EOF
    ai_run generator "$(cat "$fix_prompt")" "${log_file%.log}-progress-fix.log"
    rm -f "$fix_prompt"
  fi
}

# ── 通用：跑一轮 reviewer，解析 verdict ─────────────────
# 返回：0 = pass, 1 = fail（含 invalid JSON / verdict 异常）
run_reviewer_round() {
  local stage="$1" work_dir="$2" log_file="$3"

  reset_last_review

  local prompt_file
  prompt_file=$(PHANTOM_REVIEW_STAGE="$stage" \
    render_prompt "$SCRIPT_DIR/prompts/review.md" "$work_dir")
  ai_run reviewer "$(cat "$prompt_file")" "$log_file"
  rm -f "$prompt_file"

  if ! last_review_valid_json; then
    log_warn "[review:$stage] last-review.json 不是合法 JSON，强制视为 fail"
    cat > "$LAST_REVIEW_FILE" <<EOF
{"verdict":"fail","stage":"$stage","failures":[{"category":"other","where":"reviewer","what":"reviewer 未输出合法 JSON","evidence":"jq empty 失败"}],"evidence":[]}
EOF
    return 1
  fi

  local verdict
  verdict=$(read_review_verdict)
  case "$verdict" in
    pass) return 0 ;;
    fail) return 1 ;;
    *)
      log_warn "[review:$stage] verdict='$verdict' 非 pass/fail，视为 fail"
      return 1
      ;;
  esac
}

# ── 阶段 1：规划 ────────────────────────────────────────
run_plan_phase() {
  local work_dir="$1"
  log_phase "阶段 1/3: 需求分析与计划制定"

  set_phase_status "plan" "in_progress"

  local max_attempts=3
  local attempt=0
  while [[ $attempt -lt $max_attempts ]]; do
    attempt=$((attempt + 1))
    log_info "Plan 尝试 $attempt/$max_attempts"

    local extra=""
    if [[ $attempt -gt 1 ]]; then
      extra="⚠️ 上一次尝试**没有生成** .phantom/plan.md。
请直接用 Write 工具把完整计划写入 .phantom/plan.md——不要先解释、不要先列大纲。
本阶段你**只允许写这一个文件**，不要碰 src/ 或其他位置。"
    fi

    local prompt_file
    PHANTOM_EXTRA_NOTE="$extra" \
      prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/plan.md" "$work_dir")
    ai_run_plan "$(cat "$prompt_file")" "$LOG_DIR/phase-plan-${attempt}.log"
    rm -f "$prompt_file"

    if [[ -f ".phantom/plan.md" ]]; then
      log_ok "计划已生成: .phantom/plan.md"
      set_phase_status "plan" "completed"
      advance_phase
      return 0
    fi
    log_warn "Plan 第 $attempt 次未生成 .phantom/plan.md"
  done

  log_error "Plan 阶段经过 $max_attempts 次尝试仍未生成计划文件"
  set_phase_status "plan" "failed"
  exit 1
}

# ── 阶段 2：开发-评审 + 测试-评审 ──────────────────────
run_devtest_phase() {
  local work_dir="$1"
  local dev_max=8
  local test_max=10

  log_phase "阶段 2/3: 开发-评审-测试循环 (dev≤$dev_max / test≤$test_max)"

  set_phase_status "devtest" "in_progress"
  ensure_handoff_files

  # ── Stage A: 开发 → 独立评审 ──
  local dev_passed=false
  local dev_round=0
  while [[ "$dev_passed" == false ]] && [[ $dev_round -lt $dev_max ]]; do
    dev_round=$((dev_round + 1))

    log_info "[dev] Generator 第 $dev_round 轮"
    run_generator_round "dev" "$SCRIPT_DIR/prompts/develop.md" "$work_dir" \
      "$LOG_DIR/phase-devtest-dev-${dev_round}.log"

    log_info "[dev] Reviewer 第 $dev_round 轮（独立评审实现）"
    if run_reviewer_round "dev_implementation" "$work_dir" \
         "$LOG_DIR/phase-devtest-review-dev-${dev_round}.log"; then
      log_ok "[dev] 评审通过"
      dev_passed=true
    else
      log_warn "[dev] 评审 reject，下一轮 generator 会读 open-issues.md 修复"
    fi
  done

  if [[ "$dev_passed" == false ]]; then
    if [[ "$PHANTOM_STRICT" == "1" ]]; then
      log_error "[dev] $dev_max 轮未通过评审（strict 模式失败）"
      set_phase_status "devtest" "failed"
      exit 1
    fi
    log_warn "[dev] $dev_max 轮未通过评审，强制进入测试阶段（标记 forced_advance）"
    mark_forced_advance "devtest"
  fi

  # Stage 切换：清空 last-review，避免 dev 评审结论污染 test 评审
  reset_last_review

  # ── Stage B: 测试 → 独立评审 → 失败修复 ──
  local cycle=0
  while [[ $cycle -lt $test_max ]]; do
    cycle=$((cycle + 1))
    increment_iteration "devtest"
    log_phase "测试-评审循环 第 $cycle/$test_max 轮"

    log_info "[test] Tester 编写并运行测试"
    run_generator_round "test" "$SCRIPT_DIR/prompts/test.md" "$work_dir" \
      "$LOG_DIR/phase-devtest-test-${cycle}.log"

    log_info "[test] Reviewer 独立评审测试质量"
    if run_reviewer_round "test_quality" "$work_dir" \
         "$LOG_DIR/phase-devtest-review-test-${cycle}.log"; then
      log_ok "[test] 评审通过! devtest 完成"
      set_phase_status "devtest" "completed"
      advance_phase
      return 0
    fi

    log_warn "[test] 评审 reject，进入修复轮"
    run_generator_round "fix" "$SCRIPT_DIR/prompts/fix-from-test.md" "$work_dir" \
      "$LOG_DIR/phase-devtest-fix-${cycle}.log"
  done

  if [[ "$PHANTOM_STRICT" == "1" ]]; then
    log_error "[devtest] $test_max 轮未通过（strict 模式失败）"
    set_phase_status "devtest" "failed"
    exit 1
  fi
  log_warn "[devtest] $test_max 轮未通过，强制进入下一阶段（标记 forced_advance）"
  mark_forced_advance "devtest"
  set_phase_status "devtest" "max_cycles_reached"
  advance_phase
}

# ── 阶段 3：Docker 部署 ────────────────────────────────
run_deploy_phase() {
  local work_dir="$1"
  log_phase "阶段 3/3: Docker 构建与部署验证"

  local max_attempts=3
  local attempt=0
  while [[ $attempt -lt $max_attempts ]]; do
    attempt=$((attempt + 1))
    log_info "Docker 部署尝试 $attempt/$max_attempts"

    local log_file="$LOG_DIR/phase-deploy-${attempt}.log"
    local prompt_file
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/deploy.md" "$work_dir")
    ai_run deploy "$(cat "$prompt_file")" "$log_file"
    rm -f "$prompt_file"

    # 严格匹配：只在最后 10 行内找独占一行的 PHASE_COMPLETE
    if tail -n 10 "$log_file" 2>/dev/null | grep -qx "PHASE_COMPLETE"; then
      log_ok "Docker 部署验证成功!"
      set_phase_status "deploy" "completed"
      advance_phase
      return 0
    fi
    log_warn "部署未成功，重试..."
  done

  if [[ "$PHANTOM_STRICT" == "1" ]]; then
    log_error "Docker 部署 $max_attempts 次后仍未成功（strict 模式失败）"
  else
    log_error "Docker 部署 $max_attempts 次后仍未成功"
  fi
  set_phase_status "deploy" "failed"
  return 1
}
