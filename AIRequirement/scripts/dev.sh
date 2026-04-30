#!/usr/bin/env bash
#
# Dev orchestrator for the three local processes:
#   backend  — FastAPI (uvicorn)         port 8010
#   frontend — Vite                       port 3010
#   worker   — AIJuicer requirement node  (talks to scheduler at AIJUICER_SERVER)
#
# Usage:
#   scripts/dev.sh start   [all|backend|frontend|worker]   # spawn + tail logs
#   scripts/dev.sh stop    [all|backend|frontend|worker]
#   scripts/dev.sh restart [all|backend|frontend|worker]   # spawn + tail logs
#   scripts/dev.sh status
#   scripts/dev.sh logs    <backend|frontend|worker>       # plain tail -f
#
# `start` and `restart` stay attached to the terminal and stream prefixed
# logs from each service. Ctrl+C only detaches the tail — the services keep
# running in the background (tracked via .pids/<svc>.pid).
#
# PIDs land in .pids/ (gitignored). Per-process stdout/stderr is captured to
# $LOG_DIR/$SERVICE_NAME-<svc>.log (defaults: /Users/lapsdoor/phantom/logs/
# ai-requirement-{backend,frontend,worker}.log; override via LOG_DIR /
# SERVICE_NAME env). Sources backend/.env for AIJUICER_*, OPENAI_API_KEY, etc.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$ROOT/.pids"
mkdir -p "$PID_DIR"

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'
MAGENTA=$'\033[0;35m'
CYAN=$'\033[0;36m'
RESET=$'\033[0m'

# Load backend/.env so AIJUICER_* etc. land in env for the worker.
if [[ -f "$ROOT/backend/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/backend/.env"
  set +a
fi

# AIJuicer defaults if .env doesn't pin them.
export AIJUICER_SERVER="${AIJUICER_SERVER:-http://127.0.0.1:8000}"
export AIJUICER_REDIS_URL="${AIJUICER_REDIS_URL:-redis://127.0.0.1:6379/0}"
export AIJUICER_AGENT_NAME="${AIJUICER_AGENT_NAME:-ai-requirement}"
export AIJUICER_CONCURRENCY="${AIJUICER_CONCURRENCY:-1}"

# Log location matches the Python app: <LOG_DIR>/<SERVICE_NAME>-<role>.log.
# Defaults align with backend/app/logging_setup.py.
LOG_DIR="${LOG_DIR:-/Users/lapsdoor/phantom/logs}"
SERVICE_NAME="${SERVICE_NAME:-ai-requirement}"
mkdir -p "$LOG_DIR"

log_file() {
  printf '%s/%s-%s.log' "$LOG_DIR" "$SERVICE_NAME" "$1"
}

SERVICES=(backend frontend worker)

# ─────────────────────────── helpers ───────────────────────────
is_running() {
  local pidfile="$PID_DIR/$1.pid"
  [[ -f "$pidfile" ]] || return 1
  kill -0 "$(cat "$pidfile")" 2>/dev/null
}

port_in_use() {
  lsof -iTCP:"$1" -sTCP:LISTEN -nP >/dev/null 2>&1
}

start_backend() {
  port_in_use 8010 && {
    echo "${RED}[fail]${RESET} backend: port 8010 already in use"
    return 1
  }
  cd "$ROOT/backend"
  nohup python3 -m uvicorn app.main:create_app --factory \
    --host 0.0.0.0 --port 8010 \
    >"$(log_file backend)" 2>&1 &
  echo $! >"$PID_DIR/backend.pid"
}

start_frontend() {
  port_in_use 3010 && {
    echo "${RED}[fail]${RESET} frontend: port 3010 already in use"
    return 1
  }
  cd "$ROOT/frontend"
  # Pin PORT=3010 here: backend/.env exports PORT=8010 for uvicorn, and Vite
  # would otherwise pick that up (vite.config.ts reads process.env.PORT) and
  # fall back to 8011 when it collides with the backend.
  PORT=3010 nohup npm run dev >"$(log_file frontend)" 2>&1 &
  echo $! >"$PID_DIR/frontend.pid"
}

start_worker() {
  cd "$ROOT/backend"
  nohup python3 -m app.aijuicer_node >"$(log_file worker)" 2>&1 &
  echo $! >"$PID_DIR/worker.pid"
}

start_one() {
  local svc="$1"
  if is_running "$svc"; then
    echo "${YELLOW}[skip]${RESET} $svc already running (pid $(cat "$PID_DIR/$svc.pid"))"
    return
  fi
  ( "start_$svc" ) || return 1
  sleep 1
  if is_running "$svc"; then
    echo "${GREEN}[ok]  ${RESET} $svc up (pid $(cat "$PID_DIR/$svc.pid"), log: $(log_file "$svc"))"
  else
    echo "${RED}[fail]${RESET} $svc failed to start; check $(log_file "$svc")"
    rm -f "$PID_DIR/$svc.pid"
  fi
}

discover_pids() {
  # Returns deduped pids: tracked pidfile + any orphan that matches the
  # service signature (started outside this script). Empty if nothing found.
  local svc="$1"
  local pidfile="$PID_DIR/$svc.pid"
  local tracked=""
  local orphans=""

  [[ -f "$pidfile" ]] && tracked=$(cat "$pidfile")

  case "$svc" in
    backend)  orphans=$(pgrep -f "uvicorn app.main" 2>/dev/null || true) ;;
    frontend) orphans=$(lsof -tiTCP:3010 -sTCP:LISTEN 2>/dev/null || true) ;;
    worker)   orphans=$(pgrep -f "app.aijuicer_node" 2>/dev/null || true) ;;
  esac

  printf '%s\n%s\n' "$tracked" "$orphans" | awk 'NF && !seen[$0]++'
}

stop_one() {
  local svc="$1"
  local pidfile="$PID_DIR/$svc.pid"
  local pids
  pids=$(discover_pids "$svc")

  if [[ -z "$pids" ]]; then
    echo "${YELLOW}[skip]${RESET} $svc not running"
    rm -f "$pidfile"
    return
  fi

  # SIGTERM all
  for pid in $pids; do
    kill "$pid" 2>/dev/null || true
  done

  # Wait up to 5s for graceful exit
  for _ in 1 2 3 4 5; do
    local alive=0
    for pid in $pids; do kill -0 "$pid" 2>/dev/null && alive=1 && break; done
    [[ "$alive" -eq 0 ]] && break
    sleep 1
  done

  # Force-kill survivors
  for pid in $pids; do
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
  done

  echo "${GREEN}[ok]  ${RESET} $svc stopped (pids: $(echo $pids | tr '\n' ' '))"
  rm -f "$pidfile"
}

status_one() {
  local svc="$1"
  if is_running "$svc"; then
    echo "${GREEN}●${RESET} $svc   pid=$(cat "$PID_DIR/$svc.pid")   log=$(log_file "$svc")"
  else
    echo "${RED}○${RESET} $svc   stopped"
  fi
}

prefix_color() {
  case "$1" in
    backend)  printf '%s' "$CYAN" ;;
    frontend) printf '%s' "$MAGENTA" ;;
    worker)   printf '%s' "$YELLOW" ;;
    *)        printf '%s' "$RESET" ;;
  esac
}

tail_with_prefix() {
  local svc="$1"
  local logfile="$2"
  local color
  color=$(prefix_color "$svc")
  tail -n 0 -F "$logfile" 2>/dev/null | while IFS= read -r line; do
    printf '%s%-8s%s│ %s\n' "$color" "$svc" "$RESET" "$line"
  done
}

follow_logs() {
  local svcs=("$@")
  [[ ${#svcs[@]} -eq 0 ]] && return 0

  for svc in "${svcs[@]}"; do
    : >>"$(log_file "$svc")"
  done

  echo
  echo "${CYAN}── following logs (Ctrl+C to detach; services keep running) ──${RESET}"

  local tail_pids=()
  for svc in "${svcs[@]}"; do
    tail_with_prefix "$svc" "$(log_file "$svc")" &
    tail_pids+=($!)
  done

  # shellcheck disable=SC2317  # invoked via trap
  _detach() {
    for pid in "${tail_pids[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    echo
    echo "${YELLOW}detached. services keep running. \`$0 status\` / \`$0 stop\` to manage.${RESET}"
    exit 0
  }
  trap _detach INT TERM
  wait
}

resolve_targets() {
  local target="${1:-all}"
  if [[ "$target" == "all" ]]; then
    printf '%s\n' "${SERVICES[@]}"
  elif [[ " ${SERVICES[*]} " == *" $target "* ]]; then
    printf '%s\n' "$target"
  else
    echo "${RED}unknown service:${RESET} $target (valid: ${SERVICES[*]} all)" >&2
    exit 2
  fi
}

# ─────────────────────────── dispatch ───────────────────────────
cmd="${1:-status}"
target="${2:-all}"

mapfile -t TARGETS < <(resolve_targets "$target")

case "$cmd" in
start)
  echo "${CYAN}── starting ──${RESET}"
  for svc in "${TARGETS[@]}"; do start_one "$svc"; done
  follow_logs "${TARGETS[@]}"
  ;;
stop)
  echo "${CYAN}── stopping ──${RESET}"
  for svc in "${TARGETS[@]}"; do stop_one "$svc"; done
  ;;
restart)
  echo "${CYAN}── restarting ──${RESET}"
  for svc in "${TARGETS[@]}"; do stop_one "$svc"; done
  for svc in "${TARGETS[@]}"; do start_one "$svc"; done
  follow_logs "${TARGETS[@]}"
  ;;
status)
  echo "${CYAN}── status ──${RESET}"
  for svc in "${SERVICES[@]}"; do status_one "$svc"; done
  ;;
logs)
  if [[ -z "${2:-}" || "$2" == "all" ]]; then
    echo "Usage: $0 logs <backend|frontend|worker>" >&2
    exit 1
  fi
  exec tail -f "$(log_file "$2")"
  ;;
*)
  echo "Usage: $0 {start|stop|restart|status|logs} [backend|frontend|worker|all]" >&2
  exit 1
  ;;
esac
