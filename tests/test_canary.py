import pytest

from src.orchestrator.canary import (
    CanaryAnalyzer,
    CanaryThresholds,
    WorkerCanaryMetrics,
)


def healthy_metrics(**overrides):
    values = {
        "http_healthy": True,
        "error_rate": 0.001,
        "queue_backlog": 5,
        "processing_latency_seconds": 1.5,
        "lease_renewal_failures": 0,
        "scheduler_queue_backlog": 7,
        "worker_throughput_per_minute": 120.0,
        "scheduler_dispatch_rate_per_minute": 115.0,
    }
    values.update(overrides)
    return WorkerCanaryMetrics(**values)


def test_canary_promotes_when_http_and_worker_metrics_are_within_thresholds():
    analyzer = CanaryAnalyzer(
        CanaryThresholds(
            max_error_rate=0.01,
            max_queue_backlog=25,
            max_processing_latency_seconds=5.0,
            max_scheduler_queue_backlog=25,
            min_worker_throughput_per_minute=50.0,
        )
    )

    decision = analyzer.evaluate(healthy_metrics())

    assert decision.promote is True
    assert decision.rollback is False
    assert decision.reasons == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"queue_backlog": 51}, "queue_backlog_exceeded"),
        ({"processing_latency_seconds": 10.1}, "processing_latency_exceeded"),
        ({"scheduler_queue_backlog": 76}, "scheduler_queue_backlog_exceeded"),
    ],
)
def test_canary_fails_promotion_when_backlog_or_latency_exceeds_thresholds(
    overrides,
    reason,
):
    analyzer = CanaryAnalyzer(
        CanaryThresholds(
            max_queue_backlog=50,
            max_processing_latency_seconds=10.0,
            max_scheduler_queue_backlog=75,
        )
    )

    decision = analyzer.evaluate(healthy_metrics(**overrides))

    assert decision.promote is False
    assert decision.rollback is True
    assert reason in decision.reasons


def test_worker_lease_renewal_failures_contribute_to_rollback_decision():
    analyzer = CanaryAnalyzer(CanaryThresholds(max_lease_renewal_failures=0))

    decision = analyzer.evaluate(healthy_metrics(lease_renewal_failures=1))

    assert decision.promote is False
    assert decision.rollback is True
    assert decision.reasons == ["lease_renewal_failures"]


def test_dashboard_metrics_show_scheduler_and_worker_health_together():
    decision = CanaryAnalyzer().evaluate(healthy_metrics())

    assert decision.dashboard_metrics["worker.queue_backlog"] == 5
    assert (
        decision.dashboard_metrics["worker.processing_latency_seconds"]
        == 1.5
    )
    assert decision.dashboard_metrics["worker.lease_renewal_failures"] == 0
    assert decision.dashboard_metrics["scheduler.queue_backlog"] == 7
    assert (
        decision.dashboard_metrics["scheduler.dispatch_rate_per_minute"]
        == 115.0
    )


def test_sample_batch_rolls_back_when_any_canary_sample_fails():
    analyzer = CanaryAnalyzer(CanaryThresholds(max_queue_backlog=50))

    decision = analyzer.evaluate_samples(
        [
            healthy_metrics(queue_backlog=5),
            healthy_metrics(queue_backlog=60),
        ]
    )

    assert decision.promote is False
    assert decision.rollback is True
    assert "queue_backlog_exceeded" in decision.reasons
    assert decision.dashboard_metrics["sample_0.worker.queue_backlog"] == 5
    assert decision.dashboard_metrics["sample_1.worker.queue_backlog"] == 60


def test_sample_batch_requires_at_least_one_metrics_sample():
    with pytest.raises(ValueError, match="at least one"):
        CanaryAnalyzer().evaluate_samples([])
