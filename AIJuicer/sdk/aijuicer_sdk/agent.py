"""Agent 主类与执行循环（spec § 5）。

M2 最小可用：
- 装饰器收集 handler
- register → fetch_loop(XREADGROUP) → worker 并发 → start/complete/fail → XACK
- 手动 ctx.heartbeat（自动心跳 loop 留到 M3）
- RetryableError / FatalError 按 spec § 5.2 分类上报
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import socket
import threading
import uuid
from collections.abc import Awaitable, Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import redis.asyncio as redis_async
import structlog
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError as RedisResponseError

from aijuicer_sdk.context import AgentContext
from aijuicer_sdk.errors import FatalError, RetryableError
from aijuicer_sdk.logging import configure_sdk_logging
from aijuicer_sdk.transport import SchedulerClient
from aijuicer_sdk.types import HandlerOutput


def _detect_local_ip() -> str:
    """通过出站 socket 获取本机出网 IP；失败回落到 127.0.0.1。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        with contextlib.suppress(OSError):
            s.close()


class _HealthHandler(BaseHTTPRequestHandler):
    """最小 /health 端点。供 UI 显示 ip:port、未来可用作 LB / 反向探活。"""

    agent_payload: dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802 — stdlib 接口
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"status": "ok", **self.agent_payload}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002,N802 — stdlib 接口
        return  # 静默 stdlib HTTPServer 日志，避免污染 stdout


Handler = Callable[[AgentContext], Awaitable[HandlerOutput | None]]
"""Handler 函数签名：

    async def handle(ctx: AgentContext) -> HandlerOutput | None: ...

ctx 同时承载**数据**（task_id / workflow_id / project_name / step / attempt / input /
request_id）和**方法**（heartbeat / save_artifact / load_artifact / log）。

如果你确实需要原始的 task payload（dict 形式），用 `ctx.raw_payload`。
"""


def _stream_key(step: str) -> str:
    return f"tasks:{step}"


def _consumer_group(step: str) -> str:
    return f"agents:{step}"


class Agent:
    def __init__(
        self,
        *,
        name: str,
        step: str,
        server: str | None = None,
        redis_url: str | None = None,
        concurrency: int = 1,
        block_ms: int = 5000,
        heartbeat_interval: float = 30.0,
        presence_interval: float = 5.0,
        health_host: str | None = None,
        health_port: int | None = None,
        configure_logging: bool = True,
    ) -> None:
        self.name = name
        self.step = step
        self.server = server or os.environ.get("AIJUICER_SERVER", "http://localhost:8000")
        # redis_url 优先级：构造参数 > 环境变量 > register 时由 scheduler 下发。
        # 不再硬编码 redis://localhost:6379/0 默认值——保证多机部署时 SDK 不会
        # 误连本机 redis。
        self.redis_url: str | None = redis_url or os.environ.get("AIJUICER_REDIS_URL")
        self.concurrency = concurrency
        self.block_ms = block_ms
        self.heartbeat_interval = heartbeat_interval
        # presence 心跳独立于 task 心跳，更频繁，用于"在线名册"维持
        self.presence_interval = presence_interval
        # health server bind 配置：默认 0.0.0.0 + 随机端口；上报给 scheduler 时
        # 把 0.0.0.0 替换为对外可达的本机 IP。可通过 AIJUICER_AGENT_PORT 固定端口。
        self.health_host = health_host or os.environ.get("AIJUICER_AGENT_HOST", "0.0.0.0")
        env_port = os.environ.get("AIJUICER_AGENT_PORT")
        self.health_port = (
            health_port if health_port is not None else (int(env_port) if env_port else 0)
        )
        self._handler: Handler | None = None
        self._consumer = f"{name}-{socket.gethostname()}-{os.getpid()}"
        self._shutdown = asyncio.Event()
        self._agent_id: str | None = None
        # 运行时填入：实际 listen 的 ip / port
        self._reported_host: str | None = None
        self._reported_port: int | None = None
        self._health_server: ThreadingHTTPServer | None = None
        self._health_thread: threading.Thread | None = None
        if configure_logging:
            configure_sdk_logging()
        self._log = structlog.get_logger("aijuicer_sdk.agent").bind(agent=name, step=step)

    def handler(self, fn: Handler) -> Handler:
        """装饰器：注册 step 任务的 handler。"""
        if self._handler is not None:
            raise RuntimeError("handler already registered")
        self._handler = fn
        return fn

    def run(self) -> None:
        """阻塞运行 agent 直至 SIGTERM/SIGINT。"""
        if self._handler is None:
            raise RuntimeError("no handler registered; decorate one with @agent.handler")
        asyncio.run(self.arun())

    async def arun(self) -> None:
        """async 入口：当你需要在自己的 asyncio 主循环里和别的协程并行跑时用它。

        async def main():
            producer = asyncio.create_task(periodic_idea_generator())
            try:
                await agent.arun()
            finally:
                producer.cancel()
        asyncio.run(main())
        """
        await self._arun()

    async def _arun(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self._shutdown.set)
            except NotImplementedError:
                # Windows / 某些环境不支持；依赖 KeyboardInterrupt 降级
                pass

        client = SchedulerClient(self.server)
        sem = asyncio.Semaphore(self.concurrency)
        inflight: set[asyncio.Task] = set()
        redis_client: redis_async.Redis | None = None

        presence_task: asyncio.Task | None = None
        try:
            self._start_health_server()
            # 1. register_agent 失败时退避重试，直到 scheduler 起来或收到 shutdown。
            reg = await self._register_with_backoff(client)
            if reg is None:
                return  # shutdown during registration
            self._agent_id = reg["id"]
            # 注册响应里若带 redis_url，且本地未显式配置，则使用服务端下发的——
            # 保证 SDK 与 scheduler 必然连同一个 redis。
            server_redis = reg.get("redis_url")
            local_configured = self.redis_url is not None
            effective_redis = self.redis_url or server_redis
            if not effective_redis:
                raise RuntimeError(
                    "no redis_url: scheduler did not return one and none was configured locally"
                )
            self.redis_url = effective_redis
            redis_client = redis_async.from_url(effective_redis, decode_responses=True)
            await self._log.ainfo(
                "Agent 注册成功",
                agent_id=self._agent_id,
                host=self._reported_host,
                port=self._reported_port,
                redis_source="local" if local_configured else "scheduler",
            )
            # consumer group 应由 scheduler 启动时建好；此处再保险一次
            await self._ensure_group(redis_client)
            # 在线名册由 Redis presence key 持有；SDK 周期性续期，scheduler 不主动探活。
            presence_task = asyncio.create_task(self._presence_heartbeat(client))

            # 2. 主消费循环：自愈 NOGROUP（Redis 重启 / 数据被清）+ 退避 Redis 断连
            redis_backoff = 1.0
            while not self._shutdown.is_set():
                try:
                    msgs = await redis_client.xreadgroup(
                        groupname=_consumer_group(self.step),
                        consumername=self._consumer,
                        streams={_stream_key(self.step): ">"},
                        count=self.concurrency,
                        block=self.block_ms,
                    )
                    redis_backoff = 1.0  # 成功一次就重置
                except RedisResponseError as e:
                    if "NOGROUP" in str(e):
                        await self._log.awarning(
                            "Redis 消费者组丢失，自动重建",
                            error=str(e),
                            action="recreate",
                        )
                        await self._ensure_group(redis_client)
                        continue
                    raise
                except RedisConnectionError as e:
                    # Redis 暂时断了；退避重试，最长 30s
                    await self._log.awarning(
                        "Redis 连接断开，退避后重试",
                        error=str(e),
                        retry_in_sec=redis_backoff,
                    )
                    try:
                        await asyncio.wait_for(self._shutdown.wait(), timeout=redis_backoff)
                    except TimeoutError:
                        pass
                    redis_backoff = min(redis_backoff * 2, 30.0)
                    continue
                if not msgs:
                    continue
                # msgs: [(stream, [(message_id, {"data": "..."}), ...])]
                for _stream, entries in msgs:
                    for message_id, fields in entries:
                        payload = json.loads(fields["data"])
                        await sem.acquire()
                        task = asyncio.create_task(
                            self._run_one(
                                client=client,
                                redis_client=redis_client,
                                message_id=message_id,
                                payload=payload,
                                sem=sem,
                            )
                        )
                        inflight.add(task)
                        task.add_done_callback(inflight.discard)

            await self._log.ainfo("Agent 准备关闭，等待在飞任务结束", inflight=len(inflight))
            if inflight:
                await asyncio.gather(*inflight, return_exceptions=True)
        finally:
            if presence_task is not None:
                presence_task.cancel()
                try:
                    await presence_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            self._stop_health_server()
            await client.close()
            if redis_client is not None:
                await redis_client.aclose()
            await self._log.ainfo("Agent 已停止")

    async def _register_with_backoff(self, client: SchedulerClient) -> dict | None:
        """注册失败（scheduler 没起 / 网络断 / 5xx）时退避重试，直到成功或 shutdown。

        指数退避：1s → 2s → 4s ... 上限 30s。
        返回注册响应；shutdown 期间退出则返回 None。
        """
        backoff = 1.0
        while not self._shutdown.is_set():
            try:
                return await client.register_agent(
                    name=self.name, step=self.step, metadata=self._agent_metadata()
                )
            except (httpx.HTTPError, httpx.RequestError) as e:
                await self._log.awarning(
                    "Agent 注册失败，退避后重试",
                    error=str(e),
                    retry_in_sec=backoff,
                )
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=backoff)
            except TimeoutError:
                pass
            backoff = min(backoff * 2, 30.0)
        return None

    def _start_health_server(self) -> None:
        server = ThreadingHTTPServer((self.health_host, self.health_port), _HealthHandler)
        actual_port = server.server_address[1]
        # 上报对外 IP：bind=0.0.0.0 时探测出网 IP，否则尊重用户配置
        self._reported_host = (
            _detect_local_ip() if self.health_host in ("0.0.0.0", "") else self.health_host
        )
        self._reported_port = int(actual_port)
        _HealthHandler.agent_payload = {
            "name": self.name,
            "step": self.step,
            "pid": os.getpid(),
        }
        thread = threading.Thread(target=server.serve_forever, daemon=True, name="agent-health")
        thread.start()
        self._health_server = server
        self._health_thread = thread

    def _stop_health_server(self) -> None:
        if self._health_server is not None:
            with contextlib.suppress(Exception):
                self._health_server.shutdown()
                self._health_server.server_close()
        if self._health_thread is not None:
            self._health_thread.join(timeout=2)

    def _agent_metadata(self) -> dict[str, Any]:
        return {
            "host": self._reported_host,
            "port": self._reported_port,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
        }

    async def _presence_heartbeat(self, client: SchedulerClient) -> None:
        """从注册成功一直到 shutdown，每 presence_interval 秒续一次 presence TTL。

        独立于"任务执行心跳"——任务心跳只在 handler 运行时上报；
        而 presence 心跳与任务无关，只表达"该 Agent 进程还活着"。

        失败时不会让协程退出：scheduler 重启 / 网络抖动期间持续吃异常，恢复后下一次
        心跳就让 Redis presence key 重新出现。为了避免日志刷屏，连续失败用退避，
        并仅在第一次失败和恢复时各打一行 warning/info。
        """
        if self._agent_id is None:
            return
        consecutive_failures = 0
        try:
            while not self._shutdown.is_set():
                try:
                    await client.agent_heartbeat(
                        agent_id=self._agent_id,
                        name=self.name,
                        step=self.step,
                        metadata=self._agent_metadata(),
                    )
                    if consecutive_failures > 0:
                        await self._log.ainfo(
                            "Agent presence 心跳恢复",
                            after_failures=consecutive_failures,
                        )
                    consecutive_failures = 0
                except Exception as e:  # noqa: BLE001
                    consecutive_failures += 1
                    if consecutive_failures == 1:
                        await self._log.awarning(
                            "Agent presence 心跳失败，将持续重试",
                            error=str(e),
                        )
                # 失败时退避：5s, 10s, 20s, max 30s；成功后恢复正常 presence_interval
                if consecutive_failures > 0:
                    delay = min(self.presence_interval * (2 ** (consecutive_failures - 1)), 30.0)
                else:
                    delay = self.presence_interval
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=delay)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            return

    async def _auto_heartbeat(
        self,
        *,
        client: SchedulerClient,
        task_id: str,
        request_id: str,
    ) -> None:
        """handler 执行期间每 heartbeat_interval 秒上报一次；被 cancel 即退出。"""
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                try:
                    await client.task_heartbeat(
                        task_id=task_id, message=None, request_id=request_id
                    )
                except Exception as e:  # noqa: BLE001
                    await self._log.awarning("任务心跳上报失败", task_id=task_id, error=str(e))
        except asyncio.CancelledError:
            return

    async def _ensure_group(self, redis_client: redis_async.Redis) -> None:
        try:
            await redis_client.xgroup_create(
                name=_stream_key(self.step),
                groupname=_consumer_group(self.step),
                id="$",
                mkstream=True,
            )
        except Exception as e:  # noqa: BLE001
            if "BUSYGROUP" not in str(e):
                raise

    async def _run_one(
        self,
        *,
        client: SchedulerClient,
        redis_client: redis_async.Redis,
        message_id: str,
        payload: dict[str, Any],
        sem: asyncio.Semaphore,
    ) -> None:
        task_id = payload["task_id"]
        request_id = payload.get("request_id", f"req_{uuid.uuid4().hex[:8]}")
        ctx = AgentContext.from_task_payload(payload, client=client)
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            workflow_id=payload["workflow_id"],
            step=self.step,
            task_id=task_id,
        )
        heartbeat_task: asyncio.Task | None = None
        try:
            start_resp = await client.task_start(
                task_id=task_id,
                agent_id=self._agent_id or self.name,
                request_id=request_id,
            )
            if not start_resp.get("started", True):
                # 重复 / 乱序投递（例如 startup recovery 重入队）；直接 XACK 丢弃。
                await self._log.ainfo("跳过重复投递的任务", task_id=task_id)
                return
            assert self._handler is not None
            heartbeat_task = asyncio.create_task(
                self._auto_heartbeat(client=client, task_id=task_id, request_id=request_id)
            )
            output = await self._handler(ctx)
            await client.task_complete(task_id=task_id, output=output or {}, request_id=request_id)
            await self._log.ainfo("任务完成", task_id=task_id)
        except FatalError as e:
            await self._log.aerror("任务致命错误", task_id=task_id, error=str(e))
            await client.task_fail(
                task_id=task_id,
                error=str(e),
                retryable=False,
                request_id=request_id,
            )
        except RetryableError as e:
            await self._log.awarning("任务可重试错误", task_id=task_id, error=str(e))
            await client.task_fail(
                task_id=task_id,
                error=str(e),
                retryable=True,
                request_id=request_id,
            )
        except Exception as e:  # noqa: BLE001 — spec § 5.2: 默认按 retryable 上报
            await self._log.aexception("任务未预期异常", task_id=task_id, error=str(e))
            await client.task_fail(
                task_id=task_id,
                error=f"{type(e).__name__}: {e}",
                retryable=True,
                request_id=request_id,
            )
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            try:
                await redis_client.xack(
                    _stream_key(self.step), _consumer_group(self.step), message_id
                )
            except Exception as e:  # noqa: BLE001
                await self._log.aerror("Redis XACK 失败", error=str(e))
            structlog.contextvars.clear_contextvars()
            sem.release()
