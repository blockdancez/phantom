#!/usr/bin/env bash
# AIRequirement 服务管理器 — backend (FastAPI) + frontend (Vite) + worker (AIJuicer node)
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="ai-requirement"
SERVICES=(backend frontend worker)

port_backend=8010
port_frontend=3010
sig_backend="uvicorn app.main"
sig_frontend="vite"
sig_worker="app.aijuicer_node"

# 加载 backend/.env（OPENAI_API_KEY / AIJUICER_* 等）
if [[ -f "$PROJECT_ROOT/backend/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$PROJECT_ROOT/backend/.env"
  set +a
fi
export AIJUICER_SERVER="${AIJUICER_SERVER:-http://127.0.0.1:8000}"
export AIJUICER_REDIS_URL="${AIJUICER_REDIS_URL:-redis://127.0.0.1:6379/0}"
export AIJUICER_AGENT_NAME="${AIJUICER_AGENT_NAME:-ai-requirement}"
export AIJUICER_CONCURRENCY="${AIJUICER_CONCURRENCY:-1}"

start_backend() {
  cd "$PROJECT_ROOT/backend"
  nohup python3 -m uvicorn app.main:create_app --factory \
    --host 0.0.0.0 --port "$port_backend" \
    >"$(log_file backend)" 2>&1 &
  echo $! > "$PID_DIR/backend.pid"
  disown 2>/dev/null || true
}

start_frontend() {
  cd "$PROJECT_ROOT/frontend"
  PORT="$port_frontend" nohup npm run dev >"$(log_file frontend)" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
  disown 2>/dev/null || true
}

start_worker() {
  cd "$PROJECT_ROOT/backend"
  nohup python3 -m app.aijuicer_node >"$(log_file worker)" 2>&1 &
  echo $! > "$PID_DIR/worker.pid"
  disown 2>/dev/null || true
}

# shellcheck disable=SC1091
source "$PROJECT_ROOT/../scripts/lib/service-lib.sh"
dispatch "$@"
