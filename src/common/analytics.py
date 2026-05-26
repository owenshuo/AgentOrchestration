"""Workspace-scoped analytics reporting helpers."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class AnalyticsScopeError(ValueError):
    """Raised when an analytics query is missing required workspace scope."""


@dataclass(frozen=True)
class AnalyticsEvent:
    workspace_id: str
    metric: str
    value: float
    dimensions: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalyticsQuery:
    workspace_id: str
    metric: Optional[str] = None
    dimensions: Dict[str, Any] = field(default_factory=dict)


class AnalyticsReportStore:
    """Builds analytics reports with workspace scope in the base query."""

    def __init__(self):
        self._events: List[AnalyticsEvent] = []
        self._audit_events: List[Dict[str, Any]] = []

    def record_event(
        self,
        workspace_id: str,
        metric: str,
        value: float,
        dimensions: Optional[Dict[str, Any]] = None,
    ) -> None:
        workspace_id = self._require_text("workspace_id", workspace_id)
        metric = self._require_text("metric", metric)
        self._events.append(
            AnalyticsEvent(
                workspace_id=workspace_id,
                metric=metric,
                value=value,
                dimensions=dict(dimensions or {}),
            )
        )

    def base_query(
        self,
        workspace_id: str,
        metric: Optional[str] = None,
        dimensions: Optional[Dict[str, Any]] = None,
    ) -> AnalyticsQuery:
        return AnalyticsQuery(
            workspace_id=self._require_text("workspace_id", workspace_id),
            metric=metric,
            dimensions=dict(dimensions or {}),
        )

    def aggregate_metric(self, query: AnalyticsQuery, metric: str) -> float:
        scoped_query = self._require_scoped_query(query)
        metric = self._require_text("metric", metric)
        rows = self._matching_events(scoped_query, metric)
        total = sum(row.value for row in rows)
        self._record_audit("aggregate", scoped_query, metric, len(rows))
        return total

    def export_rows(
        self,
        query: AnalyticsQuery,
        metric: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        scoped_query = self._require_scoped_query(query)
        rows = self._matching_events(scoped_query, metric)
        self._record_audit("export", scoped_query, metric, len(rows))
        return [
            {
                "workspace_id": row.workspace_id,
                "metric": row.metric,
                "value": row.value,
                "dimensions": dict(row.dimensions),
            }
            for row in rows
        ]

    @property
    def audit_events(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self._audit_events]

    def audit_report(self) -> Dict[str, Any]:
        return {
            "total": len(self._audit_events),
            "by_operation": self._count_by("operation"),
            "by_workspace": self._count_by("workspace_id"),
            "recent": self.audit_events,
        }

    def _matching_events(
        self,
        query: AnalyticsQuery,
        metric: Optional[str],
    ) -> List[AnalyticsEvent]:
        return [
            row
            for row in self._events
            if row.workspace_id == query.workspace_id
            and (metric is None or row.metric == metric)
            and self._dimensions_match(row.dimensions, query.dimensions)
        ]

    def _require_scoped_query(self, query: AnalyticsQuery) -> AnalyticsQuery:
        if not isinstance(query, AnalyticsQuery) or not query.workspace_id:
            raise AnalyticsScopeError(
                "analytics queries require workspace scope"
            )
        return query

    def _record_audit(
        self,
        operation: str,
        query: AnalyticsQuery,
        metric: Optional[str],
        row_count: int,
    ) -> None:
        self._audit_events.append(
            {
                "operation": operation,
                "workspace_id": query.workspace_id,
                "metric": metric,
                "dimension_keys": sorted(query.dimensions),
                "row_count": row_count,
            }
        )

    def _count_by(self, field_name: str) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for event in self._audit_events:
            key = str(event[field_name])
            counts[key] = counts.get(key, 0) + 1
        return counts

    @staticmethod
    def _dimensions_match(
        dimensions: Dict[str, Any],
        required: Dict[str, Any],
    ) -> bool:
        return all(
            dimensions.get(key) == value
            for key, value in required.items()
        )

    @staticmethod
    def _require_text(field_name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise AnalyticsScopeError(f"{field_name} is required")
        return value.strip()
