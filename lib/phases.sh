#!/usr/bin/env bash
# lib/phases.sh - 各阶段执行逻辑（harness v2）
#
# 顶层流程：plan → [dev → code_review → deploy → test]（per feature）→ done
# 每个函数实现在对应 step 填充。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/state.sh"
source "$SCRIPT_DIR/lib/loop.sh"
source "$SCRIPT_DIR/lib/code-review.sh"

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

# ── 阶段 3：code-review（AI 语义审查 + shell 兜底 grep） ──
#
# 返回：0 = pass，1 = fail（reviewer 或 shell 兜底命中）
run_code_review_phase() {
  local work_dir="$1" feature_slug="$2"
  set_phase_status "code_review" "in_progress"
  increment_iteration "code_review"
  local iter
  iter=$(get_phase_iteration "code_review")
  log_phase "阶段 3/5: code-review（feature=$feature_slug, iter=$iter）"

  reset_last_code_review

  local log_file="$LOG_DIR/code-review-iter${iter}-${feature_slug}.log"
  local prompt_file
  PHANTOM_FEATURE="$feature_slug" \
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/code-review.md" "$work_dir")
  ai_run code_reviewer "$(cat "$prompt_file")" "$log_file"
  rm -f "$prompt_file"

  # 1. 校验 JSON 合法性
  if ! last_code_review_valid_json; then
    log_warn "code-review 未输出合法 JSON，强制 fail"
    cat > "$LAST_CODE_REVIEW_FILE" <<EOF
{"verdict":"fail","feature":"${feature_slug}","issues":[{"category":"other","where":"reviewer","what":"reviewer 未输出合法 JSON","evidence":"jq empty 失败"}],"notes":""}
EOF
    _write_code_review_return_packet "$feature_slug" "$iter"
    set_phase_status "code_review" "failed"
    return 1
  fi

  local verdict
  verdict=$(read_code_review_verdict)

  if [[ "$verdict" != "pass" ]]; then
    log_warn "code-review verdict=$verdict"
    _write_code_review_return_packet "$feature_slug" "$iter"
    set_phase_status "code_review" "failed"
    return 1
  fi

  # 2. Reviewer 说 pass → 跑 shell 兜底复查
  log_info "Reviewer verdict=pass，执行 shell 兜底 grep 复查"
  if run_shell_code_review; then
    log_ok "code-review 通过（reviewer pass + shell 兜底 0 命中）"
    set_phase_status "code_review" "completed"
    return 0
  fi

  log_warn "shell 兜底复查发现 ${#_SHELL_REVIEW_HITS[@]} 处问题，强制降级 reviewer verdict=pass 为 fail"

  # 把 shell 发现的问题注入 last-code-review.json
  local tmp
  tmp=$(mktemp)
  local hits_json
  hits_json=$(printf '%s\n' "${_SHELL_REVIEW_HITS[@]}" | jq -R -s 'split("\n") | map(select(length > 0))')
  jq --argjson hits "$hits_json" \
     '.verdict = "fail" | .issues += ($hits | map({category: "shell-grep", where: ".", what: ., evidence: "shell grep"}))' \
     "$LAST_CODE_REVIEW_FILE" > "$tmp" && mv "$tmp" "$LAST_CODE_REVIEW_FILE"

  _write_code_review_return_packet "$feature_slug" "$iter"
  set_phase_status "code_review" "failed"
  return 1
}

# 写 return-packet.md（code-review 失败时）
_write_code_review_return_packet() {
  local feature_slug="$1" iter="$2"
  local timestamp
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  # 从 last-code-review.json 取 issues
  local issues_section=""
  if last_code_review_valid_json; then
    issues_section=$(jq -r '.issues[] | "- [code-review] \(.where): \(.what) (evidence: \(.evidence))"' "$LAST_CODE_REVIEW_FILE" 2>/dev/null)
  fi
  if [[ -z "$issues_section" ]]; then
    issues_section="- [code-review] reviewer 失败但没输出具体 issues，见日志"
  fi

  cat > "$RETURN_PACKET_FILE" <<EOF
---
return_from: code-review
iteration: $iter
feature: $feature_slug
triggered_at: $timestamp
---

## 为什么回来

Code review 发现硬性问题，dev 必须修掉。

## 必修项（硬性，dev 必须全部修掉）

$issues_section

## 建议项（软性，dev 自行判断改不改）

- （无）

## 全量报告

- \`.phantom/last-code-review.json\`
- \`.phantom/logs/code-review-iter${iter}-${feature_slug}.log\`
EOF
}

# ── 阶段 4：deploy（docker build/run + shell 四项确定性判断） ──
#
# 返回：0 = pass，1 = fail（自试 2 次都失败后写 return-packet）
run_deploy_phase() {
  local work_dir="$1" feature_slug="$2"
  set_phase_status "deploy" "in_progress"
  increment_iteration "deploy"
  local iter
  iter=$(get_phase_iteration "deploy")
  log_phase "阶段 4/5: deploy（feature=$feature_slug, iter=$iter）"

  local port
  port=$(cat "$PORT_FILE" 2>/dev/null || echo 8080)

  # 自试 2 次
  local attempt=0
  local max_attempts=2
  local deploy_err=""

  while [[ $attempt -lt $max_attempts ]]; do
    attempt=$((attempt + 1))
    log_info "Deploy attempt ${attempt}/${max_attempts}"

    local log_file="$LOG_DIR/deploy-iter${iter}-attempt${attempt}.log"
    local prompt_file
    local extra_note=""
    if [[ -n "$deploy_err" ]]; then
      extra_note="⚠️ 上次 docker build/run/smoke 失败，错误如下（请据此修 Dockerfile 或 docker-compose.yml）：

$deploy_err"
    fi

    PHANTOM_FEATURE="$feature_slug" PHANTOM_EXTRA_NOTE="$extra_note" \
      prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/deploy.md" "$work_dir")
    ai_run deploy "$(cat "$prompt_file")" "$log_file"
    rm -f "$prompt_file"

    # Shell 侧四项确定性判断
    deploy_err=""
    if ! [[ -f "Dockerfile" ]]; then
      deploy_err="Dockerfile 不存在"
      log_warn "$deploy_err"
      continue
    fi

    local container_name="phantom-test-$(basename "$work_dir")"
    # 清理可能残留的旧容器
    docker rm -f "$container_name" >/dev/null 2>&1 || true

    # 1. docker build
    log_info "[1/4] docker build"
    if ! docker build -t "$container_name" . >>"$log_file" 2>&1; then
      deploy_err="docker build 失败（见日志 $log_file）"
      log_warn "$deploy_err"
      continue
    fi

    # 2. docker run
    log_info "[2/4] docker run"
    if ! docker run -d --name "$container_name" -e "PORT=$port" -p "$port:$port" "$container_name" >>"$log_file" 2>&1; then
      deploy_err="docker run 失败（见日志 $log_file）"
      log_warn "$deploy_err"
      docker rm -f "$container_name" >/dev/null 2>&1 || true
      continue
    fi

    # 3. 等容器进入 running 状态（最多 60s）
    log_info "[3/4] 等待容器 running"
    local waited=0
    local running=false
    while [[ $waited -lt 60 ]]; do
      if docker ps --filter "name=^${container_name}$" --filter "status=running" --format '{{.Names}}' | grep -q "^${container_name}$"; then
        running=true
        break
      fi
      sleep 2
      waited=$((waited + 2))
    done

    if [[ "$running" != true ]]; then
      deploy_err="容器 60s 内未进入 running 状态"
      docker logs "$container_name" >>"$log_file" 2>&1 || true
      log_warn "$deploy_err"
      docker rm -f "$container_name" >/dev/null 2>&1 || true
      continue
    fi

    # 额外给应用 3s 启动时间
    sleep 3

    # 4. Smoke：对每个 API 端点跑 happy path curl，要求非 5xx
    log_info "[4/4] Smoke 测试所有 API 端点"
    local smoke_failures=""
    local endpoints
    endpoints=$(_extract_endpoints_from_plan)
    if [[ -z "$endpoints" ]]; then
      log_warn "从 plan 中未提取到 API 端点，仅验证根路径"
      endpoints="GET /"
    fi

    while IFS= read -r ep; do
      [[ -z "$ep" ]] && continue
      local method path
      method=$(echo "$ep" | awk '{print $1}')
      path=$(echo "$ep" | awk '{print $2}')
      local url="http://localhost:${port}${path}"
      local code
      code=$(curl -s -o /dev/null -w '%{http_code}' -X "$method" --max-time 10 "$url" 2>/dev/null || echo "000")
      echo "    [$method $path] → HTTP $code" >>"$log_file"
      if [[ "$code" =~ ^5[0-9][0-9]$ ]] || [[ "$code" == "000" ]]; then
        smoke_failures+="$method $path → $code
"
      fi
    done <<< "$endpoints"

    # 清理容器
    docker stop "$container_name" >/dev/null 2>&1 || true
    docker rm "$container_name" >/dev/null 2>&1 || true

    if [[ -n "$smoke_failures" ]]; then
      deploy_err="Smoke 测试失败：
$smoke_failures"
      log_warn "$deploy_err"
      continue
    fi

    log_ok "Deploy 通过：docker build/run/smoke 全绿"
    set_phase_status "deploy" "completed"
    return 0
  done

  # 2 次自试都失败 → 写 return-packet 回 dev
  log_error "Deploy 自试 $max_attempts 次后仍失败"
  _write_deploy_return_packet "$feature_slug" "$iter" "$deploy_err"
  set_phase_status "deploy" "failed"
  return 1
}

# 从 plan.locked.md 第 4 节提取 API 端点
# 简单启发式：匹配 `GET /api/xxx` / `POST /xxx` 这种模式
_extract_endpoints_from_plan() {
  [[ -f "$PLAN_LOCKED_FILE" ]] || return
  awk '
    /^## 4\. / { in_section=1; next }
    /^## [0-9]/ { in_section=0 }
    in_section {
      # 匹配类似 `GET /api/todos` 的 pattern
      if (match($0, /(GET|POST|PUT|PATCH|DELETE|HEAD)[[:space:]]+\/[^ \t`]*/)) {
        s = substr($0, RSTART, RLENGTH)
        print s
      }
    }
  ' "$PLAN_LOCKED_FILE" | sort -u
}

_write_deploy_return_packet() {
  local feature_slug="$1" iter="$2" err="$3"
  local timestamp
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  cat > "$RETURN_PACKET_FILE" <<EOF
---
return_from: deploy
iteration: $iter
feature: $feature_slug
triggered_at: $timestamp
---

## 为什么回来

Deploy 自试 2 次后仍失败。可能是 Dockerfile 问题，也可能是源代码有问题（启动后崩溃或返回 5xx）。

## 必修项（硬性，dev 必须全部修掉）

- [deploy] $err

## 建议项（软性，dev 自行判断改不改）

- （无）

## 全量报告

- \`.phantom/logs/deploy-iter${iter}-attempt*.log\`
EOF
}

# ── 阶段 5：test（接口 + E2E + rubric 评分） ────────
#
# 调用方负责 min/max rounds 计数；这里只跑单次 test round。
# 返回：0 = pass（分数 ≥80）；1 = fail
run_test_phase() {
  local work_dir="$1" feature_slug="$2"
  set_phase_status "test" "in_progress"
  increment_iteration "test"
  local iter
  iter=$(get_phase_iteration "test")
  log_phase "阶段 5/5: test（feature=$feature_slug, iter=$iter）"

  local log_file="$LOG_DIR/test-iter${iter}-${feature_slug}.log"
  local prompt_file
  PHANTOM_FEATURE="$feature_slug" \
    prompt_file=$(render_prompt "$SCRIPT_DIR/prompts/test.md" "$work_dir")
  ai_run tester "$(cat "$prompt_file")" "$log_file"
  rm -f "$prompt_file"

  # 校验 test-report 存在
  local report_file="$STATE_DIR/test-report-iter${iter}.md"
  if ! [[ -f "$report_file" ]]; then
    log_warn "tester 未产出 test-report-iter${iter}.md，强制 fail 并构造 return-packet"
    _write_test_return_packet "$feature_slug" "$iter" "0" "tester 未产出 test-report-iter${iter}.md"
    set_phase_status "test" "failed"
    return 1
  fi

  # 从 report 提取总分
  local score
  score=$(_extract_score_from_report "$report_file")
  if [[ -z "$score" ]] || [[ ! "$score" =~ ^[0-9]+$ ]]; then
    log_warn "无法从 test-report 提取总分，强制 fail"
    _write_test_return_packet "$feature_slug" "$iter" "0" "无法从 test-report-iter${iter}.md 提取总分"
    set_phase_status "test" "failed"
    return 1
  fi

  log_info "test round $iter 总分: $score/100"

  if [[ "$score" -ge 80 ]]; then
    log_ok "test 通过（$score/100 ≥ 80）"
    set_phase_status "test" "completed"
    return 0
  fi

  log_warn "test 分数 $score < 80，写 return-packet 回 dev"
  # 如果 tester 已经写了 return-packet 就用它；否则 shell 兜底写一份
  if ! return_packet_exists; then
    _write_test_return_packet "$feature_slug" "$iter" "$score" "分数 $score < 80 但 tester 没写 return-packet"
  fi
  set_phase_status "test" "failed"
  return 1
}

# 从 test-report.md 第一行"总分"提取分数
# 支持格式："## 总分: 82/100" 或 "**总分**: 82/100" 等
_extract_score_from_report() {
  local report="$1"
  grep -Eo '总分[^0-9]*[0-9]+' "$report" | head -1 | grep -Eo '[0-9]+'
}

_write_test_return_packet() {
  local feature_slug="$1" iter="$2" score="$3" reason="$4"
  local timestamp
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  cat > "$RETURN_PACKET_FILE" <<EOF
---
return_from: test
iteration: $iter
feature: $feature_slug
triggered_at: $timestamp
---

## 为什么回来

Test 评分 ${score}/100，低于阈值 80。$reason

## 必修项（硬性，dev 必须全部修掉）

- [test] $reason，请查看 \`.phantom/test-report-iter${iter}.md\` 定位问题

## 建议项（软性）

- （无）

## 全量报告

- \`.phantom/test-report-iter${iter}.md\`
- \`.phantom/logs/test-iter${iter}-${feature_slug}.log\`
EOF
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
