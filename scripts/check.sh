#!/usr/bin/env bash
# Format, lint, type-check and test in one command. Run before every commit.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff format =="
uv run ruff format .

echo "== ruff check =="
uv run ruff check .

echo "== mypy =="
uv run mypy src

echo "== pytest =="
uv run pytest

echo "All checks passed."
