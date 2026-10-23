FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /bin/uv

# The virtualenv lives outside /app so the dev bind mount (compose.yml) does not hide it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    PICCOLO_CONF=core.database

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8000

# Applique les migrations puis lance uvicorn (uvicorn.workers pour gunicorn est déprécié)
CMD ["sh", "-c", "piccolo migrations forwards all && uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers"]
