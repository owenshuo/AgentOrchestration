from scripts.audit_image_metadata import audit_metadata


def test_metadata_audit_accepts_clean_history_and_allowed_labels():
    metadata = {
        "history": [
            {"CreatedBy": "COPY src ./src"},
            {"CreatedBy": "CMD uvicorn src.api.server:create_app"},
        ],
        "inspect": [
            {
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.title": "agent-orchestrator",
                        "org.opencontainers.image.version": "2.4.1",
                    }
                }
            }
        ],
    }

    assert audit_metadata(metadata, ["build-only-sentinel"]) == []


def test_metadata_audit_rejects_forbidden_build_values():
    metadata = {
        "history": [
            {"CreatedBy": "RUN echo build-only-sentinel"},
        ],
        "inspect": [{"Config": {"Labels": {}}}],
    }

    failures = audit_metadata(metadata, ["build-only-sentinel"])

    assert failures == [
        "forbidden build value leaked into image history: build-only-sentinel"
    ]


def test_metadata_audit_rejects_unapproved_runtime_labels():
    metadata = {
        "history": [],
        "inspect": [
            {
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.title": "agent-orchestrator",
                        "build.config": "debug",
                    }
                }
            }
        ],
    }

    assert audit_metadata(metadata, []) == [
        "unapproved runtime image label: build.config"
    ]
