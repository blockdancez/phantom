#!/usr/bin/env bash
# 测试用假 phantom：把所有 args 写到 stderr（让 test 断言）+ 模拟 stdout 心跳行
# 退出码由 FAKE_PHANTOM_EXIT 环境变量控制（默认 0）
set -e
echo "FAKE_PHANTOM_ARGS: $*" >&2
echo "FAKE_PHANTOM_CWD: $PWD" >&2
echo "[phantom] starting"
sleep 0.05
echo "[phantom] doing work"
sleep 0.05
echo "[phantom] done"
exit "${FAKE_PHANTOM_EXIT:-0}"
