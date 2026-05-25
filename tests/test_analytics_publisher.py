import pytest

from src.analytics import AnalyticsPublishError, AnalyticsPublisher


def metric_group(group_key, member_count, anonymized=True):
    return {
        "group_key": group_key,
        "member_count": member_count,
        "anonymized": anonymized,
        "metrics": {
            "task_count": member_count * 3,
            "avg_runtime_ms": 120.0,
        },
    }


def test_publish_fails_for_group_below_anonymity_threshold():
    publisher = AnalyticsPublisher(minimum_group_size=5)
    groups = [metric_group("workspace-small", 4)]

    with pytest.raises(AnalyticsPublishError, match="suppressed groups"):
        publisher.publish(groups)

    assert publisher.suppression_report(groups) == [
        {
            "group_key": "workspace-small",
            "reason": "minimum_group_size_not_met",
            "threshold": 5,
        }
    ]


def test_publish_allows_group_at_boundary_threshold():
    publisher = AnalyticsPublisher(minimum_group_size=5)

    result = publisher.publish([metric_group("workspace-boundary", 5)])

    assert len(result.published) == 1
    assert result.published[0].group_key == "workspace-boundary"
    assert result.suppressed == []


def test_publish_allows_large_aggregate_group():
    publisher = AnalyticsPublisher(minimum_group_size=5)

    result = publisher.publish([metric_group("workspace-large", 30)])

    assert result.published[0].metrics["task_count"] == 90


def test_publish_fails_when_upstream_anonymization_flag_is_missing():
    publisher = AnalyticsPublisher(minimum_group_size=5)
    groups = [metric_group("workspace-raw", 30, anonymized=False)]

    with pytest.raises(AnalyticsPublishError):
        publisher.publish(groups)

    assert publisher.suppression_report(groups) == [
        {
            "group_key": "workspace-raw",
            "reason": "missing_anonymization_flag",
            "threshold": 5,
        }
    ]


def test_suppression_report_does_not_expose_metric_contents():
    publisher = AnalyticsPublisher(minimum_group_size=5)
    groups = [metric_group("workspace-small", 1)]

    report = publisher.suppression_report(groups)

    assert report == [
        {
            "group_key": "workspace-small",
            "reason": "minimum_group_size_not_met",
            "threshold": 5,
        }
    ]
    assert "metrics" not in report[0]
    assert "member_count" not in report[0]
