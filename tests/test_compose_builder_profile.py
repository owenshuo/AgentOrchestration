from pathlib import Path

import yaml


COMPOSE_PATH = (
    Path(__file__).resolve().parents[1] / "infra" / "docker-compose.yml"
)
README_PATH = Path(__file__).resolve().parents[1] / "infra" / "README.md"
DOCKER_SOCKET = "/var/run/docker.sock"


def load_compose():
    with COMPOSE_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def service_mounts(service):
    mounts = []
    for volume in service.get("volumes", []):
        if isinstance(volume, str):
            mounts.append(volume)
        else:
            mounts.extend(
                str(volume.get(key, "")) for key in ("source", "target")
            )
    return mounts


def test_default_services_do_not_mount_host_docker_socket():
    compose = load_compose()

    for name, service in compose["services"].items():
        if "builder" in service.get("profiles", []):
            continue
        mounts = service_mounts(service)
        assert all(DOCKER_SOCKET not in mount for mount in mounts), name


def test_builder_profile_is_required_for_docker_socket_access():
    compose = load_compose()
    builder = compose["services"]["builder"]

    assert builder["profiles"] == ["builder"]
    assert any(DOCKER_SOCKET in mount for mount in service_mounts(builder))
    assert builder["read_only"] is True
    assert "no-new-privileges:true" in builder["security_opt"]


def test_worker_uses_builder_endpoint_instead_of_socket_mount():
    compose = load_compose()
    worker = compose["services"]["worker"]

    assert "AO_BUILDER_ENDPOINT" in worker["environment"]
    assert DOCKER_SOCKET not in " ".join(service_mounts(worker))


def test_builder_security_boundary_is_documented():
    text = README_PATH.read_text(encoding="utf-8")

    assert "--profile builder" in text
    assert DOCKER_SOCKET in text
    assert "default local stack" in text
    assert "without mounting" in text
