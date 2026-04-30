#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_DIR="${REPO_ROOT}/frontend"

cd "${FRONTEND_DIR}"

# Port priority: FRONTEND_PORT > .phantom/port.frontend > 53840
PORT="${FRONTEND_PORT:-}"
if [ -z "${PORT}" ] && [ -f "${REPO_ROOT}/.phantom/port.frontend" ]; then
  PORT="$(tr -d '[:space:]' < "${REPO_ROOT}/.phantom/port.frontend")"
fi
PORT="${PORT:-53840}"

# Make sure NEXT_PUBLIC_API_URL + API_URL point at the matching backend port
# if the operator hasn't set it explicitly.
BACKEND_PORT_VALUE="${BACKEND_PORT:-}"
if [ -z "${BACKEND_PORT_VALUE}" ] && [ -f "${REPO_ROOT}/.phantom/port.backend" ]; then
  BACKEND_PORT_VALUE="$(tr -d '[:space:]' < "${REPO_ROOT}/.phantom/port.backend")"
fi
BACKEND_PORT_VALUE="${BACKEND_PORT_VALUE:-53839}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:${BACKEND_PORT_VALUE}}"
export API_URL="${API_URL:-${NEXT_PUBLIC_API_URL}}"

# Prefer an existing node_modules install; only install if missing.
if [ ! -d "${FRONTEND_DIR}/node_modules" ]; then
  if command -v pnpm >/dev/null 2>&1; then
    pnpm install --prefer-frozen-lockfile
  elif command -v npm >/dev/null 2>&1; then
    npm install --no-audit --no-fund
  else
    echo "[start-frontend] no package manager found (pnpm/npm)" >&2
    exit 1
  fi
fi

if command -v pnpm >/dev/null 2>&1; then
  exec pnpm dev -p "${PORT}"
else
  exec npm run dev -- -p "${PORT}"
fi
