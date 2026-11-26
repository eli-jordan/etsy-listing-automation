"""Terminal decorations that need an ASCII fallback.

A redirected stdout on Windows is cp1252 and a cygwin console can report an
encoding with no block or emoji, so printing one raises ``UnicodeEncodeError``
unless :func:`choose` is asked first."""

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
    env = os.environ if environ is None else environ
    for var in LOCALE_VARS:
        value = env.get(var)
        if value:
            return _UTF8_LOCALE.search(value) is not None
    return False


def adopt_declared_encoding(environ: Mapping[str, str] | None = None) -> None:
    """Re-encode stdout and stderr as UTF-8 when the shell declared UTF-8 and Python chose
    otherwise.

    Native-Windows Python takes the console codepage (cp1252), but a cygwin pty is a named
    pipe with no console, and mintty declares UTF-8 in ``LANG``. An explicit
    ``PYTHONIOENCODING`` wins."""
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
    """POSIX reports a write to a stdout pipe nobody reads as ``BrokenPipeError``; native-Windows
    Python as ``EINVAL``, which Click misses, so ``EINVAL`` counts only when stdout is a pipe."""
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
    target = sys.stdout if stream is None else stream
    encoding = getattr(target, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def choose(preferred: str, fallback: str, *, stream: TextIO | None = None) -> str:
    return preferred if encodable(preferred, stream=stream) else fallback
