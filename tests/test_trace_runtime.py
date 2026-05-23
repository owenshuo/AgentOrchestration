import pytest

from src.agent.trace_runtime import (
    TraceAggregationRuntime,
    TraceMemoryLimitExceeded,
)


class TestTraceAggregationRuntime:
    def test_aggregate_records_completed_terminal_outcome(self):
        runtime = TraceAggregationRuntime(max_bytes=512)

        outcome = runtime.aggregate(
            "run-1",
            [{"span": "start"}, {"span": "finish", "duration_ms": 12}],
        )

        assert outcome["status"] == "completed"
        assert outcome["event_count"] == 2
        assert outcome["bytes_used"] > 0
        assert runtime.get_outcome("run-1")["status"] == "completed"

    def test_memory_limit_records_single_rejected_outcome_before_retry(self):
        runtime = TraceAggregationRuntime(max_bytes=40)

        with pytest.raises(TraceMemoryLimitExceeded):
            runtime.aggregate(
                "run-2",
                [{"span": "small"}, {"payload": "x" * 200}],
            )

        first_outcome = runtime.get_outcome("run-2")
        with pytest.raises(TraceMemoryLimitExceeded):
            runtime.aggregate("run-2", [{"span": "retry"}])

        retry_outcome = runtime.get_outcome("run-2")
        assert first_outcome == retry_outcome
        assert retry_outcome["status"] == "rejected"
        assert retry_outcome["event_count"] == 1
        assert retry_outcome["bytes_used"] <= runtime.max_bytes

    def test_cancelled_run_rejects_later_aggregation_without_new_state(self):
        runtime = TraceAggregationRuntime(max_bytes=512)

        cancelled = runtime.cancel("run-3", reason="worker cancelled")

        with pytest.raises(TraceMemoryLimitExceeded, match="worker cancelled"):
            runtime.aggregate("run-3", [{"span": "late"}])

        assert runtime.get_outcome("run-3") == cancelled
