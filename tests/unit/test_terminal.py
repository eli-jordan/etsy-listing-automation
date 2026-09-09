"""What a terminal can print, and what it says about itself.

A stdlib-only leaf's tests, matching the module (``etsy_listings.terminal``):
no workspace, no client, no prompt backend. They lived in the ``new`` picker's
behaviour file because the marker glyph is what the picker prints, which put
an encoding question in a file about a wizard.
"""

from __future__ import annotations

import pytest

from etsy_listings import terminal
from etsy_listings.newcmd.logic import LOCAL_MARKER, LOCAL_MARKER_FALLBACK

# --- the marker glyph


def test_the_marker_falls_back_to_ascii_on_a_terminal_that_cannot_print_it() -> None:
    assert terminal.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK, stream=_Stream("cp1252")) == (
        LOCAL_MARKER_FALLBACK
    )
    assert terminal.choose(LOCAL_MARKER, LOCAL_MARKER_FALLBACK, stream=_Stream("utf-8")) == (
        LOCAL_MARKER
    )


def test_both_marker_forms_occupy_the_same_width() -> None:
    """The emoji is East Asian Wide, so it is two terminal columns -- matching
    the two-character ASCII fallback keeps the brand column aligned either
    way."""
    assert len(LOCAL_MARKER_FALLBACK) == 2
    assert len(LOCAL_MARKER) == 1


def test_an_unknown_encoding_is_treated_as_unable_to_print() -> None:
    assert terminal.encodable("x", stream=_Stream("not-a-real-codec")) is False


# --- believing the shell about its encoding ----------------------------------
#
# Why the marker was showing as `* ` on a terminal that renders ⭐ perfectly:
# native-Windows Python takes its output encoding from the console codepage
# (cp1252), and a cygwin pty is a named pipe with no console behind it, so
# that answer describes nothing. mintty is UTF-8 and says so in LANG.


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"LANG": "en_GB.UTF-8"}, True),
        ({"LANG": "en_GB.utf8"}, True),
        ({"LANG": "C"}, False),
        ({}, False),
        # LC_ALL outranks LC_CTYPE outranks LANG, and the first one that is
        # set decides outright rather than falling through to the next.
        ({"LC_ALL": "C", "LANG": "en_GB.UTF-8"}, False),
        ({"LC_CTYPE": "en_GB.UTF-8", "LANG": "C"}, True),
        ({"LC_ALL": "", "LANG": "en_GB.UTF-8"}, True),
    ],
)
def test_declared_utf8_reads_the_locale_the_shell_set(environ, expected: bool) -> None:
    assert terminal.declared_utf8(environ) is expected


def test_a_utf8_locale_re_encodes_the_output_streams(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(terminal.sys, "stdout", _Reconfigurable(seen))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(seen))

    terminal.adopt_declared_encoding({"LANG": "en_GB.UTF-8"})

    assert seen == ["utf-8", "utf-8"]


def test_a_non_utf8_locale_leaves_the_streams_alone(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(terminal.sys, "stdout", _Reconfigurable(seen))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(seen))

    terminal.adopt_declared_encoding({"LANG": "C"})

    assert seen == []


def test_an_explicit_pythonioencoding_wins(monkeypatch) -> None:
    """Someone naming an encoding on purpose is exactly what this must not
    second-guess."""
    seen: list[str] = []
    monkeypatch.setattr(terminal.sys, "stdout", _Reconfigurable(seen))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(seen))

    terminal.adopt_declared_encoding({"LANG": "en_GB.UTF-8", "PYTHONIOENCODING": "cp1252"})

    assert seen == []


def test_a_stream_that_cannot_be_reconfigured_is_skipped(monkeypatch) -> None:
    """pytest's own capture, a StringIO, a pipe wrapper: no `reconfigure`, and
    a decoration is never worth an AttributeError over."""
    seen: list[str] = []
    monkeypatch.setattr(terminal.sys, "stdout", _Stream("cp1252"))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(seen))

    terminal.adopt_declared_encoding({"LANG": "en_GB.UTF-8"})

    assert seen == ["utf-8"]


def test_a_stream_that_refuses_to_be_reconfigured_is_survived(monkeypatch) -> None:
    monkeypatch.setattr(terminal.sys, "stdout", _Reconfigurable(None))
    monkeypatch.setattr(terminal.sys, "stderr", _Reconfigurable(None))
    terminal.adopt_declared_encoding({"LANG": "en_GB.UTF-8"})  # does not raise


class _Stream:
    def __init__(self, encoding: str) -> None:
        self.encoding = encoding


class _Reconfigurable:
    """A stdout stand-in. ``seen is None`` means reconfiguring fails, which is
    what a stream wrapping a closed handle does."""

    encoding = "cp1252"

    def __init__(self, seen: list[str] | None) -> None:
        self._seen = seen

    def reconfigure(self, *, encoding: str) -> None:
        if self._seen is None:
            raise ValueError("cannot reconfigure")
        self._seen.append(encoding)
