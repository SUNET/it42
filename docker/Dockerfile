FROM ghcr.io/astral-sh/uv:0.12.22 AS uv

FROM python:3.13.16-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /uvx /bin/

# Trust the local mkcert CA so a future service-to-service HTTPS call works.
COPY certs/rootCA.pem /usr/local/share/ca-certificates/it42-root.crt
RUN update-ca-certificates

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY manage.py ./
COPY templates ./templates
COPY static ./static
COPY docker/entrypoint.sh docker/worker.sh /usr/local/bin/
RUN uv sync --frozen --no-dev \
    && APP_ROLE=core python manage.py collectstatic --noinput

RUN useradd --uid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/media && chown app:app /app/media
USER app

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["web"]
