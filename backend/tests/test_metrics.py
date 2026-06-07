"""Observability metrics 模块测试。"""

from __future__ import annotations

import pytest

from app.observability.metrics import MetricsRegistry, metrics


@pytest.fixture(autouse=True)
def _reset_global_metrics():
    metrics.reset()
    yield
    metrics.reset()


class TestVectorRetrievalCounters:
    def test_hit_and_miss_counters_increment_independently(self):
        reg = MetricsRegistry()
        reg.record_vector_retrieval("SchemaRetriever", hit=True)
        reg.record_vector_retrieval("SchemaRetriever", hit=True)
        reg.record_vector_retrieval("SchemaRetriever", hit=False)
        reg.record_vector_retrieval("KnowledgeRetriever", hit=False)

        snap = reg.snapshot()
        assert snap["vector_retrieval_hit_total"] == {"SchemaRetriever": 2}
        assert snap["vector_retrieval_miss_total"] == {
            "SchemaRetriever": 1,
            "KnowledgeRetriever": 1,
        }


class TestSQLExecutionMetrics:
    def test_status_counter_and_latency_histogram(self):
        reg = MetricsRegistry()
        reg.record_sql_execution("ok", 0.04)
        reg.record_sql_execution("ok", 0.3)
        reg.record_sql_execution("blocked", 0.0)
        reg.record_sql_execution("timeout", 35.0)

        snap = reg.snapshot()
        assert snap["sql_execution_total"] == {"ok": 2, "blocked": 1, "timeout": 1}
        latency = snap["sql_execution_latency"]
        assert latency["count"] == 4
        assert latency["sum"] == pytest.approx(0.04 + 0.3 + 0.0 + 35.0)

    def test_time_sql_execution_context_manager(self):
        reg = MetricsRegistry()
        with reg.time_sql_execution() as ctx:
            ctx["status"] = "ok"

        snap = reg.snapshot()
        assert snap["sql_execution_total"] == {"ok": 1}
        assert snap["sql_execution_latency"]["count"] == 1

    def test_time_sql_execution_defaults_to_error_on_exception(self):
        reg = MetricsRegistry()
        with pytest.raises(RuntimeError), reg.time_sql_execution():
            raise RuntimeError("boom")

        snap = reg.snapshot()
        assert snap["sql_execution_total"] == {"error": 1}


class TestLLMMetrics:
    def test_call_count_and_token_breakdown(self):
        reg = MetricsRegistry()
        reg.record_llm_call(
            task_type="sql_generation",
            model="deepseek/deepseek-chat",
            status="ok",
            latency_seconds=1.2,
            prompt_tokens=300,
            completion_tokens=80,
        )
        reg.record_llm_call(
            task_type="sql_generation",
            model="deepseek/deepseek-chat",
            status="error",
            latency_seconds=0.05,
        )

        snap = reg.snapshot()
        assert snap["llm_call_total"]["sql_generation|deepseek/deepseek-chat|ok"] == 1
        assert snap["llm_call_total"]["sql_generation|deepseek/deepseek-chat|error"] == 1
        tokens = snap["llm_tokens_total"]
        assert tokens["sql_generation|deepseek/deepseek-chat|prompt"] == 300
        assert tokens["sql_generation|deepseek/deepseek-chat|completion"] == 80
        assert tokens["sql_generation|deepseek/deepseek-chat|total"] == 380


class TestDependencyGauge:
    def test_set_and_overwrite_gauge(self):
        reg = MetricsRegistry()
        reg.set_dependency_up("database", 1.0)
        reg.set_dependency_up("vector_db", 0.5)
        reg.set_dependency_up("database", 0.0)

        snap = reg.snapshot()
        assert snap["dependency_up"] == {"database": 0.0, "vector_db": 0.5}


class TestSnapshotShape:
    def test_snapshot_has_all_expected_keys(self):
        snap = metrics.snapshot()
        for key in [
            "vector_retrieval_hit_total",
            "vector_retrieval_miss_total",
            "sql_execution_total",
            "sql_execution_latency",
            "llm_call_total",
            "llm_tokens_total",
            "llm_latency",
            "dependency_up",
        ]:
            assert key in snap
