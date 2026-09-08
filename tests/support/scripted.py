"""A prompt double that answers a wizard by what it asked, not when it asked.

Both interactive commands are wizards, and a wizard's question *order* is
presentation: inserting a question, reordering two, or adding a row to the list
one of them offers changes nothing a user would call behaviour. A test that
encodes the order breaks on every such edit -- and, worse, sometimes does not:
an ordinal reply list shifted by one still runs, still writes a listing, and
still passes, having answered a different question than the test says it did.

So answers are keyed by a fragment of the question's text. ``"pricing plan
name"`` matches the prompt regardless of what precedes it, and a question with
no scripted answer is an error naming what was asked rather than an
``IndexError`` out of a spent queue.

The double replaces :mod:`etsy_listings.prompts`' three entry points, which is
the seam both wizards actually use. It does not replace ``input()``: which
*backend* asks a question is a separate concern with its own tests (a cygwin
pty cannot run prompt_toolkit, so the plain-input fallback has to keep
working), and mixing the two means neither is tested clearly.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from etsy_listings import prompts

Answers = dict[str, Any]
"""Question fragment -> the answer. A ``list`` value is *successive* answers to
the same question, which is what a user does when a prompt rejects what they
typed and asks again; the last entry then repeats. ``None`` means the user
cancelled, which is a real answer and not "use the default"."""


class Scripted:
    """Scripted answers, plus a record of everything that was asked."""

    def __init__(self, answers: Answers) -> None:
        self.answers = answers
        self.asked: list[str] = []
        self.rows_offered: dict[str, list[str]] = {}
        """The choices each picker put on screen. What a wizard *offers* is
        behaviour -- that a garment already used here sorts to the top, that a
        plan whose sizes match is listed at all -- and it is invisible in the
        files the wizard finally writes."""
        self.defaults_offered: dict[str, str] = {}
        """What each text prompt arrived pre-filled with. A re-run keeps every
        value only if these carry what the file already says."""

    def _answer(self, message: str) -> Any:
        self.asked.append(message)
        matches = [f for f in self.answers if f.lower() in message.lower()]
        if not matches:
            raise AssertionError(f"no scripted answer for {message!r}; asked {self.asked}")
        # A fragment that *is* the whole question wins outright: `new` asks
        # "Garment", and also asks "black: light or dark garment?" -- the first
        # must not be able to swallow the second.
        exact = [f for f in matches if f.lower() == message.lower()]
        if exact:
            return self._value(exact[0])
        # Otherwise the longest fragment wins, so a specific key beats a
        # general one that is a substring of it: "Pricing plan name:" is
        # answered by `pricing plan name`, never by the `pricing plan` that
        # also matches.
        longest = max(len(f) for f in matches)
        best = [f for f in matches if len(f) == longest]
        if len(best) > 1:
            raise AssertionError(f"{message!r} matches several answers equally well: {best}")
        return self._value(best[0])

    def _value(self, fragment: str) -> Any:
        answer = self.answers[fragment]
        if isinstance(answer, list):
            # Successive answers; the last one repeats.
            return answer.pop(0) if len(answer) > 1 else answer[0]
        return answer

    def text(self, message: str, *, default: str = "") -> str | None:
        """``None`` is what a real prompt returns when the user cancels, so
        that is what it means here too -- not "fall back to the default"."""
        self.defaults_offered[message] = default
        answer = self._answer(message)
        return None if answer is None else str(answer)

    def confirm(self, message: str, *, default: bool = False) -> bool | None:
        answer = self._answer(message)
        return None if answer is None else bool(answer)

    def choose(self, message: str, rows: Sequence[str], *, marker_hint: str = "") -> str | None:
        listed = list(rows)
        self.rows_offered[message] = listed
        wanted = self._answer(message)
        if wanted is None:
            return None
        for row in listed:
            if str(wanted) in row:
                return row
        raise AssertionError(f"scripted answer {wanted!r} matches no row in {listed}")

    def rows_for(self, fragment: str) -> list[str]:
        """The rows offered by the one question matching ``fragment``."""
        matches = [m for m in self.rows_offered if fragment.lower() in m.lower()]
        if len(matches) != 1:
            raise AssertionError(
                f"{fragment!r} matches {len(matches)} of the questions asked: "
                f"{list(self.rows_offered)}"
            )
        return self.rows_offered[matches[0]]


def install(monkeypatch: pytest.MonkeyPatch, answers: Answers) -> Scripted:
    """Patch the three prompt entry points and hand back the recorder.

    Patched on :mod:`etsy_listings.prompts` itself rather than on each
    command's module: both wizards call it as a module attribute, so there is
    one object to replace and no way for a new caller to miss the double.
    """
    script = Scripted(answers)
    monkeypatch.setattr(prompts, "text", script.text)
    monkeypatch.setattr(prompts, "confirm", script.confirm)
    monkeypatch.setattr(prompts, "choose", script.choose)
    return script
