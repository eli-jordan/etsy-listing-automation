# shellcheck shell=bash
# Starts the agent lint gate for Claude Code and Grok (spec S06).
#
# The hook command sources this file (`. scripts/agent_lint_launch.sh MODE`)
# rather than running it, so it costs no second bash. It only picks the
# interpreter: scripts/agent_lint_gate.py decides, for every agent, whether a
# shell command could have written a file, and reads the payload on stdin.
# `-S` keeps Python's start-up to the standard library the gate needs.

_agent_lint_root=${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}
_agent_lint_root=${_agent_lint_root//\\//}
for _agent_lint_python in "$_agent_lint_root/.venv/Scripts/python.exe" "$_agent_lint_root/.venv/bin/python"; do
	[[ -x $_agent_lint_python ]] && exec "$_agent_lint_python" -S "$_agent_lint_root/scripts/agent_lint_gate.py" "$@"
done
exec uv run --no-project python "$_agent_lint_root/scripts/agent_lint_gate.py" "$@"
