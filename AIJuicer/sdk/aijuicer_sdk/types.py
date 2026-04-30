"""Handler 入参 / 出参的强类型定义。

Handler 契约（0.6.0+，**单参数**）：

    async def handle(ctx: AgentContext) -> HandlerOutput | None:
        ...

    *  ctx：同时承载数据（task_id / workflow_id / project_name / step / attempt /
       input / request_id）和方法（save_artifact / load_artifact / heartbeat / log）。
       详见 `AgentContext`。
    *  返回值：dict[str, Any] 或 None。会被写进 step_executions.output（JSONB）
       并广播 SSE，UI 详情页可见。返回 None 等同于 {}。

`TaskPayload` 是 scheduler 派发到 Redis Stream 里的原始消息 dict 类型。SDK 内部用，
handler 一般通过 `ctx.<field>` 访问；少数场景需要原始 dict 时用 `ctx.raw_payload`，
配合此 TypedDict 做类型提示。

异常约定：

    *  raise FatalError      → 不重试，进入 AWAITING_MANUAL_ACTION
    *  raise RetryableError  → 在 max_retries 内自动重试
    *  其它任意 Exception    → 兜底按 Retryable 处理（避免 bug 让任务静默丢失）
"""

from __future__ import annotations

from typing import Any, TypedDict


class TaskPayload(TypedDict, total=False):
    """从 Redis Stream 拉到的一条任务消息（agent 端的视角）。

    所有字段都是 scheduler 入队时填的；JSON 字符串经 SDK `json.loads` 还原。

    必填字段（scheduler 永远会带）：
      - task_id      : 该次执行的 UUID（= step_executions.id）；用于 task_start /
                       task_complete / task_fail / task_heartbeat 的 URL
      - workflow_id  : 工作流 UUID
      - project_name : 项目 slug（小写英文 + 短横线，全局唯一）。后续做代码仓库目录、
                       数据库名、项目文件夹命名都应基于这个值。
      - step         : 6 个 step 之一（idea / requirement / plan / design / devtest / deploy）
      - attempt      : 第几次重试。1 = 首跑；> 1 = 重跑产生的新 attempt
      - input        : 工作流 input dict（用户创建工作流时提交 + 历次重跑写入的
                       user_feedback 字典）。常见字段：
                         - text          : 用户最初输入的文本
                         - user_feedback : { step → 该 step 的最新重跑指令 } 字典
      - request_id   : 链路追踪 id；SDK 自动放进所有上行 HTTP header 和日志

    向前兼容字段（SDK 读取，handler 一般不用）：
      - artifact_root : 旧 FS 模式下的本地目录路径；HTTP 模式下仅作占位，不用
    """

    task_id: str
    workflow_id: str
    project_name: str
    step: str
    attempt: int
    input: dict[str, Any]
    request_id: str
    artifact_root: str  # legacy, advisory only


HandlerOutput = dict[str, Any]
"""Handler 的返回值类型——一个 JSON-serializable 的字典。

写进 step_executions.output 列（JSONB），并随 task.succeeded SSE 事件广播。
返回 None 等同 {}。建议放些"概要信息"如 `{"chosen_topic": "...", "tokens": 1234}`，
具体产物用 `ctx.save_artifact(key, content)` 保存，不要塞进 output。
"""
