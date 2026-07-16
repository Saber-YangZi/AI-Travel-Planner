"""AgentLoop 性能指标采集模块。

采集维度：
  - 每轮迭代耗时 (TTI: Time-To-Iteration)
  - Token 消耗 (input/output/total)
  - 工具调用次数与耗时
  - 错误率与重试次数
  - 首 Token 延迟 (TTFT: Time-To-First-Token)
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IterationMetrics:
    """单次迭代指标"""
    iteration: int
    step_name: str                         # agent_reason | tool_call | tool_result
    duration_ms: float                     # 耗时
    input_tokens: int = 0
    output_tokens: int = 0
    tool_name: str = ""
    tool_duration_ms: float = 0.0
    error: str = ""
    retry_count: int = 0

    def to_dict(self) -> dict:
        return {
            "iteration": self.iteration,
            "step": self.step_name,
            "duration_ms": round(self.duration_ms, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_name": self.tool_name,
            "tool_duration_ms": round(self.tool_duration_ms, 2) if self.tool_duration_ms else 0,
            "error": self.error,
            "retry": self.retry_count,
        }


@dataclass
class LoopSummary:
    """完整循环统计汇总"""
    task: str = ""
    total_iterations: int = 0
    total_duration_ms: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0
    total_tool_duration_ms: float = 0.0
    total_errors: int = 0
    total_retries: int = 0
    ttft_ms: float = 0.0                 # 首 Token 延迟
    avg_iteration_ms: float = 0.0
    efficiency_score: float = 0.0        # 效率评分 (0-100)
    warnings: list[str] = field(default_factory=list)

    @property
    def tokens_per_second(self) -> float:
        if self.total_duration_ms > 0:
            return self.total_output_tokens / (self.total_duration_ms / 1000)
        return 0.0

    @property
    def tool_efficiency(self) -> float:
        """工具调用效率 = 工具耗时 / 总耗时"""
        if self.total_duration_ms > 0:
            return self.total_tool_duration_ms / self.total_duration_ms
        return 0.0

    def to_dict(self) -> dict:
        return {
            "task": self.task,
            "total_iterations": self.total_iterations,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tool_calls": self.total_tool_calls,
            "total_tool_duration_ms": round(self.total_tool_duration_ms, 2),
            "total_errors": self.total_errors,
            "total_retries": self.total_retries,
            "ttft_ms": round(self.ttft_ms, 2),
            "avg_iteration_ms": round(self.avg_iteration_ms, 2),
            "tokens_per_second": round(self.tokens_per_second, 2),
            "tool_efficiency_ratio": round(self.tool_efficiency, 3),
            "efficiency_score": round(self.efficiency_score, 1),
            "warnings": self.warnings,
        }


class MetricsCollector:
    """Agent 循环性能指标采集器"""

    def __init__(self, task: str = ""):
        self._iterations: list[IterationMetrics] = []
        self._task = task
        self._start_time: float = 0.0
        self._first_token_time: float | None = None
        self._step_timers: dict[str, float] = {}
        self._iter_count: int = 0
        self._tool_call_count: int = 0
        self._tool_total_ms: float = 0.0
        self._error_count: int = 0
        self._retry_count: int = 0

    # ------------------------------------------------------------------
    # 采集接口
    # ------------------------------------------------------------------

    def start(self):
        """标记循环开始"""
        self._start_time = time.monotonic()

    def record_step_start(self, step_name: str):
        """记录步骤开始"""
        self._step_timers[step_name] = time.monotonic()

    def record_step_end(
        self,
        step_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_name: str = "",
        error: str = "",
        retried: bool = False,
    ):
        """记录步骤结束，自动计算耗时"""
        now = time.monotonic()
        start = self._step_timers.pop(step_name, now)
        duration = (now - start) * 1000

        self._iter_count += 1

        # 首 Token
        if self._first_token_time is None and output_tokens > 0:
            self._first_token_time = now

        if tool_name:
            self._tool_call_count += 1
            self._tool_total_ms += duration

        if error:
            self._error_count += 1
        if retried:
            self._retry_count += 1

        self._iterations.append(IterationMetrics(
            iteration=self._iter_count,
            step_name=step_name,
            duration_ms=duration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_name=tool_name,
            tool_duration_ms=duration if tool_name else 0.0,
            error=error,
            retry_count=1 if retried else 0,
        ))

    # ------------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------------

    def summarize(self) -> LoopSummary:
        """生成汇总报告"""
        total_ms = (time.monotonic() - self._start_time) * 1000
        total_input = sum(it.input_tokens for it in self._iterations)
        total_output = sum(it.output_tokens for it in self._iterations)

        avg_iter = total_ms / max(self._iter_count, 1)

        # 效率评分
        score = self._compute_efficiency_score(
            total_ms, self._iter_count, self._error_count
        )

        # 告警生成
        warnings = self._generate_warnings(
            avg_iter, self._iter_count, self._error_count
        )

        ttft = (self._first_token_time - self._start_time) * 1000 if self._first_token_time else 0.0

        return LoopSummary(
            task=self._task,
            total_iterations=self._iter_count,
            total_duration_ms=total_ms,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_tool_calls=self._tool_call_count,
            total_tool_duration_ms=self._tool_total_ms,
            total_errors=self._error_count,
            total_retries=self._retry_count,
            ttft_ms=ttft,
            avg_iteration_ms=avg_iter,
            efficiency_score=score,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _compute_efficiency_score(
        self, total_ms: float, iterations: int, errors: int
    ) -> float:
        """计算综合效率评分 (0-100)"""
        score = 100.0

        # 迭代过多扣分
        if iterations > 20:
            score -= min((iterations - 20) * 2, 30)

        # 错误扣分
        score -= min(errors * 10, 40)

        # 耗时过长扣分
        if total_ms > 60_000:  # 超过 60 秒
            score -= min((total_ms - 60_000) / 2000, 20)

        # 过短（可能未完成）
        if total_ms < 500 and iterations < 3:
            score -= 10

        return max(score, 0.0)

    def _generate_warnings(
        self, avg_iter_ms: float, iterations: int, errors: int
    ) -> list[str]:
        """生成优化建议"""
        warnings = []

        if iterations > 30:
            warnings.append("循环迭代次数过多 (>30)，建议添加缓存减少重复调用")
        if avg_iter_ms > 5000:
            warnings.append(f"平均每轮耗时 {avg_iter_ms:.0f}ms (>5s)，建议启用并行调用")
        if errors > 0:
            warnings.append(f"检测到 {errors} 次错误，建议增加重试机制")
        if iterations == 1 and avg_iter_ms < 200:
            warnings.append("仅 1 轮迭代，可能未完成完整规划流程")

        return warnings

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "summary": self.summarize().to_dict(),
            "iterations": [it.to_dict() for it in self._iterations],
        }
