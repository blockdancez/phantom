#!/usr/bin/env bash
# lib/phases.sh - 各阶段执行逻辑（harness v2）
#
# 顶层流程：plan → [dev → code_review → deploy → test]（per feature）→ done
# 每个函数实现在对应 step 填充。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/state.sh"
source "$SCRIPT_DIR/lib/loop.sh"

# 严格模式：达到最大轮次时直接 fail，而非 forced advance
PHANTOM_STRICT="${PHANTOM_STRICT:-0}"
# Fast 模式：降低 min rounds 地板
PHANTOM_FAST="${PHANTOM_FAST:-0}"

# ── 阶段 1：plan（plan R1 → plan-review R2 → plan R3 → 落锁） ──
run_plan_phase() {
  local work_dir="$1"
  log_phase "阶段 1/5: plan（plan → plan-review → plan → 落锁）"
  set_phase_status "plan" "in_progress"

  # TODO Step 2: 实现 R1/R2/R3 三 round 逻辑 + 落锁 plan.locked.md
  log_error "run_plan_phase 尚未实现（Step 2）"
  return 1
}

# ── 阶段 2：dev（feature-per-sprint 的单次 dev round） ────
# 调用方负责 feature 迭代，这里只跑单次 dev round
run_dev_phase() {
  local work_dir="$1" feature_slug="$2"
  log_phase "阶段 2/5: dev（feature=$feature_slug）"
  set_phase_status "dev" "in_progress"

  # TODO Step 3: 实现 dev round，含 self-test 无限自修
  log_error "run_dev_phase 尚未实现（Step 3）"
  return 1
}

# ── 阶段 3：code-review ────────────────────────────────
run_code_review_phase() {
  local work_dir="$1" feature_slug="$2"
  log_phase "阶段 3/5: code-review（feature=$feature_slug）"
  set_phase_status "code_review" "in_progress"

  # TODO Step 4: 实现 reviewer 跑 + shell 兜底 grep
  log_error "run_code_review_phase 尚未实现（Step 4）"
  return 1
}

# ── 阶段 4：deploy ────────────────────────────────────
run_deploy_phase() {
  local work_dir="$1" feature_slug="$2"
  log_phase "阶段 4/5: deploy（feature=$feature_slug）"
  set_phase_status "deploy" "in_progress"

  # TODO Step 5: 实现 docker build/run + shell 四项确定性判断 + 自试 2 次
  log_error "run_deploy_phase 尚未实现（Step 5）"
  return 1
}

# ── 阶段 5：test ──────────────────────────────────────
run_test_phase() {
  local work_dir="$1" feature_slug="$2"
  log_phase "阶段 5/5: test（feature=$feature_slug）"
  set_phase_status "test" "in_progress"

  # TODO Step 6: 实现接口 + E2E 测试 + 累积评分 + min/max rounds
  log_error "run_test_phase 尚未实现（Step 6）"
  return 1
}

# ── Feature 列表读取（从 plan.locked.md 第 5 节） ──────
# 返回 feature slug 列表（一行一个）
list_features_from_plan() {
  [[ -f "$PLAN_LOCKED_FILE" ]] || return 1
  # 第 5 节标题匹配："## 5. Feature 列表" 或 "## 5." 开头
  awk '
    /^## 5\. / { in_section=1; next }
    /^## [0-9]/ { in_section=0 }
    in_section && /^### / {
      # feature slug 从 "### feature-N: Title" 提取
      slug = $0
      gsub(/^### /, "", slug)
      gsub(/:.*$/, "", slug)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", slug)
      if (slug != "") print slug
    }
  ' "$PLAN_LOCKED_FILE"
}

# 根据索引取第 N 个 feature 的 slug
get_feature_by_index() {
  local idx="$1"
  list_features_from_plan | sed -n "$((idx + 1))p"
}

# feature 总数
count_features() {
  list_features_from_plan | wc -l | tr -d ' '
}
