"""phantom CLI 子进程调用 + 工作区管理 + 心跳泵。"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Phantom 工作区基目录。base 是单机/单用户部署，path = base / project_name。
# 多机部署时可设 PHANTOM_PROJECTS_BASE 覆盖。
PROJECTS_BASE_DEFAULT = Path("/Users/lapsdoor/phantom")


def _projects_base() -> Path:
    return Path(os.environ.get("PHANTOM_PROJECTS_BASE") or str(PROJECTS_BASE_DEFAULT))


def resolve_workspace(project_name: str) -> Path:
    """把 task['input']['project_name'] 转成 phantom 工作区绝对路径。

    路径 = PHANTOM_PROJECTS_BASE / project_name（base 默认 /Users/lapsdoor/phantom）。
    AIJuicer 的 idea step 已在该路径下写过 idea.md / requirement.md，
    但若目录不存在（边缘场景）这里幂等创建。
    """
    if not project_name:
        raise ValueError("project_name 为空，task['input']['project_name'] 必须有值")
    if "/" in project_name or project_name.startswith("..") or project_name.startswith("."):
        raise ValueError(
            f"project_name 不安全（含 / 或 .. / 以 . 开头）：{project_name!r}"
        )
    ws = _projects_base() / project_name
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def workspace_has_phantom_state(workspace: Path) -> bool:
    """已经初始化过 phantom 项目吗？（state.json 存在 = 是）"""
    return (workspace / ".phantom" / "state.json").is_file()


import asyncio
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path


class PhantomFailedError(RuntimeError):
    """phantom 子进程退出码非 0。"""

    def __init__(self, exit_code: int, last_lines: list[str]) -> None:
        self.exit_code = exit_code
        self.last_lines = last_lines
        tail = "\n".join(last_lines[-20:])
        super().__init__(
            f"phantom 子进程失败（exit={exit_code}），日志末尾 20 行：\n{tail}"
        )


HeartbeatFn = Callable[[str], Awaitable[None]]


async def _drain(
    stream: asyncio.StreamReader,
    callback: HeartbeatFn | None,
    buffer: list[str],
    *,
    log_level: int = logging.INFO,
    log_prefix: str = "phantom",
) -> None:
    """读 stream（stdout 或 stderr）按行追加到 buffer，并调 callback（每行一次）。

    每行同时通过 logger 落盘，保证日志规范要求的"输出到控制台和日志文件"。
    """
    while True:
        line = await stream.readline()
        if not line:
            return
        text = line.decode(errors="replace").rstrip("\n")
        buffer.append(text)
        logger.log(log_level, "[%s] %s", log_prefix, text)
        if callback is not None:
            try:
                await callback(text)
            except Exception:  # noqa: BLE001 — 心跳失败不应中断子进程
                logger.warning("heartbeat 回调异常，已忽略", exc_info=True)


async def run_phantom(
    *,
    workspace: Path,
    args: list[str],
    heartbeat: HeartbeatFn,
    phantom_bin: str | None = None,
    stderr_callback: HeartbeatFn | None = None,
) -> int:
    """在 workspace 目录下跑 `phantom <args>`，stdout 每行触发 heartbeat。

    - 子进程 cwd = workspace（phantom 的 .phantom/ 状态会落在这里）
    - 环境变量从父进程继承（PHANTOM_*_BACKEND / OPENAI_API_KEY / 等）
    - 退出码 != 0 → 抛 PhantomFailedError（含日志末尾，便于上报 scheduler）
    """
    bin_path = phantom_bin or shutil.which("phantom")
    if not bin_path:
        raise RuntimeError(
            "找不到 phantom CLI（PATH 上没有 phantom）。请先在 AIDevelop 仓库根目录跑 ./install.sh。"
        )

    logger.info("启动 phantom 子进程 bin=%s args=%s cwd=%s", bin_path, args, workspace)
    proc = await asyncio.create_subprocess_exec(
        bin_path,
        *args,
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )
    logger.info("phantom 子进程已启动 pid=%s", proc.pid)
    stdout_buffer: list[str] = []
    stderr_buffer: list[str] = []
    assert proc.stdout is not None and proc.stderr is not None
    await asyncio.gather(
        _drain(proc.stdout, heartbeat, stdout_buffer, log_prefix="phantom.stdout"),
        _drain(
            proc.stderr,
            stderr_callback,
            stderr_buffer,
            log_level=logging.WARNING,
            log_prefix="phantom.stderr",
        ),
    )
    rc = await proc.wait()
    logger.info("phantom 子进程退出 pid=%s rc=%s", proc.pid, rc)
    if rc != 0:
        # 把 stderr 末尾也带上（phantom 错误一般在 stderr）
        merged = stdout_buffer + stderr_buffer
        raise PhantomFailedError(rc, merged)
    return rc


from aijuicer_sdk import FatalError, RetryableError


# stderr / stdout 含其中任一关键字 → 视为可重试
_RETRYABLE_PATTERNS = (
    "调用超时",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "Connection refused",
    "ConnectionResetError",
    "ETIMEDOUT",
    "Temporary failure",
)

# stderr / stdout 含其中任一关键字 → 视为不可重试（结构性问题，重试无意义）
_FATAL_PATTERNS = (
    ".phantom/plan.locked.md 已存在",
    "plan.locked.md 不存在",
    "需要 .phantom/plan.locked.md",
    "需要提供需求文档",
    "max_rounds",
    "找不到 phantom CLI",
)


def classify_phantom_failure(err: PhantomFailedError) -> RetryableError | FatalError:
    """根据 phantom 输出关键字决定 retryable / fatal。"""
    blob = "\n".join(err.last_lines)
    for pat in _FATAL_PATTERNS:
        if pat in blob:
            return FatalError(f"phantom 结构性失败（{pat}）：{err}")
    for pat in _RETRYABLE_PATTERNS:
        if pat in blob:
            return RetryableError(f"phantom 临时失败（{pat}）：{err}")
    # 默认乐观——和 SDK 的兜底策略保持一致
    return RetryableError(f"phantom 未知失败（exit={err.exit_code}）：{err}")
