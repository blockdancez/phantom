#!/usr/bin/env bash
# lib/code-review.sh - Shell 侧兜底复查（cheap defense-in-depth）
#
# 在 AI code-reviewer 说 verdict=pass 之后，shell 跑一轮确定性 grep。
# 任一命中即把 verdict 强制降级为 fail，并把问题写进 return-packet。

# 要扫描的源文件后缀
_SHELL_REVIEW_EXTENSIONS=(
  "--include=*.py"
  "--include=*.js"
  "--include=*.ts"
  "--include=*.tsx"
  "--include=*.jsx"
  "--include=*.go"
  "--include=*.java"
  "--include=*.rs"
  "--include=*.rb"
)

# 要跳过的目录
_SHELL_REVIEW_EXCLUDES=(
  "--exclude-dir=node_modules"
  "--exclude-dir=.git"
  "--exclude-dir=.phantom"
  "--exclude-dir=dist"
  "--exclude-dir=build"
  "--exclude-dir=target"
  "--exclude-dir=venv"
  "--exclude-dir=__pycache__"
  "--exclude-dir=.venv"
  "--exclude-dir=migrations"
)

# 扫描某类问题并返回命中行
# args: <pattern> <pattern description>
# 输出：每行 "file:line: content"
_shell_grep_issue() {
  local pattern="$1"
  grep -rnE "$pattern" \
    "${_SHELL_REVIEW_EXTENSIONS[@]}" \
    "${_SHELL_REVIEW_EXCLUDES[@]}" \
    . 2>/dev/null || true
}

# 主函数：跑全部兜底检查
# 返回：0 无问题；1 有问题
# 副作用：把问题写到全局数组 _SHELL_REVIEW_HITS（每行一条）
run_shell_code_review() {
  _SHELL_REVIEW_HITS=()
  local hits

  # 1. 禁用标记
  hits=$(_shell_grep_issue 'TODO|FIXME|XXX|HACK')
  if [[ -n "$hits" ]]; then
    while IFS= read -r line; do
      _SHELL_REVIEW_HITS+=("[placeholder] $line")
    done <<< "$hits"
  fi

  # 2. 禁用日志：console.log 或行首 print
  hits=$(_shell_grep_issue '(console\.log\(|^[[:space:]]*print\()')
  if [[ -n "$hits" ]]; then
    while IFS= read -r line; do
      _SHELL_REVIEW_HITS+=("[print-log] $line")
    done <<< "$hits"
  fi

  # 3. 硬编码端口（常见开发端口）
  hits=$(_shell_grep_issue '(^|[^0-9a-zA-Z_])(3000|8080|5000|8000)([^0-9a-zA-Z_]|$)')
  if [[ -n "$hits" ]]; then
    # 排除那些带 env / process.env / os.getenv 的行（合理的默认值用法）
    while IFS= read -r line; do
      if echo "$line" | grep -qE '(env\.PORT|getenv|PORT\s*=|\$PORT|process\.env)'; then
        continue
      fi
      _SHELL_REVIEW_HITS+=("[hardcoded-port] $line")
    done <<< "$hits"
  fi

  # 4. 硬编码凭据：password = "..." 这种模式
  hits=$(_shell_grep_issue '(password|passwd|secret|api_key|apikey|token)\s*=\s*["'\''][^"'\'']+["'\'']')
  if [[ -n "$hits" ]]; then
    while IFS= read -r line; do
      # 排除 getenv 取值行
      if echo "$line" | grep -qE '(getenv|os\.environ|process\.env|ENV\[)'; then
        continue
      fi
      _SHELL_REVIEW_HITS+=("[hardcoded-credential] $line")
    done <<< "$hits"
  fi

  if [[ ${#_SHELL_REVIEW_HITS[@]} -gt 0 ]]; then
    return 1
  fi
  return 0
}

# 把 _SHELL_REVIEW_HITS 格式化成 return-packet 的必修项列表
format_shell_review_failures() {
  local hit
  for hit in "${_SHELL_REVIEW_HITS[@]}"; do
    printf -- '- [shell-grep] %s\n' "$hit"
  done
}
