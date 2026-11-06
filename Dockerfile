FROM python:3.14.7-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --locked --no-dev --no-editable --no-install-project
COPY src/ ./src/
RUN uv sync --locked --no-dev --no-editable

FROM python:3.14.7-slim-bookworm
WORKDIR /app
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build --chown=10001:10001 /app/.venv /app/.venv
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "ecommerce_store_qa.main:app", "--host", "0.0.0.0", "--port", "8080"]
