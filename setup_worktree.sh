#!/bin/bash
# For running by hand from cygwin. T3 runs scripts/setup_worktree.py directly
# (t3.json): its Windows terminal is PowerShell, which cannot run a .sh.
cd "$(dirname "$0")" && exec uv run --no-project python scripts/setup_worktree.py
