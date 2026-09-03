#!/usr/bin/env bash
# Format, lint, type-check and test (with the coverage gate) in one command.
# Run before every commit. Intended to be run from cygwin zsh -- the tools are
# Windows-native binaries on the cygwin PATH via ~/.zshenv, and cygwin
# translates the working directory for them.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff format =="
uv run ruff format .

echo "== ruff check =="
uv run ruff check .

echo "== mypy =="
uv run mypy src

# Coverage is measured over the whole suite, browser layer included. Those
# tests skip themselves when chromium or ui/frontend/dist is missing, which
# costs about a point -- the gate has enough headroom to pass either way, so a
# missing browser never fails the build for the wrong reason.
echo "== pytest + coverage (branch, fail under 80%) =="
uv run pytest --cov --cov-report=term-missing --cov-report=html

# The frontend gate mirrors the Python one -- branch coverage, 80% floor --
# and skips cleanly (not a failure) when node/npm isn't on PATH, the same
# self-skip pattern the browser pytest layer uses for missing chromium, so a
# Python-only contributor's check.sh run isn't blocked by a toolchain they
# don't have installed.
FRONTEND_DIR="src/etsy_listings/ui/frontend"
if command -v npm >/dev/null 2>&1; then
  echo "== frontend: lint, typecheck, test + coverage (branch, fail under 80%) =="
  (cd "$FRONTEND_DIR" && npm run lint && npm run typecheck && npm run test:coverage)
else
  echo "== frontend checks skipped: npm not on PATH =="
fi

echo
echo "All checks passed. Coverage detail: htmlcov/index.html, $FRONTEND_DIR/coverage/index.html"
