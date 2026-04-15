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

  # ── R1: Planner 写初稿 ───────────────────────────
  log_info "Plan R1: Planner 起草 plan.md（9 节）"
  local r1_attempt=0
  local r1_max=3
  while [[ $r1_attempt -lt $r1_max ]]; do
    r1_attempt=$((r1_attempt + 1))
    local r1_extra=""
    if [[ $r1_attempt -gt 1 ]]; then
      r1_extra="⚠️ 上次尝试没有生成 .phantom/plan.md。请**直接用 Write 工具**把完整 9 节计划写入 .phantom/plan.md，不要先解释、不要先列大纲。不得碰其他文件。"
    fi

    local prompt_file
    PHANTOM_EXTRA_NOTE="$r1_extra" \
      prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/plan.md" "$work_dir")
    ai_run_oneshot generator "$(cat "$prompt_file")" "$LOG_DIR/plan-r1-attempt${r1_attempt}.log"
    rm -f "$prompt_file"

    if [[ -f "$PLAN_FILE" ]] && _plan_has_all_9_sections; then
      log_ok "Plan R1 通过：plan.md 9 节齐全"
      break
    fi
    log_warn "Plan R1 第 $r1_attempt 次未产出合格 plan.md（9 节不齐或文件缺失）"
  done

  if ! [[ -f "$PLAN_FILE" ]] || ! _plan_has_all_9_sections; then
    log_error "Plan R1 经过 $r1_max 次尝试仍未产出合格 plan.md"
    set_phase_status "plan" "failed"
    exit 1
  fi

  # ── R2: Plan reviewer 审查 ─────────────────────
  log_info "Plan R2: Plan-reviewer 审查 rubric（跨模型，只提建议无否决权）"
  local prompt_file
  prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/plan-review.md" "$work_dir")
  ai_run_oneshot plan_reviewer "$(cat "$prompt_file")" "$LOG_DIR/plan-r2.log"
  rm -f "$prompt_file"

  if ! [[ -f "$PLAN_REVIEW_COMMENTS_FILE" ]]; then
    log_warn "Plan R2 未产出 review comments，继续 R3（无意见=不改）"
    printf '# Plan Review Comments\n\n无意见（R2 未产出 comments，降级）\n' > "$PLAN_REVIEW_COMMENTS_FILE"
  fi

  # ── R3: Planner 根据 comments 修订 ───────────────
  log_info "Plan R3: Planner 根据 comments 修订 plan.md"
  local r3_extra
  r3_extra="这是 Plan 阶段的 R3（最后一轮）。下面是 R2 跨模型 reviewer 的意见，你可以采纳也可以忽略并写理由，但必须重新 Write .phantom/plan.md（即使只是微调）。

--- Reviewer comments ---
$(cat "$PLAN_REVIEW_COMMENTS_FILE")
--- end comments ---

请重写 .phantom/plan.md（保持 9 节结构），把你决定采纳的修改落实到位。对于忽略的建议，在对应章节末尾加一行 \"> R2 建议: ...，未采纳原因: ...\" 的 quote。"

  PHANTOM_EXTRA_NOTE="$r3_extra" \
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/plan.md" "$work_dir")
  ai_run_oneshot generator "$(cat "$prompt_file")" "$LOG_DIR/plan-r3.log"
  rm -f "$prompt_file"

  if ! [[ -f "$PLAN_FILE" ]] || ! _plan_has_all_9_sections; then
    log_error "Plan R3 产出的 plan.md 仍不合格（9 节不齐）"
    set_phase_status "plan" "failed"
    exit 1
  fi

  # ── 落锁 ──────────────────────────────────────
  cp "$PLAN_FILE" "$PLAN_LOCKED_FILE"
  log_ok "Plan 落锁：.phantom/plan.locked.md 已生成"

  # 校验 feature 列表能被解析
  local feature_count
  feature_count=$(count_features)
  if [[ "$feature_count" -lt 5 ]]; then
    log_error "Plan 第 5 节 feature 数量 $feature_count < 5（下游 feature-per-sprint 无法启动）"
    set_phase_status "plan" "failed"
    exit 1
  fi
  log_ok "解析到 $feature_count 个 feature"
  list_features_from_plan | sed 's/^/  - /'

  set_phase_status "plan" "completed"
  return 0
}

# 检查 plan.md 是否包含 9 个预期章节
_plan_has_all_9_sections() {
  [[ -f "$PLAN_FILE" ]] || return 1
  local expected=(
    '## 1\. 产品目标'
    '## 2\. 技术栈与架构'
    '## 3\. 数据模型'
    '## 4\. API 约定'
    '## 5\. Feature 列表'
    '## 6\. 非功能需求'
    '## 7\. 编码标准与审查红线'
    '## 8\. 部署配置'
    '## 9\. 验收评分标准'
  )
  local h
  for h in "${expected[@]}"; do
    grep -q "^$h" "$PLAN_FILE" || return 1
  done
  return 0
}

# ── 阶段 2：dev（单次 dev round，compaction 长会话） ────
#
# 调用方（主循环）负责 feature 迭代与 return-packet 传递；
# 这里只跑一个 dev round——注入当前 feature slug，调用 generator，
# 校验 changelog.md 有新条目。
run_dev_phase() {
  local work_dir="$1" feature_slug="$2"
  set_phase_status "dev" "in_progress"
  increment_iteration "dev"
  local iter
  iter=$(get_phase_iteration "dev")
  log_phase "阶段 2/5: dev（feature=$feature_slug, iter=$iter）"

  local changelog_before=0
  [[ -f "$CHANGELOG_FILE" ]] && changelog_before=$(grep -c '^## Iteration ' "$CHANGELOG_FILE" 2>/dev/null || echo 0)

  local log_file="$LOG_DIR/dev-iter${iter}-${feature_slug}.log"
  local prompt_file
  PHANTOM_FEATURE="$feature_slug" \
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/develop.md" "$work_dir")
  ai_run generator "$(cat "$prompt_file")" "$log_file"
  rm -f "$prompt_file"

  # 校验 changelog.md 新增了本 iteration 的条目
  local changelog_after=0
  [[ -f "$CHANGELOG_FILE" ]] && changelog_after=$(grep -c '^## Iteration ' "$CHANGELOG_FILE" 2>/dev/null || echo 0)

  if [[ "$changelog_after" -le "$changelog_before" ]]; then
    log_warn "dev 未在 changelog.md 新增 Iteration 条目（${changelog_before} → ${changelog_after}），触发补救 round"
    local fix_prompt
    fix_prompt=$(mktemp)
    cat > "$fix_prompt" <<'EOF'
你刚刚完成的 dev round **没有在 .phantom/changelog.md 追加新的 `## Iteration <N>` 条目**。

请**只做这件事**：
1. 运行 `git diff --stat HEAD` 查看本轮改动
2. 按固定格式在 .phantom/changelog.md 末尾追加一节：

```markdown
## Iteration <N> — <feature-slug>

### 做了什么
- <概述本轮写的功能>

### 自测结果
- 单测：<N> 条，<M> 通过，覆盖率 <X>%
- 静态检查：<tool> 0 error

### 已知遗留
- （无 / 简述）
```

3. 完成后停止，不要开始新功能
EOF
    ai_run generator "$(cat "$fix_prompt")" "${log_file%.log}-changelog-fix.log"
    rm -f "$fix_prompt"
  fi

  # 跑完这一 round 后清除 return-packet（已被消费），归档到 logs/
  if [[ -f "$RETURN_PACKET_FILE" ]]; then
    archive_return_packet "$iter"
    rm -f "$RETURN_PACKET_FILE"
  fi

  set_phase_status "dev" "completed"
  return 0
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
