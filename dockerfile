FROM python:3.12-slim

# Install system dependencies + uv
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files first (for layer caching)
COPY pyproject.toml uv.lock ./

# Install project + dependencies
RUN uv sync --frozen

# Copy the rest of the application
COPY . .

# The app already sets host=0.0.0.0 in config.toml
EXPOSE 8181

CMD ["uv", "run", "main.py"]
