FROM python:3.11-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install . \
    && find /opt/venv -type d -name "__pycache__" -prune -exec rm -rf {} + \
    && rm -rf /root/.cache /tmp/* /var/tmp/*

FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY src ./src

RUN groupadd --system ao \
    && useradd --system --gid ao --create-home --home-dir /home/ao ao \
    && rm -rf /root/.cache /home/ao/.cache /tmp/* /var/tmp/* \
        /var/cache/apt/* /var/lib/apt/lists/*

USER ao
