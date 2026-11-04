#!/bin/sh
# Format check, lint and type check.
set -eu
cd "$(dirname "$0")/.."
uv run ruff format --check .
uv run ruff check .
uv run ty check src tests scripts
