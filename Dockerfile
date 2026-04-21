FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev

COPY . .

EXPOSE 8181

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8181/health || exit 1

CMD [".venv/bin/python", "main.py"]
