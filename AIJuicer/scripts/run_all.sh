#!/usr/bin/env bash
# 本机一键启动 scheduler + webui [+ 6 个示例 agent]。退出时（Ctrl+C）一起清理。
#
# 用法：
#     ./scripts/run_all.sh                    # 默认只起 scheduler + webui；端口被占则报错退出
#     ./scripts/run_all.sh --with-agents      # 同时起 6 个示例 agent
#     ./scripts/run_all.sh --force            # 端口被占时强制 kill 占用方再跑
#     ./scripts/run_all.sh restart            # 等价于 --force：先停占用方再启动
#     ./scripts/run_all.sh -h                 # 帮助
set -euo pipefail
cd "$(dirname "$0")/.."

START_AGENTS=0
FORCE_KILL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --with-agents|--agents)
      START_AGENTS=1
      shift
      ;;
    --no-agents|--without-agents)
      START_AGENTS=0
      shift
      ;;
    -f|--force|--kill|restart)
      FORCE_KILL=1
      shift
      ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0
      ;;
    *)
      echo "未知参数：$1（用 -h 看帮助）" >&2
      exit 2
      ;;
  esac
done

: "${AIJUICER_SERVER:=http://127.0.0.1:8000}"
: "${AIJUICER_REDIS_URL:=redis://127.0.0.1:6379/0}"
# 本机开发：让 Agent /health 端口绑在 127.0.0.1，UI 上的链接才能直接点开。
# 部署到多机时取消该默认（注释掉下行），SDK 会自动探测对外 IP。
: "${AIJUICER_AGENT_HOST:=127.0.0.1}"
export AIJUICER_SERVER AIJUICER_REDIS_URL AIJUICER_AGENT_HOST

mkdir -p var/logs

# 端口预检：8000 / 3000 被占会导致 uvicorn / next dev 立即退出，
# 触发下面的 wait -n + trap，整个脚本看起来"刚启动就停"。
# 加 --force/-f 时直接 kill 占用方；不加则报错退出。
for port in 8000 3000; do
  pids=$(lsof -nPi ":$port" -sTCP:LISTEN -t 2>/dev/null || true)
  if [ -n "$pids" ]; then
    if [ "${FORCE_KILL}" = "1" ]; then
      echo ">> --force：kill port $port 占用进程 → $(echo $pids | tr '\n' ' ')"
      kill -9 $pids 2>/dev/null || true
      # 等端口真正释放（macOS 释放有 1-2s 延迟）
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        sleep 0.3
        lsof -nPi ":$port" -sTCP:LISTEN -t >/dev/null 2>&1 || break
      done
      if lsof -nPi ":$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "!! port $port 仍被占用（kill 失败）" >&2
        exit 1
      fi
    else
      echo "!! port $port 已被占用：" >&2
      lsof -nPi ":$port" -sTCP:LISTEN >&2
      echo "!! 加 --force 可自动 kill 后再跑" >&2
      exit 1
    fi
  fi
done

PIDS=()
cleanup() {
  echo ">> stopping pids: ${PIDS[*]}"
  kill "${PIDS[@]}" 2>/dev/null || true
  wait "${PIDS[@]}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

source .venv/bin/activate

echo ">> scheduler @ :8000"
uvicorn scheduler.main:app --host 127.0.0.1 --port 8000 --log-level info \
  >var/logs/scheduler.log 2>&1 &
PIDS+=($!)

# 等 scheduler 起来
until curl -sf "$AIJUICER_SERVER/health" >/dev/null; do sleep 0.5; done
echo ">> scheduler ready"

if [ "${START_AGENTS}" = "1" ]; then
  for step in idea requirement plan design devtest deploy; do
    echo ">> agent ai-$step"
    python -m sdk.examples.ai_$step >"var/logs/agent-$step.log" 2>&1 &
    PIDS+=($!)
  done
else
  echo ">> --no-agents 已指定，跳过 6 个示例 agent"
fi

# Web UI（仅当已 pnpm install）
if [ -d webui/node_modules ]; then
  echo ">> webui @ :3000"
  (cd webui && NEXT_PUBLIC_API_BASE="$AIJUICER_SERVER" \
    PATH=/opt/homebrew/bin:$PATH pnpm dev >../var/logs/webui.log 2>&1) &
  PIDS+=($!)
else
  echo "!! webui/node_modules 未安装；跳过 UI。先 cd webui && pnpm install"
fi

echo ">> all up. Ctrl+C to stop. Tail: tail -f var/logs/*.log"
wait -n
