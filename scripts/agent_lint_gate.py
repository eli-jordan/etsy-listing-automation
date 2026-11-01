"""Skip the agent lint hook after shell commands that cannot have written a file (spec S06).

Every agent's hook starts here: Claude Code and Grok through
scripts/agent_lint_launch.sh, Codex directly from its session shell
(PowerShell on Windows). It runs as
`python -S` and, to decide fast, imports nothing but `os`, `re` and `sys` and
reads the payload as text: `json` alone would cost more than the rest of the
decision. The rules are scripts/agent_lint_rules.txt. A command that may have
written anything, an edit, or a session event continues in this same process
with the full hook (`agent_lint.py`), so falling through costs no second
start.
"""

from __future__ import annotations

import os
import re
import sys

RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_lint_rules.txt")
SEPARATORS = re.compile(r"&&|\|\||;|\||\n")
QUOTES = "'\""
SHELL_TOOL = re.compile(r'"tool_name"\s*:\s*"Bash"')
COMMAND_FIELD = re.compile(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _rules() -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {"strip": [], "unwrap": [], "deny": [], "allow": []}
    with open(RULES, encoding="utf-8") as lines:
        for line in lines:
            kind, _, value = line.rstrip("\r\n").partition(" ")
            if kind in rules and value:
                rules[kind].append(value)
    return rules


def _unwrap(command: str, wrappers: list[str]) -> str:
    """The command a shell wrapper (`bash -lc '...'`, `powershell -Command ...`) runs."""
    for wrapper in wrappers:
        match = re.search(wrapper, command)
        if match:
            inner = match.group(match.re.groups)
            return inner[:-1] if inner[-1:] in QUOTES else inner
    return command


def is_read_only(command: str) -> bool:
    """True when every segment of the command only reads, by the shared rules."""
    rules = _rules()
    command = _unwrap(command.strip(), rules["unwrap"])
    for text in rules["strip"]:
        command = command.replace(text, "")
    if any(re.search(pattern, command) for pattern in rules["deny"]):
        return False
    segments = (segment.strip() for segment in SEPARATORS.split(command))
    return all(
        any(re.search(pattern, segment) for pattern in rules["allow"])
        for segment in segments
        if segment
    )


def shell_command(payload: str) -> str | None:
    """The command of a shell-tool payload, read as text without the json module.

    None for anything else, and for a command whose JSON escapes this does
    not decode (`\\uXXXX` could spell a `>`): those go to the full check.
    """
    if not SHELL_TOOL.search(payload):
        return None
    match = COMMAND_FIELD.search(payload)
    if match is None or "\\u" in match.group(1):
        return None
    command = match.group(1).replace('\\"', '"').replace("\\n", "\n").replace("\\t", " ")
    return command.replace("\\\\", "\\")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "edit"
    payload = sys.stdin.read()
    if mode == "edit":
        command = shell_command(payload)
        if command is not None and is_read_only(command):
            return 0
    # The full hook loads only when it has work, keeping the skip near 0.1s.
    import json  # noqa: PLC0415 -- see above

    import agent_lint  # noqa: PLC0415 -- see above

    return agent_lint.run(mode, json.loads(payload or "{}"))


if __name__ == "__main__":
    sys.exit(main())
