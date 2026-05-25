"""Publish-time anonymity checks for analytics metric groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping


class AnalyticsPublishError(ValueError):
    """Raised when analytics output cannot satisfy anonymity policy."""


@dataclass(frozen=True)
class AggregateMetricGroup:
    group_key: str
    member_count: int
    metrics: Mapping[str, float]
    anonymized: bool = True

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "AggregateMetricGroup":
        return cls(
            group_key=str(payload["group_key"]),
            member_count=int(payload["member_count"]),
            metrics=dict(payload.get("metrics", {})),
            anonymized=bool(payload.get("anonymized", False)),
        )


@dataclass(frozen=True)
class SuppressedMetricGroup:
    group_key: str
    reason: str
    threshold: int


@dataclass(frozen=True)
class AnalyticsPublishResult:
    published: List[AggregateMetricGroup]
    suppressed: List[SuppressedMetricGroup]


class AnalyticsPublisher:
    def __init__(self, minimum_group_size: int = 5):
        if minimum_group_size < 1:
            raise AnalyticsPublishError(
                "minimum_group_size must be at least one"
            )
        self.minimum_group_size = minimum_group_size

    def publish(
        self,
        groups: Iterable[Mapping[str, Any] | AggregateMetricGroup],
    ) -> AnalyticsPublishResult:
        published: List[AggregateMetricGroup] = []
        suppressed: List[SuppressedMetricGroup] = []

        for item in groups:
            group = self._coerce_group(item)
            if not group.anonymized:
                suppressed.append(
                    self._suppressed(
                        group,
                        "missing_anonymization_flag",
                    )
                )
                continue
            if group.member_count < self.minimum_group_size:
                suppressed.append(
                    self._suppressed(
                        group,
                        "minimum_group_size_not_met",
                    )
                )
                continue
            published.append(group)

        if suppressed:
            raise AnalyticsPublishError(
                "analytics publish suppressed groups below anonymity policy"
            )
        return AnalyticsPublishResult(published=published, suppressed=[])

    def validate(
        self,
        groups: Iterable[Mapping[str, Any] | AggregateMetricGroup],
    ) -> AnalyticsPublishResult:
        published: List[AggregateMetricGroup] = []
        suppressed: List[SuppressedMetricGroup] = []
        for item in groups:
            group = self._coerce_group(item)
            if (
                group.anonymized
                and group.member_count >= self.minimum_group_size
            ):
                published.append(group)
            else:
                reason = "minimum_group_size_not_met"
                if not group.anonymized:
                    reason = "missing_anonymization_flag"
                suppressed.append(self._suppressed(group, reason))
        return AnalyticsPublishResult(
            published=published,
            suppressed=suppressed,
        )

    def suppression_report(
        self,
        groups: Iterable[Mapping[str, Any] | AggregateMetricGroup],
    ) -> List[Dict[str, Any]]:
        result = self.validate(groups)
        return [
            {
                "group_key": group.group_key,
                "reason": group.reason,
                "threshold": group.threshold,
            }
            for group in result.suppressed
        ]

    def _coerce_group(
        self,
        item: Mapping[str, Any] | AggregateMetricGroup,
    ) -> AggregateMetricGroup:
        if isinstance(item, AggregateMetricGroup):
            return item
        return AggregateMetricGroup.from_mapping(item)

    def _suppressed(
        self,
        group: AggregateMetricGroup,
        reason: str,
    ) -> SuppressedMetricGroup:
        return SuppressedMetricGroup(
            group_key=group.group_key,
            reason=reason,
            threshold=self.minimum_group_size,
        )
