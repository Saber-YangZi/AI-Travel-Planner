"""
日志系统 — 结构化日志 + 运行时监控

功能：
  - JSON 结构化日志输出
  - 多级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
  - 自动轮转（按天/按大小）
  - 控制台 + 文件双通道
  - 运行时性能监控仪表板
"""

import logging
import logging.handlers
import sys
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

LOG_DIR = Path("logs")
LOG_FORMAT_JSON = False  # True = JSON 格式; False = 可读文本


def setup_logger(
    name: str = "travel_agent",
    level: int = logging.INFO,
    log_dir: str | Path = "logs",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """初始化结构化日志系统。

    双通道输出:
      - 控制台:   INFO  级别以上
      - 文件:     DEBUG 级别以上（按大小轮转）
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 避免重复添加
    if logger.handlers:
        return logger

    # ---- 控制台 Handler ----
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)

    # ---- 文件 Handler (轮转) ----
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / f"{name}.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | "
        "%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


# ---- 全局默认 logger ----
_default_logger = setup_logger()


def get_logger(name: str | None = None) -> logging.Logger:
    """获取 logger 实例"""
    if name:
        return logging.getLogger(f"travel_agent.{name}")
    return _default_logger


# ---------------------------------------------------------------------------
# 运行时监控
# ---------------------------------------------------------------------------

@dataclass
class SystemSnapshot:
    """运行时系统快照"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    active_loops: int = 0
    total_requests: int = 0
    errors_last_minute: int = 0
    avg_loop_duration_ms: float = 0.0
    cache_hit_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "active_loops": self.active_loops,
            "total_requests": self.total_requests,
            "errors_last_minute": self.errors_last_minute,
            "avg_loop_duration_ms": round(self.avg_loop_duration_ms, 1),
            "cache_hit_rate": round(self.cache_hit_rate, 3),
        }


class RuntimeMonitor:
    """运行时指标监控器（线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._total_requests: int = 0
        self._active_loops: int = 0
        self._errors: list[float] = []   # 错误时间戳
        self._loop_durations: list[float] = []  # 循环耗时
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._logger = get_logger("monitor")

    # -------------------- 指标更新 --------------------

    def on_request_start(self):
        with self._lock:
            self._total_requests += 1
            self._active_loops += 1
        self._logger.info(f"请求开始 (活跃循环: {self._active_loops})")

    def on_request_end(self, duration_ms: float, error: bool = False):
        with self._lock:
            self._active_loops = max(0, self._active_loops - 1)
            self._loop_durations.append(duration_ms)
            if error:
                self._errors.append(time.time())
        self._logger.info(
            f"请求完成 | 耗时: {duration_ms:.0f}ms | "
            f"错误: {error} | 活跃: {self._active_loops}"
        )

    def on_cache_hit(self):
        with self._lock:
            self._cache_hits += 1

    def on_cache_miss(self):
        with self._lock:
            self._cache_misses += 1

    def on_error(self, error_msg: str):
        self._logger.error(f"运行时错误: {error_msg}")
        with self._lock:
            self._errors.append(time.time())

    # -------------------- 快照 --------------------

    def snapshot(self) -> SystemSnapshot:
        now = time.time()
        with self._lock:
            errors_last_min = sum(1 for t in self._errors if now - t <= 60)
            durations = self._loop_durations[-20:]  # 最近 20 次
            avg_dur = sum(durations) / len(durations) if durations else 0.0
            total = self._cache_hits + self._cache_misses
            hit_rate = self._cache_hits / total if total > 0 else 0.0

            return SystemSnapshot(
                active_loops=self._active_loops,
                total_requests=self._total_requests,
                errors_last_minute=errors_last_min,
                avg_loop_duration_ms=avg_dur,
                cache_hit_rate=hit_rate,
            )

    def dump(self) -> dict:
        """导出完整监控数据"""
        snap = self.snapshot()
        return snap.to_dict()


# ---- 全局单例 ----
_monitor = RuntimeMonitor()


def get_monitor() -> RuntimeMonitor:
    return _monitor
