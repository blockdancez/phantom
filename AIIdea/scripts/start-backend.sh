#!/usr/bin/env bash
set -euo pipefail

# Locate the repo root from the script's own path so this works regardless of
# the invoker's cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

cd "${BACKEND_DIR}"

# Port priority: PORT > BACKEND_PORT > .phantom/port.backend > 53839
PORT="${PORT:-${BACKEND_PORT:-}}"
if [ -z "${PORT}" ] && [ -f "${REPO_ROOT}/.phantom/port.backend" ]; then
  PORT="$(tr -d '[:space:]' < "${REPO_ROOT}/.phantom/port.backend")"
fi
PORT="${PORT:-53839}"

# Prefer python from the project venv if one exists; fall back to system.
if [ -x "${BACKEND_DIR}/.venv/bin/python" ]; then
  PYTHON="${BACKEND_DIR}/.venv/bin/python"
elif [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

export PYTHONPATH="${BACKEND_DIR}:${PYTHONPATH:-}"

# Run migrations if alembic is importable; don't hard-fail on non-reachable DB
# so a developer can still inspect the failure via the /api/health endpoint.
if "${PYTHON}" -c "import alembic" >/dev/null 2>&1; then
  "${PYTHON}" -m alembic -c "${BACKEND_DIR}/alembic.ini" upgrade head || {
    echo "[start-backend] alembic upgrade failed; starting API anyway for inspection" >&2
  }
fi

# Run uvicorn in the background so this shell can install a trap that
# guarantees Ctrl+C actually returns control to the user. uvicorn's
# graceful shutdown hangs on the AIJuicer redis XREADGROUP / asyncio
# fire-and-forget tasks even with --timeout-graceful-shutdown — the trap
# below sends SIGINT first, waits 4s, then escalates to SIGKILL.
"${PYTHON}" -m uvicorn src.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --timeout-graceful-shutdown 5 &
SERVER_PID=$!

cleanup() {
    if kill -0 "${SERVER_PID}" 2>/dev/null; then
        echo "[start-backend] sending SIGINT to ${SERVER_PID}, will SIGKILL in 4s if still alive..." >&2
        kill -INT "${SERVER_PID}" 2>/dev/null || true
        for _ in 1 2 3 4; do
            sleep 1
            if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
                exit 0
            fi
        done
        echo "[start-backend] graceful shutdown timed out, SIGKILL ${SERVER_PID}" >&2
        kill -9 "${SERVER_PID}" 2>/dev/null || true
    fi
    exit 0
}
trap cleanup INT TERM
wait "${SERVER_PID}"
