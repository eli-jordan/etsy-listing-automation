"""Terminal decorations that need an ASCII fallback.

A redirected stdout on Windows is cp1252, and a cygwin console can report an
encoding that represents neither a block nor an emoji. Printing one anyway
raises ``UnicodeEncodeError`` part-way through a run -- which is exactly how
``apply`` used to die after rendering its first scene. Anything that prints a
non-ASCII decoration asks here first, so there is one place that knows the
rule rather than a `try: encode` at every call site.

A CLI leaf: the ``apply`` swatches and the ``new`` picker's marker are
both terminal output, which only the CLI produces (ADR-0052). It depends on
nothing but the standard library, so any CLI module may depend on it.
"""

from __future__ import annotations

import errno
import os
import re
import stat
import sys
from collections.abc import Mapping
from typing import TextIO

_UTF8_LOCALE = re.compile(r"\.utf-?8$", re.IGNORECASE)

LOCALE_VARS = ("LC_ALL", "LC_CTYPE", "LANG")
"""POSIX precedence: the first one that is set and non-empty decides, and the
others are not consulted."""


def declared_utf8(environ: Mapping[str, str] | None = None) -> bool:
    """Has the shell said its terminal is UTF-8?"""
    env = os.environ if environ is None else environ
    for var in LOCALE_VARS:
        value = env.get(var)
        if value:
            return _UTF8_LOCALE.search(value) is not None
    return False


def adopt_declared_encoding(environ: Mapping[str, str] | None = None) -> None:
    """Re-encode stdout and stderr as UTF-8 when the shell declared UTF-8 and
    Python decided otherwise.

    Native-Windows Python picks its output encoding from the console
    codepage -- cp1252 on a Norwegian/UK Windows -- and a cygwin pty is a
    named pipe with no console behind it, so that answer describes nothing
    about the terminal actually rendering the output. mintty is UTF-8, and
    says so in ``LANG``. Trusting the shell's own declaration over a codepage
    it never set is what lets the ⭐ marker and the ``apply`` swatches print
    as themselves instead of degrading to ASCII on a terminal that would have
    shown them perfectly.

    ``PYTHONIOENCODING`` wins if it is set: that is someone stating an
    encoding on purpose, and guessing over an explicit choice is exactly the
    failure this function exists to undo.
    """
    env = os.environ if environ is None else environ
    if env.get("PYTHONIOENCODING") or not declared_utf8(env):
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # pytest's capture, a StringIO, a pipe wrapper
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            continue


def stdout_reader_gone(exc: OSError) -> bool:
    """Did ``exc`` come from writing to a stdout pipe nobody reads any more?

    ``etsy-listings auth etsy --help | head`` closes the pipe once ``head``
    has its lines. POSIX reports that as ``BrokenPipeError``; native-Windows
    Python reports a write to a closed pipe as ``EINVAL`` instead, which
    Click's own broken-pipe handling does not recognise. ``EINVAL`` counts
    only when stdout really is a pipe, so an unrelated invalid-argument error
    still surfaces.
    """
    if isinstance(exc, BrokenPipeError):
        return True
    return exc.errno == errno.EINVAL and sys.platform == "win32" and _stdout_is_pipe()


def _stdout_is_pipe() -> bool:
    try:
        return stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode)
    except (OSError, ValueError, AttributeError):  # closed, or not a real file
        return False


def discard_stdout() -> None:
    """Point the stdout file descriptor at the null device, so the flush
    Python makes at exit cannot fail a second time on the closed pipe."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.close(devnull)


def encodable(text: str, *, stream: TextIO | None = None) -> bool:
    """Can ``stream`` (default stdout) actually represent ``text``?

    ``LookupError`` is caught alongside the encoding failure: a stream can
    report an encoding name Python has no codec for, and a decoration is never
    worth raising over.
    """
    target = sys.stdout if stream is None else stream
    encoding = getattr(target, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def choose(preferred: str, fallback: str, *, stream: TextIO | None = None) -> str:
    """``preferred`` if the stream can print it, else ``fallback``.

    Callers pair these so both occupy the same number of terminal columns --
    an emoji is usually two, so its fallback is two ASCII characters, and a
    column of them stays aligned either way.
    """
    return preferred if encodable(preferred, stream=stream) else fallback
