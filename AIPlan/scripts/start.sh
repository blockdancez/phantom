#!/usr/bin/env bash
# 后台启动 ai-plan worker（连 AIJuicer scheduler，常驻拉任务）
# 日志由 Python logging 写入 $AI_PLAN_LOG_DIR/ai-plan.log（默认 /Users/lapsdoor/phantom/logs）
# nohup 兜底捕获未走 logging 的极早期输出
set -e
cd "$(dirname "$0")/.."

: "${AI_PLAN_LOG_DIR:=/Users/lapsdoor/phantom/logs}"
export AI_PLAN_LOG_DIR
mkdir -p "$AI_PLAN_LOG_DIR"

nohup .venv/bin/python -m ai_plan.agent \
  > "$AI_PLAN_LOG_DIR/ai-plan.bootstrap.log" 2>&1 &
echo "ai-plan PID=$! → 主日志：$AI_PLAN_LOG_DIR/ai-plan.log"
