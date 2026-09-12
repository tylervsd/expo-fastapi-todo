FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

FROM python:3.14.7-slim-bookworm

COPY --from=uv /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && rm -rf /root/.cache/uv

COPY app ./app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app

USER 10001:10001

EXPOSE 8080

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8080}\""]
