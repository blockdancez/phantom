#!/usr/bin/env bash
# 共享服务管理库。被各子项目的 scripts/service.sh source。
#
# 调用方在 source 本文件之前必须先设置：
#   PROJECT_ROOT   绝对路径，子项目根
#   SERVICE_NAME   服务前缀，如 ai-juicer / ai-idea / ai-plan
#   SERVICES       Bash 数组，列出本项目的子服务名，如 (scheduler webui)
#
# 调用方为每个 svc 提供:
#   start_<svc>()   函数体内 cd + 启动命令(nohup ... > "$(log_file <svc>)" 2>&1 &;
#                   echo $! > "$PID_DIR/<svc>.pid")
#   port_<svc>      可选；声明端口号供端口占用预检
#   sig_<svc>       可选；pgrep -f 关键字，用于发现 orphan
#
# 调用方在最末尾 source 本文件后调用：dispatch "$@"
#
# 子命令统一为：start | stop | restart | status | logs | run

set -euo pipefail

: "${LOG_DIR:=/Users/lapsdoor/phantom/logs}"
PID_DIR="$PROJECT_ROOT/.pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
BLUE=$'\033[0;34m'
MAGENTA=$'\033[0;35m'
CYAN=$'\033[0;36m'
RESET=$'\033[0m'

log_file() { printf '%s/%s-%s.log' "$LOG_DIR" "$SERVICE_NAME" "$1"; }

is_running() {
  local pidfile="$PID_DIR/$1.pid"
  [[ -f "$pidfile" ]] || return 1
  kill -0 "$(cat "$pidfile")" 2>/dev/null
}

port_in_use() {
  lsof -nPiTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

discover_pids() {
  local svc="$1" pidfile="$PID_DIR/$svc.pid"
  local tracked="" orphans=""
  [[ -f "$pidfile" ]] && tracked=$(cat "$pidfile")
  local sig_var="sig_${svc}"
  local sig="${!sig_var:-}"
  [[ -n "$sig" ]] && orphans=$(pgrep -f "$sig" 2>/dev/null || true)
  printf '%s\n%s\n' "$tracked" "$orphans" | awk 'NF && !seen[$0]++'
}

prefix_color() {
  local svc="$1" h
  h=$(echo -n "$svc" | cksum | awk '{print $1 % 6}')
  case "$h" in
    0) printf '%s' "$CYAN" ;;
    1) printf '%s' "$MAGENTA" ;;
    2) printf '%s' "$YELLOW" ;;
    3) printf '%s' "$GREEN" ;;
    4) printf '%s' "$BLUE" ;;
    5) printf '%s' "$RED" ;;
  esac
}

start_one() {
  local svc="$1"
  if is_running "$svc"; then
    echo "${YELLOW}[skip]${RESET} $SERVICE_NAME/$svc already running (pid $(cat "$PID_DIR/$svc.pid"))"
    return 0
  fi
  local port_var="port_${svc}"
  local port="${!port_var:-}"
  if [[ -n "$port" ]] && port_in_use "$port"; then
    echo "${RED}[fail]${RESET} $SERVICE_NAME/$svc: port $port 被占用" >&2
    return 1
  fi
  if ! type "start_$svc" >/dev/null 2>&1; then
    echo "${RED}[fail]${RESET} $SERVICE_NAME/$svc: 未定义 start_$svc()" >&2
    return 1
  fi
  ( "start_$svc" ) || return 1
  sleep 1
  if is_running "$svc"; then
    echo "${GREEN}[ok]  ${RESET} $SERVICE_NAME/$svc up (pid $(cat "$PID_DIR/$svc.pid"), log: $(log_file "$svc"))"
  else
    echo "${RED}[fail]${RESET} $SERVICE_NAME/$svc 启动失败；查看 $(log_file "$svc")"
    rm -f "$PID_DIR/$svc.pid"
    return 1
  fi
}

stop_one() {
  local svc="$1" pidfile="$PID_DIR/$svc.pid"
  local pids
  pids=$(discover_pids "$svc")
  if [[ -z "$pids" ]]; then
    echo "${YELLOW}[skip]${RESET} $SERVICE_NAME/$svc not running"
    rm -f "$pidfile"
    return 0
  fi
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  for _ in 1 2 3 4 5; do
    local alive=0
    for pid in $pids; do kill -0 "$pid" 2>/dev/null && { alive=1; break; }; done
    [[ "$alive" -eq 0 ]] && break
    sleep 1
  done
  for pid in $pids; do
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  done
  echo "${GREEN}[ok]  ${RESET} $SERVICE_NAME/$svc stopped (pids: $(echo $pids | tr '\n' ' '))"
  rm -f "$pidfile"
}

status_one() {
  local svc="$1"
  if is_running "$svc"; then
    echo "${GREEN}●${RESET} $SERVICE_NAME/$svc   pid=$(cat "$PID_DIR/$svc.pid")   log=$(log_file "$svc")"
  else
    echo "${RED}○${RESET} $SERVICE_NAME/$svc   stopped"
  fi
}

tail_with_prefix() {
  local svc="$1" logfile="$2" color
  color=$(prefix_color "$svc")
  tail -n 0 -F "$logfile" 2>/dev/null | while IFS= read -r line; do
    printf '%s%-24s%s│ %s\n' "$color" "$SERVICE_NAME/$svc" "$RESET" "$line"
  done
}

follow_logs() {
  local svcs=("$@")
  [[ ${#svcs[@]} -eq 0 ]] && return 0
  for svc in "${svcs[@]}"; do : >>"$(log_file "$svc")"; done
  echo
  echo "${CYAN}── following logs (Ctrl+C 仅 detach 日志，服务继续后台运行) ──${RESET}"
  local tail_pids=()
  for svc in "${svcs[@]}"; do
    tail_with_prefix "$svc" "$(log_file "$svc")" &
    tail_pids+=($!)
  done
  _detach() {
    for pid in "${tail_pids[@]}"; do kill "$pid" 2>/dev/null || true; done
    echo
    echo "${YELLOW}detached. 用 \`$0 status\` / \`$0 stop\` 管理。${RESET}"
    exit 0
  }
  trap _detach INT TERM
  wait
}

resolve_targets() {
  local target="${1:-all}"
  if [[ "$target" == "all" ]]; then
    printf '%s\n' "${SERVICES[@]}"
  else
    local found=0
    for s in "${SERVICES[@]}"; do
      [[ "$s" == "$target" ]] && { found=1; break; }
    done
    if [[ "$found" == 1 ]]; then
      printf '%s\n' "$target"
    else
      echo "${RED}unknown service:${RESET} $target (valid: ${SERVICES[*]} all)" >&2
      return 2
    fi
  fi
}

usage() {
  cat <<EOF
$SERVICE_NAME 服务管理器

用法:
  $0 start   [<svc>|all] [--no-follow]   后台启动 + 流式日志（默认）
  $0 stop    [<svc>|all]                 优雅停止 (5s 内 SIGTERM，超时 SIGKILL)
  $0 restart [<svc>|all] [--no-follow]
  $0 status                              所有子服务状态
  $0 logs    <svc>                       tail -f 单个服务日志

子服务: ${SERVICES[*]}
PID 目录: $PID_DIR
日志目录: $LOG_DIR (文件名: $SERVICE_NAME-<svc>.log)

环境变量:
  LOG_DIR        自定义日志目录（默认 /Users/lapsdoor/phantom/logs）
EOF
}

dispatch() {
  local cmd="${1:-status}"
  shift || true

  local follow=1
  local target=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --no-follow) follow=0; shift ;;
      -h|--help) usage; exit 0 ;;
      *) target="$1"; shift ;;
    esac
  done
  target="${target:-all}"

  case "$cmd" in
    start|stop|restart)
      local targets=()
      mapfile -t targets < <(resolve_targets "$target") || exit 2
      [[ ${#targets[@]} -eq 0 ]] && { echo "no targets"; exit 0; }
      case "$cmd" in
        start)
          echo "${CYAN}── starting ${SERVICE_NAME} ──${RESET}"
          for svc in "${targets[@]}"; do start_one "$svc" || true; done
          [[ "$follow" == 1 ]] && follow_logs "${targets[@]}"
          ;;
        stop)
          echo "${CYAN}── stopping ${SERVICE_NAME} ──${RESET}"
          for svc in "${targets[@]}"; do stop_one "$svc"; done
          ;;
        restart)
          echo "${CYAN}── restarting ${SERVICE_NAME} ──${RESET}"
          for svc in "${targets[@]}"; do stop_one "$svc"; done
          for svc in "${targets[@]}"; do start_one "$svc" || true; done
          [[ "$follow" == 1 ]] && follow_logs "${targets[@]}"
          ;;
      esac
      ;;
    status)
      echo "${CYAN}── status ${SERVICE_NAME} ──${RESET}"
      for svc in "${SERVICES[@]}"; do status_one "$svc"; done
      ;;
    logs)
      [[ -z "$target" || "$target" == "all" ]] && { echo "Usage: $0 logs <svc>" >&2; exit 1; }
      exec tail -F "$(log_file "$target")"
      ;;
    -h|--help|help) usage ;;
    *) usage; exit 1 ;;
  esac
}
