"""The base class for "this is a message for the user, not a bug".

A stdlib-only leaf, like :mod:`etsy_listings.terminal`, because everything
from ``config`` to ``catalog`` to the stages needs to raise one and none of
them should depend on each other to do it.

The distinction it draws is the one the CLI needs to make and could not:
:class:`UserFacingError` means the run stopped for a reason the user can act
on -- a design that is too small, a colour that does not exist, copy still
carrying a sentinel -- and its message is the whole of what should reach the
terminal. Anything else is a defect, and a defect should print a traceback,
because that is what a traceback is for.

Without this, ``plan`` printed a stack for `etsy.title is still <generate>`
and, worse, let it kill a ``--all`` batch that PRD 16 requires to carry on.
"""

from __future__ import annotations


class UserFacingError(Exception):
    """An error whose message is the entire useful output."""


INTERNAL_ERROR_MESSAGE = "Internal error, see the server log"
"""What reaches a client in place of a defect's own message (A33, decision 7).

A :class:`UserFacingError`'s message is the whole of what should reach a
reader; anything else is a defect, and a defect's own text can carry
whatever an internal exception happens to say -- a connection string, a
stack frame's local, a secret interpolated into an f-string. One constant so
every place that turns "not a UserFacingError" into a client-visible message
says the same thing, rather than each guessing its own wording."""
