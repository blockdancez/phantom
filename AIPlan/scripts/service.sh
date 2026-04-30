#!/usr/bin/env bash
# AIPlan 服务管理器 — phantom --plan 包装 worker
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="ai-plan"
SERVICES=(worker)
sig_worker="ai_plan.agent"

: "${AIJUICER_SERVER:=http://127.0.0.1:8000}"
export AIJUICER_SERVER

start_worker() {
  cd "$PROJECT_ROOT"
  if [[ ! -x .venv/bin/python ]]; then
    echo "[start_worker] 找不到 .venv/bin/python；先在 $PROJECT_ROOT 跑：python3.12 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
    return 1
  fi
  PYTHONUNBUFFERED=1 nohup .venv/bin/python -m ai_plan.agent \
    >"$(log_file worker)" 2>&1 &
  echo $! > "$PID_DIR/worker.pid"
  disown 2>/dev/null || true
}

# shellcheck disable=SC1091
source "$PROJECT_ROOT/../scripts/lib/service-lib.sh"
dispatch "$@"
