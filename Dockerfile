FROM python:3.11-slim AS deps

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
        "/runtime-deps",
        *dependencies,
    ]
)
PY

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY --from=deps /runtime-deps /usr/local
COPY src ./src

EXPOSE 8000
CMD ["uvicorn", "src.api.server:create_app", "--factory", "--host", \
     "0.0.0.0", "--port", "8000"]
