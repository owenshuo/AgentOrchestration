import pytest

from src.agent.artifacts import (
    CrossRegionArtifactReader,
    InMemoryArtifactStore,
)
from src.common.errors import ArtifactConsistencyError, ArtifactNotFoundError


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay


def make_reader(
    clock,
    store,
    retry_delays=(1, 2, 3),
    replication_window_seconds=10,
):
    return CrossRegionArtifactReader(
        store,
        replication_window_seconds=replication_window_seconds,
        retry_delays=retry_delays,
        now=clock.monotonic,
        sleep=clock.sleep,
    )


def test_reads_from_origin_region_without_retry():
    clock = FakeClock()
    store = InMemoryArtifactStore(now=clock.monotonic)
    store.put(
        "artifact-1", b"payload", "us-east-1",
        replica_regions=["eu-west-1"],
    )

    result = make_reader(clock, store).read("artifact-1", "us-east-1")

    assert result.data == b"payload"
    assert result.region == "us-east-1"
    assert result.attempts == 1
    assert clock.sleeps == []


def test_delayed_replication_retries_until_replica_is_available():
    clock = FakeClock()
    store = InMemoryArtifactStore(now=clock.monotonic)
    store.put(
        "artifact-2", b"payload", "us-east-1",
        replica_regions=["eu-west-1"],
    )

    def sleep_and_replicate(delay):
        clock.sleep(delay)
        if len(clock.sleeps) == 2:
            store.mark_available("artifact-2", "eu-west-1", b"payload")

    reader = CrossRegionArtifactReader(
        store,
        replication_window_seconds=10,
        retry_delays=(1, 2, 3),
        now=clock.monotonic,
        sleep=sleep_and_replicate,
    )

    result = reader.read("artifact-2", "eu-west-1")

    assert result.data == b"payload"
    assert result.attempts == 3
    assert clock.sleeps == [1, 2]


def test_pending_replica_is_not_marked_permanently_missing_within_window():
    clock = FakeClock()
    store = InMemoryArtifactStore(now=clock.monotonic)
    store.put(
        "artifact-3", b"payload", "us-east-1",
        replica_regions=["eu-west-1"],
    )

    with pytest.raises(ArtifactNotFoundError) as exc_info:
        make_reader(
            clock, store, retry_delays=(1,), replication_window_seconds=10
        ).read(
            "artifact-3",
            "eu-west-1",
        )

    assert exc_info.value.metadata_state == "pending"
    assert exc_info.value.region == "eu-west-1"
    assert exc_info.value.origin_region == "us-east-1"


def test_missing_metadata_is_permanent_missing():
    clock = FakeClock()
    store = InMemoryArtifactStore(now=clock.monotonic)

    with pytest.raises(ArtifactNotFoundError) as exc_info:
        make_reader(clock, store).read("missing", "eu-west-1")

    assert exc_info.value.artifact_id == "missing"
    assert exc_info.value.region == "eu-west-1"
    assert exc_info.value.metadata_state == "missing"


def test_region_marked_missing_does_not_retry():
    clock = FakeClock()
    store = InMemoryArtifactStore(now=clock.monotonic)
    store.put(
        "artifact-4", b"payload", "us-east-1",
        replica_regions=["eu-west-1"],
    )
    store.mark_missing("artifact-4", "eu-west-1")

    with pytest.raises(ArtifactNotFoundError) as exc_info:
        make_reader(clock, store).read("artifact-4", "eu-west-1")

    assert exc_info.value.metadata_state == "missing"
    assert clock.sleeps == []


def test_pending_replica_after_window_includes_metadata_context():
    clock = FakeClock()
    store = InMemoryArtifactStore(now=clock.monotonic)
    store.put(
        "artifact-5", b"payload", "us-east-1",
        replica_regions=["eu-west-1"],
    )
    clock.now = 11

    with pytest.raises(ArtifactNotFoundError) as exc_info:
        make_reader(
            clock, store, retry_delays=(1,), replication_window_seconds=10
        ).read(
            "artifact-5",
            "eu-west-1",
        )

    assert exc_info.value.metadata_state == "pending"
    assert exc_info.value.replication_age_seconds == 11
    assert "origin_region=us-east-1" in str(exc_info.value)
    assert "region=eu-west-1" in str(exc_info.value)


def test_available_replica_with_digest_mismatch_fails_consistency_check():
    clock = FakeClock()
    store = InMemoryArtifactStore(now=clock.monotonic)
    store.put(
        "artifact-6", b"payload", "us-east-1",
        replica_regions=["eu-west-1"],
    )
    store.mark_available("artifact-6", "eu-west-1", b"corrupt")

    with pytest.raises(ArtifactConsistencyError) as exc_info:
        make_reader(clock, store).read("artifact-6", "eu-west-1")

    assert exc_info.value.artifact_id == "artifact-6"
    assert exc_info.value.region == "eu-west-1"
    assert exc_info.value.expected_digest != exc_info.value.actual_digest
