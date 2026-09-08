"""Stand-ins for the two things a prompt reaches outside the process for.

Both were being written inline, per test, slightly differently each time:
twelve hand-rolled ``def fake_run(args, **kwargs)`` closures over a ``seen``
dict, and half a dozen ``input()`` replacements over a list of answers. The
variation was never the point of any of those tests.

Distinct from :mod:`tests.support.scripted`, which replaces
:mod:`etsy_listings.prompts`' three entry points to drive a *wizard*. These
replace what those entry points call, to test the prompts themselves -- which
backend runs, and how it behaves when the backend misbehaves.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeRun:
    """A ``subprocess.run`` that answers the same way every time and remembers
    how it was called.

    ``error`` is for the case a returncode cannot express: an ``fzf`` that
    cannot be launched at all, which must not read as a cancelled prompt.
    """

    returncode: int = 0
    stdout: str = ""
    error: Exception | None = None
    calls: list[tuple[list[str], dict[str, Any]]] = field(default_factory=list)

    def __call__(self, args: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(args), kwargs))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(list(args), self.returncode, stdout=self.stdout)

    @property
    def args(self) -> list[str]:
        """The argv of the most recent call."""
        return self.calls[-1][0]

    @property
    def stdin(self) -> str:
        """What was piped to the most recent call."""
        return str(self.calls[-1][1].get("input", ""))


def replies(answers: list[str]):  # noqa: ANN201 - a bare `input` stand-in
    """An ``input()`` that answers ``answers`` in order.

    Deliberately raises ``IndexError`` once they run out rather than looping or
    returning "": a prompt asking one more question than the test scripted is a
    thing the test should be told about, not something to paper over.
    """
    queue = list(answers)

    def reply(_: str = "") -> str:
        return queue.pop(0)

    return reply
