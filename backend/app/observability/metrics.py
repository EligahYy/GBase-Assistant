"""内存级指标收集器。

设计取舍：
- 不引入 prometheus_client，避免新依赖。后续如需暴露 /metrics 端点，可在 ``render_prometheus`` 中拼接文本格式。
- 仅在进程内统计，重启清零；适合 Demo / 单机部署阶段。
- 线程/协程安全：使用 ``threading.Lock`` 保护字典写入。

埋点接入点（Phase 3.5.4）：
- LLM 调用：``metrics.record_llm_call`` —— ``backend/app/llm/client.py``
- SQL 沙箱：``metrics.record_sql_execution`` —— ``backend/app/sql/sandbox.py``
- 向量检索：``metrics.record_vector_retrieval`` —— ``backend/app/dependencies.py``
- 依赖健康：``metrics.set_dependency_up`` —— ``backend/app/api/health.py``
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class _Histogram:
    """简易直方图：保留 count / sum / 桶计数。"""

    buckets: tuple[float, ...]
    counts: list[int] = field(default_factory=list)
    total_count: int = 0
    total_sum: float = 0.0

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = [0] * (len(self.buckets) + 1)

    def observe(self, value: float) -> None:
        self.total_count += 1
        self.total_sum += value
        for i, upper in enumerate(self.buckets):
            if value <= upper:
                self.counts[i] += 1
                return
        self.counts[-1] += 1


# 默认延迟桶（秒）：覆盖 LLM/SQL/Embedding 常见区间
_DEFAULT_LATENCY_BUCKETS: tuple[float, ...] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)


class MetricsRegistry:
    """进程内指标注册表。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Counter: 向量检索命中/未命中（按 retriever 分组）
        self._vector_hit_total: dict[str, int] = defaultdict(int)
        self._vector_miss_total: dict[str, int] = defaultdict(int)

        # Counter & Histogram: SQL 沙箱执行
        self._sql_exec_total: dict[str, int] = defaultdict(int)  # status -> count
        self._sql_exec_latency: _Histogram = _Histogram(_DEFAULT_LATENCY_BUCKETS)

        # Counter & Histogram: LLM 调用
        self._llm_call_total: dict[tuple[str, str, str], int] = defaultdict(int)
        # key = (task_type, model, status)
        self._llm_tokens_total: dict[tuple[str, str, str], int] = defaultdict(int)
        # key = (task_type, model, kind)  kind ∈ {prompt, completion, total}
        self._llm_latency: _Histogram = _Histogram(_DEFAULT_LATENCY_BUCKETS)

        # Gauge: 依赖健康（1=up, 0=down, 0.5=degraded）
        self._dependency_up: dict[str, float] = {}

    # ── 向量检索 ────────────────────────────────────────────────────────────
    def record_vector_retrieval(self, retriever: str, hit: bool) -> None:
        with self._lock:
            if hit:
                self._vector_hit_total[retriever] += 1
            else:
                self._vector_miss_total[retriever] += 1

    # ── SQL 沙箱 ───────────────────────────────────────────────────────────
    def record_sql_execution(self, status: str, latency_seconds: float) -> None:
        with self._lock:
            self._sql_exec_total[status] += 1
            self._sql_exec_latency.observe(latency_seconds)

    @contextmanager
    def time_sql_execution(self) -> Iterator[dict]:
        """上下文管理器：自动测量 SQL 执行耗时。

        用法::

            with metrics.time_sql_execution() as ctx:
                ...
                ctx["status"] = "ok"
        """
        ctx: dict = {"status": "error"}
        start = time.perf_counter()
        try:
            yield ctx
        finally:
            elapsed = time.perf_counter() - start
            self.record_sql_execution(ctx.get("status", "error"), elapsed)

    # ── LLM 调用 ───────────────────────────────────────────────────────────
    def record_llm_call(
        self,
        *,
        task_type: str,
        model: str,
        status: str,
        latency_seconds: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        with self._lock:
            self._llm_call_total[(task_type, model, status)] += 1
            self._llm_latency.observe(latency_seconds)
            if prompt_tokens:
                self._llm_tokens_total[(task_type, model, "prompt")] += prompt_tokens
            if completion_tokens:
                self._llm_tokens_total[(task_type, model, "completion")] += completion_tokens
            if prompt_tokens or completion_tokens:
                self._llm_tokens_total[(task_type, model, "total")] += prompt_tokens + completion_tokens

    # ── 依赖健康 ────────────────────────────────────────────────────────────
    def set_dependency_up(self, name: str, value: float) -> None:
        with self._lock:
            self._dependency_up[name] = value

    # ── 快照 ───────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        """返回当前所有指标的浅拷贝，供调试与未来 /metrics 端点使用。"""
        with self._lock:
            return {
                "vector_retrieval_hit_total": dict(self._vector_hit_total),
                "vector_retrieval_miss_total": dict(self._vector_miss_total),
                "sql_execution_total": dict(self._sql_exec_total),
                "sql_execution_latency": {
                    "count": self._sql_exec_latency.total_count,
                    "sum": self._sql_exec_latency.total_sum,
                    "buckets": list(
                        zip(
                            self._sql_exec_latency.buckets + (float("inf"),),
                            self._sql_exec_latency.counts,
                            strict=True,
                        )
                    ),
                },
                "llm_call_total": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in self._llm_call_total.items()},
                "llm_tokens_total": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in self._llm_tokens_total.items()},
                "llm_latency": {
                    "count": self._llm_latency.total_count,
                    "sum": self._llm_latency.total_sum,
                },
                "dependency_up": dict(self._dependency_up),
            }

    def reset(self) -> None:
        """测试用：清空所有指标。"""
        with self._lock:
            self._vector_hit_total.clear()
            self._vector_miss_total.clear()
            self._sql_exec_total.clear()
            self._sql_exec_latency = _Histogram(_DEFAULT_LATENCY_BUCKETS)
            self._llm_call_total.clear()
            self._llm_tokens_total.clear()
            self._llm_latency = _Histogram(_DEFAULT_LATENCY_BUCKETS)
            self._dependency_up.clear()


metrics = MetricsRegistry()
