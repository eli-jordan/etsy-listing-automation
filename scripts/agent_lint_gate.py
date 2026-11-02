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

The command is split as its shell splits it, quotes and escapes included, so
a quoted `;` or `>` is text and a bare `&` starts another command. Every
command the line runs is judged: each segment, each `$(...)`, backtick and
`<(...)`, and the script of a nested shell, however deep. A construct the
reader does not follow (an open quote, a subshell, a script block) falls
through.
"""

from __future__ import annotations

import os
import re
import sys

RULES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_lint_rules.txt")
SHELL_TOOL = re.compile(r'"tool_name"\s*:\s*"(Bash|PowerShell)"')
COMMAND_FIELD = re.compile(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"')
JSON_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
JSON_CHARACTERS = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}
KINDS = ("allow", "deny", "unwrap", "unwrap-powershell", "prefix", "target", "variable")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(=.*)?", re.DOTALL)
# What a backslash escapes in bash but not in PowerShell, unquoted and in
# double quotes: a Bash payload may come from Codex's PowerShell, which
# would split such a line differently.
SPLIT_ESCAPES = "\"'`$;&|<>()# \t\n"
SPLIT_ESCAPES_QUOTED = '"`$'
FD_PREFIXES = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "*")
BRACED_VARIABLE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
# PowerShell takes curly quotes for quotes and dashes for `-`; bash takes
# them as text.
LOOKALIKES = re.compile("[\u2013-\u2015\u2018-\u201f]")
PLACEHOLDER = "$_"
DEPTH = 8
HANDLERS = {
    " ": "_blank",
    "\t": "_blank",
    "\r": "_blank",
    "\n": "_newline",
    "#": "_comment",
    "'": "_quoted",
    '"': "_quoted",
    "\\": "_backslash",
    "`": "_backtick",
    "$": "_dollar",
    "<": "_less",
    ">": "_greater",
    "&": "_ampersand",
    ";": "_separator",
    "|": "_separator",
    "(": "_open",
    ")": "_unread",
    "{": "_brace",
    "}": "_brace",
}


class _UnreadError(Exception):
    """A construct the reader does not follow: the command falls through."""


def _rules() -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {kind: [] for kind in KINDS}
    with open(RULES, encoding="utf-8") as lines:
        for line in lines:
            kind, _, value = line.rstrip("\r\n").partition(" ")
            if kind in rules and value:
                rules[kind].append(value)
    return rules


class _Reader:
    """Splits a command line into segments of words, as bash or PowerShell does.

    A word is (raw, value): its source text and what the shell passes on,
    quotes removed. Redirects and heredoc bodies leave no words; the
    commands that substitutions run are collected in `inner`.
    """

    def __init__(self, text: str, targets: list[str], *, powershell: bool, strict: bool) -> None:
        self.text, self.targets, self.powershell = text, targets, powershell
        self.strict = strict  # bash that PowerShell may be the one to run
        self.segments: list[list[tuple[str, str]]] = [[]]
        self.inner: list[str] = []
        self.heredocs: list[tuple[str, bool, bool]] = []
        self.raw: list[str] = []
        self.value: list[str] = []
        self.pending = ""  # what the next word is: "target", "input" or "heredoc"

    def read(self, start: int = 0, closer: str = "") -> int:
        """Reads to the unquoted `closer`, or the end; the index after it."""
        i = start
        while i < len(self.text):
            if closer and self.text[i] == closer:
                self._end_segment()
                return i + 1
            i = getattr(self, HANDLERS.get(self.text[i], "_plain"))(i)
        if closer or self.heredocs:
            raise _UnreadError
        self._end_segment()
        return i

    # --- one character, by what it is -------------------------------------

    def _plain(self, i: int) -> int:
        self._add(self.text[i], self.text[i])
        return i + 1

    def _blank(self, i: int) -> int:
        self._end_word()
        return i + 1

    def _newline(self, i: int) -> int:
        self._end_segment()
        for delimiter, literal, tabs in self.heredocs:
            i = self._skip_heredoc(i + 1, delimiter, literal=literal, tabs=tabs) - 1
        self.heredocs = []
        return i + 1

    def _comment(self, i: int) -> int:
        if self.raw:
            return self._plain(i)
        end = self.text.find("\n", i)
        return len(self.text) if end < 0 else end

    def _quoted(self, i: int) -> int:
        quote, j = self.text[i], i + 1
        value: list[str] = []
        while not self._closes(j, quote):
            j = self._quoted_character(j, quote, value)
        self._add(self.text[i : j + 1], "".join(value))
        return j + 1

    def _backslash(self, i: int) -> int:
        return self._plain(i) if self.powershell else self._escaped(i)

    def _backtick(self, i: int) -> int:
        if self.strict:
            raise _UnreadError  # bash substitutes, PowerShell escapes
        return self._escaped(i) if self.powershell else self._substitution(i + 1, "`")

    def _dollar(self, i: int) -> int:
        if self.text[i + 1 : i + 2] == "(":
            return self._substitution(i + 2, ")")
        braced = BRACED_VARIABLE.match(self.text, i)
        if braced:
            self._add(braced.group(), braced.group())
            return braced.end()
        return self._plain(i)

    def _less(self, i: int) -> int:
        if self.text[i + 1 : i + 2] == "(" and not self.powershell:
            return self._substitution(i + 2, ")")
        if self.powershell or self.text[i + 1 : i + 2] == ">":
            raise _UnreadError
        return self._input(i)

    def _greater(self, i: int) -> int:
        if self.text[i + 1 : i + 2] == "(" and not self.powershell:
            return self._substitution(i + 2, ")")
        return self._output(i, i + 1)

    def _ampersand(self, i: int) -> int:
        if self.text[i + 1 : i + 2] == ">":
            return self._output(i, i + 2)
        return self._separator(i)

    def _separator(self, i: int) -> int:
        self._end_segment()
        return i + 2 if self.text[i : i + 2] in ("&&", "||", "|&", ";;") else i + 1

    def _unread(self, _i: int) -> int:
        raise _UnreadError

    def _open(self, i: int) -> int:
        # A subshell's commands are judged like a substitution's.
        if self.powershell or self.raw or self.segments[-1]:
            raise _UnreadError
        return self._nested(i + 1, ")")

    def _brace(self, i: int) -> int:
        # A PowerShell script block runs commands no segment shows.
        return self._unread(i) if self.powershell or self.strict else self._plain(i)

    # --- the pieces ---------------------------------------------------------

    def _add(self, raw: str, value: str) -> None:
        self.raw.append(raw)
        self.value.append(value)

    def _escaped(self, i: int) -> int:
        following = self.text[i + 1 : i + 2]
        if self.strict and following in SPLIT_ESCAPES:
            raise _UnreadError
        if following != "\n":  # else a line continuation
            self._add(self.text[i : i + 2], following)
        return i + 2

    def _closes(self, j: int, quote: str) -> bool:
        if j >= len(self.text):
            raise _UnreadError  # never closed
        doubled = self.powershell and self.text[j + 1 : j + 2] == quote
        return self.text[j] == quote and not doubled

    def _quoted_character(self, j: int, quote: str, value: list[str]) -> int:
        char = self.text[j]
        if char == quote:  # doubled, in PowerShell: one quote
            value.append(quote)
            return j + 2
        if quote == "'":
            value.append(char)
            return j + 1
        return self._double_quoted_character(j, value)

    def _double_quoted_character(self, j: int, value: list[str]) -> int:
        text, char = self.text, self.text[j]
        if char == ("`" if self.powershell else "\\") and j + 1 < len(text):
            return self._double_quoted_escape(j, value)
        if text[j : j + 2] == "$(" or char == "`":
            if char == "`" and self.strict:
                raise _UnreadError  # bash substitutes, PowerShell escapes
            value.append(PLACEHOLDER)
            return self._nested(j + 2, ")") if char == "$" else self._nested(j + 1, "`")
        value.append(char)
        return j + 1

    def _double_quoted_escape(self, j: int, value: list[str]) -> int:
        char, escaped = self.text[j], self.text[j + 1]
        if self.strict and escaped in SPLIT_ESCAPES_QUOTED:
            raise _UnreadError
        value.append(escaped if self.powershell or escaped in '"\\$`\n' else char + escaped)
        return j + 2

    def _nested(self, start: int, closer: str) -> int:
        reader = _Reader(self.text, self.targets, powershell=self.powershell, strict=self.strict)
        end = reader.read(start, closer)
        self.inner.append(self.text[start : end - 1])
        return end

    def _substitution(self, start: int, closer: str) -> int:
        end = self._nested(start, closer)
        self._add(PLACEHOLDER, PLACEHOLDER)
        return end

    def _input(self, i: int) -> int:
        self._end_word()
        if self.text[i : i + 3] == "<<<":
            return i + 3  # a here-string: its word is data
        if self.text[i : i + 2] == "<&":
            return i + 2
        if self.text[i : i + 2] == "<<":
            tabs = self.text[i + 2 : i + 3] == "-"
            self.pending = "heredoc-" if tabs else "heredoc"
            return i + 3 if tabs else i + 2
        self.pending = "input"
        return i + 1

    def _output(self, i: int, j: int) -> int:
        """A redirect at i, its operator read to j: a copy, or a file to name."""
        if "".join(self.raw) in FD_PREFIXES:
            self.raw, self.value = [], []  # `2>`: the number is the redirect's
        self._end_word()
        if self.text[j : j + 1] in (">", "|"):
            j += 1
        if self.text[j : j + 1] == "&" and self.text[i] == ">":
            if re.match(r"[0-9-]", self.text[j + 1 : j + 2]):
                return j + 2  # a copy of another descriptor: 2>&1
            j += 1
        self.pending = "target"
        return j

    def _end_word(self) -> None:
        if not self.raw:
            return
        raw, value = "".join(self.raw), "".join(self.value)
        self.raw, self.value = [], []
        pending, self.pending = self.pending, ""
        if pending == "target" and not any(re.fullmatch(t, value) for t in self.targets):
            raise _UnreadError
        if pending.startswith("heredoc"):
            self.heredocs.append((value, raw != value, pending == "heredoc-"))
        elif not pending:
            self.segments[-1].append((raw, value))

    def _end_segment(self) -> None:
        self._end_word()
        if self.pending:
            raise _UnreadError  # a redirect or heredoc that names nothing
        if self.segments[-1]:
            self.segments.append([])

    def _skip_heredoc(self, i: int, delimiter: str, *, literal: bool, tabs: bool) -> int:
        """The index after a heredoc body that starts at i."""
        while i < len(self.text):
            end = self.text.find("\n", i)
            end = len(self.text) if end < 0 else end
            if _ends_heredoc(self.text[i:end], delimiter, literal=literal, tabs=tabs):
                return end + 1
            i = end + 1
        raise _UnreadError  # never closed


def _ends_heredoc(line: str, delimiter: str, *, literal: bool, tabs: bool) -> bool:
    """Whether a body line closes its heredoc. The body is data, unless it substitutes."""
    line = line.rstrip("\r")
    if (line.lstrip("\t") if tabs else line) == delimiter:
        return True
    if not literal and ("$(" in line or "`" in line):
        raise _UnreadError
    return False


def _program(word: str) -> str:
    """`git` for `/usr/bin/git`, `'C:/Program Files/Git/cmd/git.exe'` or `git.exe`."""
    name = re.split(r"[/\\]", word.strip("'\""))[-1]
    if " " in name:
        return word  # `'git status'` runs no git
    return name[:-4] if name.lower().endswith(".exe") else name


def _assignments(words: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[str]]:
    """The segment without its leading VAR=value words, and every assignment it makes."""
    assigned = []
    while words and ASSIGNMENT.match(words[0][1]):
        assigned.append(words[0][1])
        words = words[1:]
    if words and words[0][1] in ("export", "unset", "declare", "typeset", "local"):
        assigned += [value for _, value in words[1:] if VARIABLE.fullmatch(value)]
    return words, assigned


def _leading(texts: list[str], patterns: list[str], most: int) -> int:
    """How many leading words, up to `most`, the longest match of a pattern spans, or 0."""
    spans = range(most, 0, -1)
    spanned = (n for n in spans if any(re.fullmatch(p, " ".join(texts[:n])) for p in patterns))
    return next(spanned, 0)


def _bare(
    words: list[tuple[str, str]], rules: dict[str, list[str]]
) -> tuple[list[tuple[str, str]], str | None]:
    """The segment without its assignments and prefixes, and an assignment it may not make."""
    assigned: list[str] = []
    while True:
        words, made = _assignments(words)
        assigned += made
        prefix = _leading([value for _, value in words], rules["prefix"], len(words))
        if not prefix:
            break
        words = words[prefix:]
    unsafe = (
        each
        for each in assigned
        if any(re.fullmatch(v, each, re.DOTALL) for v in rules["variable"])
    )
    return words, next(unsafe, None)


def _unwrapped(words: list[tuple[str, str]], rules: dict[str, list[str]], depth: int) -> str | None:
    """Why a nested shell's script may write; "" when the segment is no nested shell."""
    raws = [raw for raw, _ in words]
    for powershell, kind in ((False, "unwrap"), (True, "unwrap-powershell")):
        count = _leading(raws, rules[kind], len(words) - 1)
        if not count:
            continue
        if count == len(words) - 1:
            script = words[-1][1]
        elif powershell:
            script = " ".join(raws[count:])  # PowerShell joins the rest into its script
        else:
            return "shell arguments"  # a POSIX shell's further words: not followed
        return _problem(script, rules, powershell=powershell, strict=False, depth=depth + 1)
    return ""


def _matched(text: str, rules: dict[str, list[str]]) -> str | None:
    """Why a segment's text may write, by the deny and allow rules."""
    denied = next(
        (pattern for pattern in rules["deny"] if re.search(pattern, text, re.DOTALL)), None
    )
    if denied:
        return "deny " + denied
    if any(re.search(pattern, text) for pattern in rules["allow"]):
        return None
    return "segment " + " ".join(text.split()[:2])[:40]


def _segment_problem(
    words: list[tuple[str, str]], rules: dict[str, list[str]], depth: int
) -> str | None:
    """Why one simple command may write, or None when it only reads."""
    words, unsafe = _bare(words, rules)
    if unsafe:
        return "variable " + unsafe
    if not words:
        return None
    words = [(_program(words[0][0]),) * 2, *words[1:]]
    nested = _unwrapped(words, rules, depth)
    if nested != "":
        return nested
    return _matched(" ".join(raw for raw, _ in words), rules)


def _problem(
    command: str, rules: dict[str, list[str]], *, powershell: bool, strict: bool, depth: int
) -> str | None:
    if depth > DEPTH:
        return "nested too deep"
    reader = _Reader(command, rules["target"], powershell=powershell, strict=strict)
    try:
        reader.read()
    except _UnreadError:
        return "unread"
    inner = (
        _problem(text, rules, powershell=powershell, strict=strict, depth=depth + 1)
        for text in reader.inner
    )
    segments = (_segment_problem(words, rules, depth) for words in reader.segments if words)
    return next(filter(None, inner), None) or next(filter(None, segments), None)


def why_not(command: str, *, powershell: bool = False) -> str | None:
    """What may make the command write a file, or None when it only reads.

    Read as bash, a command must also hold no escape PowerShell would read
    differently, since Codex reports its PowerShell commands as Bash.
    """
    if LOOKALIKES.search(command):
        return "lookalike"
    rules = _rules()
    return _problem(command.strip(), rules, powershell=powershell, strict=not powershell, depth=0)


def is_read_only(command: str, *, powershell: bool = False) -> bool:
    """True when every command the line runs only reads, by the shared rules."""
    return why_not(command, powershell=powershell) is None


def shell_command(payload: str) -> tuple[str, bool] | None:
    """The command of a shell-tool payload, and whether PowerShell runs it.

    Read as text, without the json module. None for anything else, and for
    a command whose JSON escapes this does not decode (`\\uXXXX` could spell
    a `>`): those go to the full check.
    """
    tool = SHELL_TOOL.search(payload)
    match = COMMAND_FIELD.search(payload) if tool else None
    if tool is None or match is None or "\\u" in match.group(1):
        return None
    command = JSON_ESCAPE.sub(lambda m: JSON_CHARACTERS.get(m[1], m[1]), match.group(1))
    return command, tool.group(1) == "PowerShell"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "edit"
    payload = sys.stdin.read()
    if mode == "edit":
        shell = shell_command(payload)
        if shell is not None and is_read_only(shell[0], powershell=shell[1]):
            return 0
    # The full hook loads only when it has work, keeping the skip near 0.1s.
    import json  # noqa: PLC0415 -- see above

    import agent_lint  # noqa: PLC0415 -- see above

    return agent_lint.run(mode, json.loads(payload or "{}"))


if __name__ == "__main__":
    sys.exit(main())
