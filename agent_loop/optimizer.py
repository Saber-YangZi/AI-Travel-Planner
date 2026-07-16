"""AgentLoop 优化器 — 可配置的循环控制与异常恢复。

作用：
  - 设定最大迭代次数（防止死循环）
  - 设定超时阈值（防止单个任务卡死）
  - 设定最大错误次数（达到上限优雅终止）
  - 重试策略（指数退避 + 最大重试）
  - 降级策略（工具调用失败时返回兜底数据）

用法:
  optimizer = LoopOptimizer(max_iterations=50, timeout_ms=120_000)
  async with optimizer.run(planner, user_input) as loop:
      async for event in loop:
          ...
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any


class LoopStatus(str, Enum):
    """循环运行状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"


class LoopExitReason(str, Enum):
    """循环退出原因"""
    NATURAL = "natural"           # 正常完成
    MAX_ITERATIONS = "max_iterations"  # 达到迭代上限
    TIMEOUT = "timeout"           # 超时
    MAX_ERRORS = "max_errors"     # 错误过多
    CANCELLED = "cancelled"       # 被取消
    FATAL_ERROR = "fatal_error"   # 致命错误


@dataclass
class LoopState:
    """循环实时状态"""
    iteration: int = 0
    elapsed_ms: float = 0
    status: LoopStatus = LoopStatus.IDLE
    exit_reason: LoopExitReason | None = None
    error_count: int = 0
    retry_count: int = 0
    tool_calls: int = 0
    last_error: str = ""

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "status": self.status.value,
            "exit_reason": self.exit_reason.value if self.exit_reason else None,
            "errors": self.error_count,
            "retries": self.retry_count,
            "tool_calls": self.tool_calls,
            "last_error": self.last_error,
        }


@dataclass
class LoopConfig:
    """循环配置"""
    max_iterations: int = 50           # 最大迭代次数
    timeout_seconds: float = 120.0     # 超时（秒）
    max_errors: int = 5                # 最大容许错误数
    retry_max: int = 3                 # 单次操作最大重试
    retry_base_delay: float = 1.0      # 重试基础延迟（秒）
    retry_backoff: float = 2.0         # 重试退避因子
    graceful_timeout: float = 5.0      # 优雅终止等待时间（秒）


class LoopOptimizer:
    """Agent 循环优化器"""

    def __init__(self, config: LoopConfig | None = None):
        self.config = config or LoopConfig()
        self.state = LoopState()

    # ------------------------------------------------------------------
    # 核心运行接口
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def run(
        self,
        planner,             # TripPlanner 实例
        user_input: str,
    ) -> AsyncIterator[AsyncIterator[tuple[str, Any]]]:
        """带保护机制的循环执行上下文"""
        self.state = LoopState(status=LoopStatus.RUNNING)
        start_time = time.monotonic()
        task: asyncio.Task | None = None

        async def _wrapped_stream():
            nonlocal task
            try:
                async for chunk in planner.stream(user_input):
                    self.state.iteration += 1
                    self.state.elapsed_ms = (time.monotonic() - start_time) * 1000

                    # 检查迭代上限
                    if self.state.iteration > self.config.max_iterations:
                        self.state.exit_reason = LoopExitReason.MAX_ITERATIONS
                        self.state.status = LoopStatus.COMPLETED
                        yield ("warning", f"达到最大迭代次数 ({self.config.max_iterations})，已终止")
                        return

                    # 检查错误上限
                    if self.state.error_count >= self.config.max_errors:
                        self.state.exit_reason = LoopExitReason.MAX_ERRORS
                        self.state.status = LoopStatus.ERROR
                        yield ("error", f"错误次数过多 ({self.state.error_count})，已终止")
                        return

                    yield ("data", chunk)

                self.state.status = LoopStatus.COMPLETED
                self.state.exit_reason = LoopExitReason.NATURAL

            except asyncio.CancelledError:
                self.state.status = LoopStatus.CANCELLED
                self.state.exit_reason = LoopExitReason.CANCELLED
            except Exception as e:
                self.state.status = LoopStatus.ERROR
                self.state.exit_reason = LoopExitReason.FATAL_ERROR
                self.state.last_error = str(e)
                yield ("error", str(e))

        try:
            task = asyncio.ensure_future(_wrapped_stream())

            # 超时保护
            async def _timeout_guard():
                deadline = start_time + self.config.timeout_seconds
                while time.monotonic() < deadline and self.state.status == LoopStatus.RUNNING:
                    await asyncio.sleep(0.5)
                if self.state.status == LoopStatus.RUNNING:
                    self.state.status = LoopStatus.TIMEOUT
                    self.state.exit_reason = LoopExitReason.TIMEOUT
                    task.cancel()

            timeout_task = asyncio.ensure_future(_timeout_guard())

            yield task

            # 等待任务完成
            try:
                await task
            except asyncio.CancelledError:
                pass

            timeout_task.cancel()

        finally:
            self.state.elapsed_ms = (time.monotonic() - start_time) * 1000

    # ------------------------------------------------------------------
    # 重试机制
    # ------------------------------------------------------------------

    async def retry_with_backoff(
        self,
        coro_factory,        # Callable[[], Awaitable]
        max_retries: int | None = None,
        on_retry: callable | None = None,
    ) -> Any:
        """指数退避重试"""
        max_retries = max_retries or self.config.retry_max
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                return await coro_factory()
            except Exception as e:
                last_error = e
                self.state.retry_count += 1

                if attempt < max_retries:
                    delay = self.config.retry_base_delay * (self.config.retry_backoff ** attempt)
                    if on_retry:
                        on_retry(attempt + 1, delay, e)
                    await asyncio.sleep(delay)
                else:
                    self.state.error_count += 1
                    self.state.last_error = str(e)
                    raise

        raise last_error  # type: ignore

    # ------------------------------------------------------------------
    # 工具调用降级
    # ------------------------------------------------------------------

    async def safe_tool_call(
        self,
        tool_func,
        *args,
        fallback: Any = None,
        **kwargs,
    ) -> Any:
        """安全的工具调用：失败时返回降级数据"""
        try:
            self.state.tool_calls += 1
            result = await tool_func(*args, **kwargs)
            return result
        except Exception as e:
            self.state.error_count += 1
            self.state.last_error = str(e)
            return fallback

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self.state.status == LoopStatus.RUNNING

    @property
    def should_stop(self) -> bool:
        return self.state.status in (
            LoopStatus.CANCELLED,
            LoopStatus.ERROR,
            LoopStatus.TIMEOUT,
        )
