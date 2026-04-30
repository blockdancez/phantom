FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir .
# Playwright (chromium) is only needed by TwitterTrendsCollector.
# Install it best-effort — if the CDN is unreachable the build still succeeds
# and the Twitter collector simply skips at runtime.
RUN playwright install --with-deps chromium || echo "WARN: playwright install failed, Twitter collector will be unavailable"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
