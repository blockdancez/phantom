"""Prometheus 指标（spec § 6.2）。"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

registry = CollectorRegistry()

workflows_total = Counter(
    "aijuicer_workflows_total",
    "Workflow terminal outcomes累计",
    ["status"],
    registry=registry,
)
step_duration_seconds = Histogram(
    "aijuicer_step_duration_seconds",
    "Step 执行时长（秒）",
    ["step", "result"],
    registry=registry,
)
step_retries_total = Counter(
    "aijuicer_step_retries_total",
    "Step 重试累计",
    ["step"],
    registry=registry,
)
agents_online = Gauge(
    "aijuicer_agents_online",
    "在线 agent 数",
    ["step"],
    registry=registry,
)
task_queue_depth = Gauge(
    "aijuicer_task_queue_depth",
    "Redis Stream 待处理深度",
    ["step"],
    registry=registry,
)
heartbeat_timeout_total = Counter(
    "aijuicer_heartbeat_timeout_total",
    "心跳超时累计",
    ["step"],
    registry=registry,
)
manual_interventions_total = Counter(
    "aijuicer_manual_interventions_total",
    "人工介入累计",
    registry=registry,
)
dispatch_no_online_total = Counter(
    "aijuicer_dispatch_no_online_total",
    "派发任务时该 step 无在线 Agent 的次数（任务仍 XADD，等待 Agent 上线消费）",
    ["step"],
    registry=registry,
)


def render() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
