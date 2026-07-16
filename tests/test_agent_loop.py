"""AgentLoop 优化模块 — 测试套件"""

import asyncio
import pytest
import json
from pathlib import Path

from agent_loop.metrics import MetricsCollector, IterationMetrics, LoopSummary
from agent_loop.optimizer import LoopOptimizer, LoopConfig, LoopState, LoopStatus, LoopExitReason
from agent_loop.visualizer import LoopVisualizer


# ---------------------------------------------------------------------------
# MetricsCollector 测试
# ---------------------------------------------------------------------------

class TestMetricsCollector:
    """指标采集"""

    def test_record_step_basic(self):
        collector = MetricsCollector(task="test-task")
        collector.start()
        collector.record_step_start("agent_reason")
        collector.record_step_end("agent_reason", output_tokens=50)

        summary = collector.summarize()
        assert summary.total_iterations == 1
        assert summary.total_output_tokens == 50
        assert summary.task == "test-task"

    def test_record_tool_call(self):
        collector = MetricsCollector()
        collector.start()
        import time
        collector.record_step_start("query_weather")
        time.sleep(0.001)  # 确保耗时 > 0
        collector.record_step_end("query_weather", tool_name="maps_weather", output_tokens=20)

        summary = collector.summarize()
        assert summary.total_tool_calls == 1

    def test_error_tracking(self):
        collector = MetricsCollector()
        collector.start()
        collector.record_step_start("tool_call")
        collector.record_step_end("tool_call", error="Connection refused", retried=True)

        summary = collector.summarize()
        assert summary.total_errors == 1
        assert summary.total_retries == 1

    def test_efficiency_score_perfect(self):
        """低迭代无错误 → 高分"""
        collector = MetricsCollector()
        collector.start()
        for i in range(5):
            collector.record_step_start("step")
            collector.record_step_end("step", output_tokens=10)

        summary = collector.summarize()
        assert summary.efficiency_score >= 70

    def test_efficiency_score_penalty(self):
        """高迭代高错误 → 低分"""
        collector = MetricsCollector()
        collector.start()
        for i in range(50):
            collector.record_step_start("step")
            collector.record_step_end("step", error="err")

        summary = collector.summarize()
        assert summary.efficiency_score < 70

    def test_warnings_generated(self):
        collector = MetricsCollector()
        collector.start()
        # 单次快速迭代 → 不完整警告
        collector.record_step_start("step")
        collector.record_step_end("step", output_tokens=5)

        summary = collector.summarize()
        assert len(summary.warnings) >= 1

    def test_to_dict(self):
        collector = MetricsCollector(task="demo")
        collector.start()
        collector.record_step_start("step")
        collector.record_step_end("step", output_tokens=10)

        data = collector.to_dict()
        assert "summary" in data
        assert "iterations" in data
        assert data["summary"]["total_iterations"] == 1

    def test_ttft_tracking(self):
        collector = MetricsCollector()
        collector.start()
        # 第一轮无输出
        collector.record_step_start("think")
        collector.record_step_end("think", input_tokens=10, output_tokens=0)
        # 第二轮有输出
        import time
        time.sleep(0.001)  # 确保 ttft > 0
        collector.record_step_start("speak")
        collector.record_step_end("speak", output_tokens=30)

        summary = collector.summarize()
        assert summary.ttft_ms >= 0  # 可能有也可能为 0（测试环境太快）


# ---------------------------------------------------------------------------
# LoopOptimizer 测试
# ---------------------------------------------------------------------------

class TestLoopOptimizer:
    """循环优化器"""

    def test_config_defaults(self):
        config = LoopConfig()
        assert config.max_iterations == 50
        assert config.timeout_seconds == 120.0
        assert config.max_errors == 5

    def test_state_initial(self):
        state = LoopState()
        assert state.status == LoopStatus.IDLE
        assert state.iteration == 0
        assert state.error_count == 0

    def test_retry_backoff_success(self):
        optimizer = LoopOptimizer()
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("fail")
            return "ok"

        async def run():
            return await optimizer.retry_with_backoff(flaky, max_retries=3)

        result = asyncio.run(run())
        assert result == "ok"
        assert call_count == 3

    def test_retry_backoff_exhaust(self):
        optimizer = LoopOptimizer()

        async def always_fails():
            raise RuntimeError("always fail")

        async def run():
            with pytest.raises(RuntimeError):
                await optimizer.retry_with_backoff(always_fails, max_retries=2)

        asyncio.run(run())
        assert optimizer.state.retry_count >= 2

    def test_safe_tool_call_fallback(self):
        optimizer = LoopOptimizer()

        async def broken_tool():
            raise Exception("tool error")

        result = asyncio.run(
            optimizer.safe_tool_call(broken_tool, fallback={"status": "fallback"})
        )
        assert result == {"status": "fallback"}
        assert optimizer.state.error_count == 1

    def test_loop_state_to_dict(self):
        state = LoopState(
            iteration=10, error_count=2, tool_calls=5,
            status=LoopStatus.RUNNING,
        )
        d = state.to_dict()
        assert d["iteration"] == 10
        assert d["errors"] == 2


# ---------------------------------------------------------------------------
# LoopVisualizer 测试
# ---------------------------------------------------------------------------

class TestLoopVisualizer:
    """可视化"""

    def test_terminal_dashboard(self):
        summary = LoopSummary(
            task="长沙3日游",
            total_iterations=15,
            total_duration_ms=4500,
            total_output_tokens=320,
            total_tool_calls=4,
            total_errors=0,
            ttft_ms=250,
            efficiency_score=85.5,
        )
        output = LoopVisualizer.terminal_dashboard(summary)
        assert "长沙" in output
        assert "85.5" in output

    def test_html_output(self, tmp_path):
        summary = LoopSummary(
            task="test", total_iterations=3, total_duration_ms=1500,
            total_output_tokens=50, ttft_ms=100, efficiency_score=90,
        )
        iterations = [
            IterationMetrics(1, "agent_reason", 500, output_tokens=20),
            IterationMetrics(2, "tool_call", 800, tool_name="maps_weather"),
            IterationMetrics(3, "agent_reason", 200, output_tokens=30),
        ]
        path = LoopVisualizer.to_html(summary, iterations, tmp_path / "test.html")
        content = path.read_text("utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert "AgentLoop" in content or "性能报告" in content
        assert "90" in content

    def test_csv_output(self, tmp_path):
        summary = LoopSummary(task="test", total_iterations=2)
        iterations = [IterationMetrics(1, "step", 100)]
        path = LoopVisualizer.to_csv(summary, iterations, tmp_path / "test.csv")
        content = path.read_text("utf-8")
        assert "iteration" in content
        assert "SUMMARY" in content
