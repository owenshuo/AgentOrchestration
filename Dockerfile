FROM python:3.11-slim AS builder

ARG AO_BUILD_CONFIG

WORKDIR /build
COPY pyproject.toml ./
RUN python - <<'PY'
import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as source:
    dependencies = tomllib.load(source)["project"]["dependencies"]

subprocess.check_call(
    [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-cache-dir",
        "--prefix",
        "/install",
        *dependencies,
    ]
)
PY

COPY src ./src

FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="agent-orchestrator" \
      org.opencontainers.image.version="2.4.1" \
      org.opencontainers.image.description="Agent Orchestration runtime image"

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --from=builder /build/src ./src

EXPOSE 8000
CMD ["uvicorn", "src.api.server:create_app", "--factory", "--host", \
     "0.0.0.0", "--port", "8000"]
