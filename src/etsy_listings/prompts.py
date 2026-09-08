"""How an interactive command asks a question, given the terminal it got.

A package-root leaf like :mod:`etsy_listings.terminal`, and for the same
reason: it answers a question about the terminal rather than about any one
command. It lived in ``newcmd/`` while ``new`` was the only thing that
prompted; ``setup`` (PRD 43) is the second, and reaching into another
package's submodule for it would have been the wrong way to share this.

This module exists because of a hard constraint discovered while building the
garment picker: **questionary cannot prompt at all under cygwin.**
prompt_toolkit on ``sys.platform == "win32"`` only ever builds a Win32,
Windows-10-VT100 or ConEmu output, and a cygwin pty is a named pipe with no
console screen buffer behind it, so ``create_output()`` raises
``NoConsoleScreenBufferError`` before a single key is read. Verified under a
real pty (``script -q -c ... /dev/null``), not just a redirect. CLAUDE.md
mandates cygwin zsh as *the* shell for this project, so "run it somewhere
else" is not an answer -- ``new`` has to work there.

So each question picks the best backend that can actually run:

===============  =========================================================
``choose``       ``fzf`` if this machine has one -- fuzzy, scrollable, and
                 the tool asked for. Otherwise a plain selector
                 that does not filter at all: questionary's arrow-key list
                 where prompt_toolkit works, else a numbered list over
                 ``input()``, which works anywhere.
``text``         questionary, else ``input()``.
``confirm``      questionary, else ``input()``.
===============  =========================================================

**Only fzf filters.** Filtering was tried in the other two backends and both
were worse than not having it. questionary's autocomplete copies the
highlighted row into the input buffer as you arrow through the menu, so the
query silently becomes a row you never typed -- and clearing it back out
leaves a fragment that matches nothing. A type-to-narrow loop over ``input()``
avoids that but costs a full redraw per query to save scrolling a list the
terminal already scrolls for free. A selector that only selects beats a filter
that surprises you, and ``fzf`` is one package away for anyone who wants the
fuzzy version.

Finding fzf is its own problem here, and ``shutil.which`` is not the answer:
see :func:`fzf_command`.

Every backend returns ``None`` for "the user cancelled", so callers handle
cancellation one way regardless of which one ran.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from functools import cache
from pathlib import Path

PAGE_SIZE = 20
"""Rows the numbered selector prints at a time. Enough to fill a terminal
without scrolling the prompt off the top."""


@cache
def prompt_toolkit_works() -> bool:
    """Can prompt_toolkit drive this terminal at all?

    Probed rather than inferred: the failure depends on the console handle
    behind stdout, which no combination of ``platform``/``isatty``/``TERM``
    describes reliably. Any exception means the same thing -- we cannot use
    it -- so the breadth of the ``except`` is the point, not an oversight.
    """
    try:
        from prompt_toolkit.output.defaults import create_output

        create_output()
    except Exception:
        return False
    return True


FZF_PROBE_TIMEOUT_SECONDS = 5


class _FzfFailed(Exception):
    """fzf could not run at all -- which is not "the user picked nothing"."""


@cache
def fzf_command() -> list[str] | None:
    """The argv prefix that runs fzf here, or ``None`` if nothing can.

    ``shutil.which`` is the whole answer everywhere except the environment
    this project actually runs in. Under cygwin the tool is *native-Windows*
    Python, so ``which`` searches with Windows rules -- and cygwin's ``fzf``
    package installs ``/usr/bin/fzf`` as a shebang script with no ``.exe``,
    which Windows can neither find nor execute. The symptom is precise and
    confusing: ``ls | fzf`` works in the shell, and ``new`` insists there is
    no fzf.

    So when the native lookup fails, ask cygwin's own shell whether it has one
    and, if it does, run fzf *through* that shell so the shebang is honoured.
    Returning an argv prefix rather than a path is what lets the two cases --
    a real ``fzf.exe`` and ``sh -c 'exec fzf ...'`` -- reach one call site.
    """
    native = shutil.which("fzf")
    if native is not None:
        return [native]
    return _fzf_via_cygwin_shell()


def _fzf_via_cygwin_shell() -> list[str] | None:
    sh = _cygwin_sh()
    if sh is None:
        return None
    try:
        found = subprocess.run(
            [sh, "-c", "command -v fzf"],
            capture_output=True,
            text=True,
            timeout=FZF_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if found.returncode != 0 or not found.stdout.strip():
        return None
    # `exec fzf "$@"` rather than pasting the arguments into the script text:
    # one of them is the prompt, which carries the question, and hand-quoting
    # that is how a shell injection gets written.
    return [sh, "-c", 'exec fzf "$@"', "fzf"]


def _cygwin_sh() -> str | None:
    """Cygwin's ``sh.exe``, found the way ``workspace/userpath.py`` finds
    ``cygpath``: cygwin hands a Windows child a translated PATH, so its
    ``/usr/bin`` is reachable as a Windows directory even though the POSIX
    spelling is not."""
    if os.name != "nt":
        return None
    cygpath = shutil.which("cygpath")
    if cygpath is None:
        return None
    sh = Path(cygpath).with_name("sh.exe")
    return str(sh) if sh.is_file() else None


def choose(message: str, rows: Sequence[str], *, marker_hint: str = "") -> str | None:
    """Pick one of ``rows``. ``None`` if the user cancelled.

    ``rows`` arrive in the order they should be offered and every backend
    preserves it -- that is what keeps the already-used-here garments at the
    top of the list.
    """
    listed = list(rows)
    if not listed:
        return None

    command = fzf_command()
    if command is not None:
        try:
            return _choose_with_fzf(command, message, listed)
        except _FzfFailed as exc:
            # An fzf that is present but cannot run -- no terminal to draw on,
            # most likely -- must not read as a cancelled prompt, or `new`
            # would exit silently with nothing on screen to explain it.
            print(f"  {exc}; falling back to a plain list")
    if prompt_toolkit_works():
        return _choose_with_questionary(message, listed, marker_hint)
    return _choose_with_input(message, listed, marker_hint)


def text(message: str, *, default: str = "") -> str | None:
    if prompt_toolkit_works():
        import questionary

        answer: str | None = questionary.text(message, default=default).ask()
        return answer
    suffix = f" [{default}]" if default else ""
    try:
        typed = input(f"{message}{suffix} ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return typed or default


def confirm(message: str, *, default: bool = False) -> bool | None:
    if prompt_toolkit_works():
        import questionary

        answer: bool | None = questionary.confirm(message, default=default).ask()
        return answer
    hint = "Y/n" if default else "y/N"
    try:
        typed = input(f"{message} [{hint}] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if not typed:
        return default
    return typed.startswith("y")


def _choose_with_fzf(command: list[str], message: str, rows: list[str]) -> str | None:
    """fzf reads its keys from ``/dev/tty``, which is why it works under a
    cygwin pty where prompt_toolkit cannot.

    fzf's own default ranking is left on: for an empty query it preserves the
    input order (so the marked rows stay on top), and once a query is typed it
    ranks by its own fuzzy score.

    Only two flags, and deliberately: cygwin's ``fzf`` package is 0.12.1, the
    Ruby implementation, which rejects ``--height`` outright ("illegal
    option") and takes the whole screen instead. Two flags every fzf since
    2015 accepts is worth more here than an inline list on the recent ones.

    stderr is left attached to the terminal rather than captured: fzf draws
    its UI there when it cannot open ``/dev/tty``, and swallowing that would
    turn a diagnosable failure into a blank screen.
    """
    try:
        result = subprocess.run(
            [*command, "--reverse", f"--prompt={message} > "],
            input="\n".join(rows),
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _FzfFailed(f"could not run fzf ({exc})") from exc
    if result.returncode in {1, 130}:  # 1 = no match, 130 = cancelled
        return None
    if result.returncode != 0:  # 2 = error, and anything else is one too
        raise _FzfFailed(f"fzf exited with status {result.returncode}")
    picked = result.stdout.strip("\n")
    return picked or None


def _choose_with_questionary(message: str, rows: list[str], marker_hint: str) -> str | None:
    """Arrow keys over the list, no filtering -- ``questionary.select``, not
    ``autocomplete``. See this module's docstring for why."""
    import questionary

    answer: str | None = questionary.select(
        message,
        choices=rows,
        instruction=marker_hint or None,
    ).ask()
    return answer


def _choose_with_input(message: str, rows: list[str], marker_hint: str) -> str | None:
    """A numbered list in plain ``input()``: one page at a time, ``n``/``p``
    to move between pages, a number to pick.

    The last resort, and the one that always works -- no console handle, no
    raw mode, no external binary. Numbers are absolute positions in the whole
    list rather than positions on the page, so a number means the same thing
    wherever it is typed.
    """
    pages = (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE
    paged = pages > 1
    hint = (
        "number to pick, n/p to page, blank to cancel"
        if paged
        else ("number to pick, blank to cancel")
    )
    page = 0
    while True:
        _print_page(rows, page, pages, marker_hint)
        try:
            typed = input(f"{message} ({hint}) ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None
        if not typed:
            return None
        if typed.isdigit():
            index = int(typed) - 1
            if 0 <= index < len(rows):
                return rows[index]
            print(f"  no option {typed}; pick 1-{len(rows)}")
        elif paged and typed in {"n", "p"}:
            page = (page + (1 if typed == "n" else -1)) % pages
        else:
            print(f"  {typed!r} is not {'a number or n/p' if paged else 'a number'}")


def _print_page(rows: list[str], page: int, pages: int, marker_hint: str) -> None:
    start = page * PAGE_SIZE
    print()
    if marker_hint:
        print(f"  {marker_hint}")
    for offset, row in enumerate(rows[start : start + PAGE_SIZE]):
        print(f"  {start + offset + 1:>3}  {row}")
    if pages > 1:
        print(f"       page {page + 1}/{pages} of {len(rows)} options")
