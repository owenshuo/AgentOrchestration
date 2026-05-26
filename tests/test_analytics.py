import pytest

from src.common.analytics import (
    AnalyticsQuery,
    AnalyticsReportStore,
    AnalyticsScopeError,
)


def test_analytics_aggregation_scopes_workspace_before_sum():
    store = AnalyticsReportStore()
    store.record_event("workspace-a", "tasks.completed", 3)
    store.record_event("workspace-b", "tasks.completed", 100)
    store.record_event("workspace-a", "tasks.failed", 2)

    query = store.base_query("workspace-a")

    assert store.aggregate_metric(query, "tasks.completed") == 3


def test_analytics_export_scopes_workspace_before_rows_are_returned():
    store = AnalyticsReportStore()
    store.record_event(
        "workspace-a",
        "spend.total",
        25,
        {"category": "travel", "token": "do-not-audit"},
    )
    store.record_event(
        "workspace-b",
        "spend.total",
        100,
        {"category": "travel"},
    )

    rows = store.export_rows(
        store.base_query("workspace-a", dimensions={"category": "travel"}),
        metric="spend.total",
    )

    assert rows == [
        {
            "workspace_id": "workspace-a",
            "metric": "spend.total",
            "value": 25,
            "dimensions": {
                "category": "travel",
                "token": "do-not-audit",
            },
        }
    ]


def test_direct_aggregation_without_workspace_scope_is_blocked():
    store = AnalyticsReportStore()
    store.record_event("workspace-a", "tasks.completed", 3)

    with pytest.raises(AnalyticsScopeError, match="workspace scope"):
        store.aggregate_metric(
            AnalyticsQuery(workspace_id=""),
            "tasks.completed",
        )


def test_audit_report_explains_queries_without_dimension_values():
    store = AnalyticsReportStore()
    store.record_event(
        "workspace-a",
        "spend.total",
        25,
        {"category": "travel", "token": "do-not-audit"},
    )
    query = store.base_query(
        "workspace-a",
        dimensions={"category": "travel", "token": "do-not-audit"},
    )

    assert store.aggregate_metric(query, "spend.total") == 25
    report = store.audit_report()

    assert report == {
        "total": 1,
        "by_operation": {"aggregate": 1},
        "by_workspace": {"workspace-a": 1},
        "recent": [
            {
                "operation": "aggregate",
                "workspace_id": "workspace-a",
                "metric": "spend.total",
                "dimension_keys": ["category", "token"],
                "row_count": 1,
            }
        ],
    }
    assert "travel" not in str(report)
    assert "do-not-audit" not in str(report)

    report["recent"][0]["row_count"] = 999
    assert store.audit_events[0]["row_count"] == 1
