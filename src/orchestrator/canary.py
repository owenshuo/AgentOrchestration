"""Canary rollout decisions for scheduler and worker health."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping


@dataclass(frozen=True)
class WorkerCanaryMetrics:
    """Metrics collected for a canary worker version."""

    http_healthy: bool
    error_rate: float
    queue_backlog: int
    processing_latency_seconds: float
    lease_renewal_failures: int = 0
    scheduler_queue_backlog: int = 0
    worker_throughput_per_minute: float = 0.0
    scheduler_dispatch_rate_per_minute: float = 0.0


@dataclass(frozen=True)
class CanaryThresholds:
    """Rollback thresholds for worker canary promotion."""

    max_error_rate: float = 0.01
    max_queue_backlog: int = 100
    max_processing_latency_seconds: float = 30.0
    max_lease_renewal_failures: int = 0
    max_scheduler_queue_backlog: int = 100
    min_worker_throughput_per_minute: float = 0.0


@dataclass(frozen=True)
class CanaryDecision:
    promote: bool
    rollback: bool
    reasons: List[str] = field(default_factory=list)
    dashboard_metrics: Dict[str, float | int | bool] = field(
        default_factory=dict
    )


class CanaryAnalyzer:
    """Evaluate whether a worker canary should promote or roll back."""

    def __init__(self, thresholds: CanaryThresholds | None = None):
        self.thresholds = thresholds or CanaryThresholds()

    def evaluate(self, metrics: WorkerCanaryMetrics) -> CanaryDecision:
        reasons = self._rejection_reasons(metrics)
        rollback = bool(reasons)
        return CanaryDecision(
            promote=not rollback,
            rollback=rollback,
            reasons=reasons,
            dashboard_metrics=self.dashboard_metrics(metrics),
        )

    def evaluate_samples(
        self,
        samples: Iterable[WorkerCanaryMetrics],
    ) -> CanaryDecision:
        decisions = [self.evaluate(sample) for sample in samples]
        if not decisions:
            raise ValueError("at least one canary metrics sample is required")

        reasons: List[str] = []
        dashboard: Dict[str, float | int | bool] = {}
        for index, decision in enumerate(decisions):
            dashboard.update(
                {
                    f"sample_{index}.{key}": value
                    for key, value in decision.dashboard_metrics.items()
                }
            )
            reasons.extend(decision.reasons)

        rollback = any(decision.rollback for decision in decisions)
        return CanaryDecision(
            promote=not rollback,
            rollback=rollback,
            reasons=reasons,
            dashboard_metrics=dashboard,
        )

    def dashboard_metrics(
        self,
        metrics: WorkerCanaryMetrics,
    ) -> Dict[str, float | int | bool]:
        return {
            "worker.http_healthy": metrics.http_healthy,
            "worker.error_rate": metrics.error_rate,
            "worker.queue_backlog": metrics.queue_backlog,
            "worker.processing_latency_seconds": (
                metrics.processing_latency_seconds
            ),
            "worker.lease_renewal_failures": metrics.lease_renewal_failures,
            "worker.throughput_per_minute": (
                metrics.worker_throughput_per_minute
            ),
            "scheduler.queue_backlog": metrics.scheduler_queue_backlog,
            "scheduler.dispatch_rate_per_minute": (
                metrics.scheduler_dispatch_rate_per_minute
            ),
        }

    def _rejection_reasons(self, metrics: WorkerCanaryMetrics) -> List[str]:
        thresholds = self.thresholds
        checks: Mapping[str, bool] = {
            "http_health_failed": not metrics.http_healthy,
            "error_rate_exceeded": (
                metrics.error_rate > thresholds.max_error_rate
            ),
            "queue_backlog_exceeded": (
                metrics.queue_backlog > thresholds.max_queue_backlog
            ),
            "processing_latency_exceeded": (
                metrics.processing_latency_seconds
                > thresholds.max_processing_latency_seconds
            ),
            "lease_renewal_failures": (
                metrics.lease_renewal_failures
                > thresholds.max_lease_renewal_failures
            ),
            "scheduler_queue_backlog_exceeded": (
                metrics.scheduler_queue_backlog
                > thresholds.max_scheduler_queue_backlog
            ),
            "worker_throughput_below_threshold": (
                metrics.worker_throughput_per_minute
                < thresholds.min_worker_throughput_per_minute
            ),
        }
        return [reason for reason, failed in checks.items() if failed]
