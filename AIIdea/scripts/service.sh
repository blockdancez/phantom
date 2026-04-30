#!/usr/bin/env bash
# AIIdea 服务管理器 — backend (FastAPI) + frontend (Next.js)
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="ai-idea"
SERVICES=(backend frontend)

port_backend=53839
port_frontend=53840
sig_backend="uvicorn src.main"
sig_frontend="next dev"

# 端口可被 .phantom/port.* 覆盖
[[ -f "$PROJECT_ROOT/.phantom/port.backend" ]]  && port_backend=$(tr -d '[:space:]' <"$PROJECT_ROOT/.phantom/port.backend")
[[ -f "$PROJECT_ROOT/.phantom/port.frontend" ]] && port_frontend=$(tr -d '[:space:]' <"$PROJECT_ROOT/.phantom/port.frontend")

_python() {
  if [[ -x "$PROJECT_ROOT/backend/.venv/bin/python" ]]; then echo "$PROJECT_ROOT/backend/.venv/bin/python"
  elif [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then echo "$PROJECT_ROOT/.venv/bin/python"
  else echo python3; fi
}

start_backend() {
  cd "$PROJECT_ROOT/backend"
  local PY
  PY=$(_python)
  export PYTHONPATH="$PROJECT_ROOT/backend:${PYTHONPATH:-}"
  if "$PY" -c "import alembic" >/dev/null 2>&1; then
    "$PY" -m alembic -c "$PROJECT_ROOT/backend/alembic.ini" upgrade head \
      >>"$(log_file backend)" 2>&1 || true
  fi
  nohup "$PY" -m uvicorn src.main:app --host 0.0.0.0 --port "$port_backend" \
    --timeout-graceful-shutdown 5 \
    >>"$(log_file backend)" 2>&1 &
  echo $! > "$PID_DIR/backend.pid"
  disown 2>/dev/null || true
}

start_frontend() {
  cd "$PROJECT_ROOT/frontend"
  if [[ ! -d node_modules ]]; then
    if command -v pnpm >/dev/null 2>&1; then pnpm install --prefer-frozen-lockfile
    elif command -v npm >/dev/null 2>&1; then npm install --no-audit --no-fund
    else echo "[start_frontend] 无 pnpm/npm" >&2; return 1; fi
  fi
  export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:$port_backend}"
  export API_URL="${API_URL:-$NEXT_PUBLIC_API_URL}"
  if command -v pnpm >/dev/null 2>&1; then
    nohup pnpm dev -p "$port_frontend" >"$(log_file frontend)" 2>&1 &
  else
    nohup npm run dev -- -p "$port_frontend" >"$(log_file frontend)" 2>&1 &
  fi
  echo $! > "$PID_DIR/frontend.pid"
  disown 2>/dev/null || true
}

# shellcheck disable=SC1091
source "$PROJECT_ROOT/../scripts/lib/service-lib.sh"
dispatch "$@"
