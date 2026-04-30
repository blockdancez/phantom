#!/usr/bin/env bash
# Phantom 顶层一键管理器 — 编排所有子项目的 service.sh
#
# 启动顺序：
#   1) AIJuicer (scheduler + webui)            ← 中央调度，必须先起
#   2) Workers: AIPlan / AIDesign / AIDevTest /
#               AIRequirement worker            ← 拉 AIJuicer 任务
#   3) Webapps: AIIdea / AIRequirement          ← 独立 webapp
#
# 停止顺序与启动相反。
#
# 用法:
#   scripts/all.sh start             启动全部（按顺序）
#   scripts/all.sh stop              停止全部（反序）
#   scripts/all.sh restart
#   scripts/all.sh status            汇总状态
#   scripts/all.sh logs <service>    tail 单个日志
#   scripts/all.sh -h | --help

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# (子项目目录，svc 列表) — 启动顺序
LAYERS=(
  "AIJuicer:scheduler,webui"
  "AIPlan:worker"
  "AIDesign:worker"
  "AIDevTest:worker"
  "AIRequirement:worker"
  "AIIdea:backend,frontend"
  "AIRequirement:backend,frontend"
)

usage() {
  cat <<EOF
Phantom 顶层服务管理器

用法:
  $0 start        启动所有子项目（按依赖顺序）
  $0 stop         反序停止
  $0 restart
  $0 status       汇总状态
  $0 logs <ai-juicer/scheduler|ai-idea/backend|...>  tail 单个日志

启动层（按顺序）:
$(for l in "${LAYERS[@]}"; do echo "  - ${l/:/  → }"; done)
EOF
}

call_proj() {
  local proj="$1" cmd="$2" svc="$3"
  echo
  echo "════ [$cmd] $proj ($svc) ════"
  bash "$ROOT/$proj/scripts/service.sh" "$cmd" "$svc" --no-follow || true
}

cmd_start() {
  for layer in "${LAYERS[@]}"; do
    local proj="${layer%%:*}" svcs="${layer#*:}"
    for svc in ${svcs//,/ }; do
      call_proj "$proj" start "$svc"
    done
  done
  echo
  echo "═══════════════════════════════════════"
  cmd_status
  echo
  echo "提示: 用 \`$0 logs <project>/<svc>\` 查看具体日志"
}

cmd_stop() {
  # 反序
  local i
  for (( i=${#LAYERS[@]}-1; i>=0; i-- )); do
    local layer="${LAYERS[$i]}"
    local proj="${layer%%:*}" svcs="${layer#*:}"
    # svcs 也反序
    local rev=()
    for svc in ${svcs//,/ }; do rev=("$svc" "${rev[@]}"); done
    for svc in "${rev[@]}"; do
      call_proj "$proj" stop "$svc"
    done
  done
}

cmd_status() {
  echo "── Phantom 服务总状态 ──"
  for proj in AIJuicer AIPlan AIDesign AIDevTest AIRequirement AIIdea; do
    bash "$ROOT/$proj/scripts/service.sh" status || true
  done
}

cmd_logs() {
  local target="${1:-}"
  [[ -z "$target" ]] && { echo "Usage: $0 logs <project>/<svc>，例: AIIdea/backend" >&2; exit 1; }
  local proj="${target%%/*}" svc="${target#*/}"
  if [[ ! -d "$ROOT/$proj" ]]; then echo "未知项目: $proj" >&2; exit 1; fi
  exec bash "$ROOT/$proj/scripts/service.sh" logs "$svc"
}

case "${1:-status}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  logs)    cmd_logs "${2:-}" ;;
  -h|--help|help) usage ;;
  *) usage; exit 1 ;;
esac
