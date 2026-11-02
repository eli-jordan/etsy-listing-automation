"""A stand-in for what a plain prompt reads: the user's typed lines.

Half a dozen ``input()`` replacements over a list of answers were being
written inline, per test, slightly differently each time. The variation was
never the point of any of those tests. Commands a prompt finds or runs (fzf,
cygwin's shell) are :mod:`tests.support.cli_host`'s ``ScriptedCliHost``.

Distinct from :mod:`tests.support.scripted`, which replaces
:mod:`etsy_listings.cli.prompts`' three entry points to drive a *wizard*. This
replaces what those entry points read, to test the prompts themselves.
"""

from __future__ import annotations


def replies(answers: list[str]):
    """An ``input()`` that answers ``answers`` in order.

    Deliberately raises ``IndexError`` once they run out rather than looping or
    returning "": a prompt asking one more question than the test scripted is a
    thing the test should be told about, not something to paper over.
    """
    queue = list(answers)

    def reply(_: str = "") -> str:
        return queue.pop(0)

    return reply
