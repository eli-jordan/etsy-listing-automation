"""The base class for "this is a message for the user, not a bug".

A stdlib-only leaf, because everything
from ``config`` to ``catalog`` to the stages needs to raise one and none of
them should depend on each other to do it.

The distinction it draws is the one the CLI needs to make and could not:
:class:`UserFacingError` means the run stopped for a reason the user can act
on -- a design that is too small, a colour that does not exist, copy still
carrying a sentinel -- and its message is the whole of what should reach the
terminal. Anything else is a defect, and a defect should print a traceback,
because that is what a traceback is for.

Without this, ``plan`` printed a stack for `etsy.title is still <generate>`
and, worse, let it kill a ``--all`` batch that continue-on-error requires to carry on.
"""

from __future__ import annotations


class UserFacingError(Exception):
    """An error whose message is the entire useful output."""


INTERNAL_ERROR_MESSAGE = "Internal error, see the server log"
"""What reaches a client in place of a defect's own message (ADR-0041, decision 7).

A :class:`UserFacingError`'s message is the whole of what should reach a
reader; anything else is a defect, and a defect's own text can carry
whatever an internal exception happens to say -- a connection string, a
stack frame's local, a secret interpolated into an f-string. One constant so
every place that turns "not a UserFacingError" into a client-visible message
says the same thing, rather than each guessing its own wording."""


# ---------------------------------------------------------------- refusals
#
# What kind of "no" a refusal is, so that each adapter decides once what each
# kind becomes -- the HTTP app has one table of category to status
# (``server/api/app.py``), and no route reads a message to decide. Core names
# categories, never status codes (ADR-0052). A refusal inherits exactly one,
# including one an adapter answers with its own body (an AI run's reason, a
# staging refusal's remedy), so its status still agrees with its category.
# ``workspace.InvalidNameError`` stays its own refusal: a name that is not a
# path segment is a security boundary (ADR-0013), not a user message.


class MissingError(UserFacingError, LookupError):
    """What the request names is not there: never was, or something removed
    or moved it first."""


class ConflictError(UserFacingError):
    """The request is well formed, but what the workspace holds now forbids
    it: a name already taken, a row with nothing to retry, a template that
    must be prepared first."""


class StaleError(UserFacingError):
    """The request was made against a revision of something that has since
    changed; the caller reloads and asks again. Nothing was written."""


class RefusedError(UserFacingError, ValueError):
    """The request's own content cannot be taken, whatever the workspace
    holds: a file that is not an image, a kind the photos cannot be, mask
    strokes outside the photo."""
