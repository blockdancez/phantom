#!/usr/bin/env bash
# 前台启动 ai-devtest worker：控制台 + 文件双路日志（由 Python logging 写入）
# 默认日志路径：/Users/lapsdoor/phantom/logs/ai-devtest.log
# 用法：bash scripts/run.sh
# 退出：Ctrl+C
set -e
cd "$(dirname "$0")/.."

if [[ ! -x .venv/bin/python ]]; then
  echo "[run.sh] 找不到 .venv/bin/python，请先：python3.12 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
  exit 1
fi

export PYTHONUNBUFFERED=1

: "${AI_DEVTEST_LOG_DIR:=/Users/lapsdoor/phantom/logs}"
export AI_DEVTEST_LOG_DIR
mkdir -p "$AI_DEVTEST_LOG_DIR"

: "${AIJUICER_SERVER:=http://127.0.0.1:8000}"
export AIJUICER_SERVER

echo "[run.sh] AIJUICER_SERVER=$AIJUICER_SERVER"
echo "[run.sh] AI_DEVTEST_LOG_DIR=$AI_DEVTEST_LOG_DIR"
echo "[run.sh] 控制台与日志文件均由 Python logging 同步写入；Ctrl+C 退出"
echo "------------------------------------------------------------"

exec .venv/bin/python -m ai_devtest.agent
