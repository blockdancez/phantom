#!/usr/bin/env bash
# AIJuicer 服务管理器 — scheduler + webui
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="ai-juicer"
SERVICES=(scheduler webui)

port_scheduler=8000
port_webui=3000
sig_scheduler="uvicorn scheduler.main"
sig_webui="next dev"

: "${AIJUICER_SERVER:=http://127.0.0.1:8000}"
: "${AIJUICER_REDIS_URL:=redis://127.0.0.1:6379/0}"
: "${AIJUICER_AGENT_HOST:=127.0.0.1}"
export AIJUICER_SERVER AIJUICER_REDIS_URL AIJUICER_AGENT_HOST

start_scheduler() {
  cd "$PROJECT_ROOT"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  nohup uvicorn scheduler.main:app --host 127.0.0.1 --port "$port_scheduler" --log-level info \
    >"$(log_file scheduler)" 2>&1 &
  echo $! > "$PID_DIR/scheduler.pid"
  disown 2>/dev/null || true
}

start_webui() {
  if [[ ! -d "$PROJECT_ROOT/webui/node_modules" ]]; then
    echo "[start_webui] webui/node_modules 不存在，请先 cd webui && pnpm install" >&2
    return 1
  fi
  cd "$PROJECT_ROOT/webui"
  PATH="/opt/homebrew/bin:$PATH" \
  NEXT_PUBLIC_API_BASE="$AIJUICER_SERVER" \
    nohup pnpm dev >"$(log_file webui)" 2>&1 &
  echo $! > "$PID_DIR/webui.pid"
  disown 2>/dev/null || true
}

# shellcheck disable=SC1091
source "$PROJECT_ROOT/../scripts/lib/service-lib.sh"
dispatch "$@"
