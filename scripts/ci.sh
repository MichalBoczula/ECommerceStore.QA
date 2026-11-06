#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

uv sync --locked
uv run --locked --no-sync ruff format --check .
uv run --locked --no-sync ruff check .
uv run --locked --no-sync pyright
uv run --locked --no-sync pytest -q
uv build --wheel
