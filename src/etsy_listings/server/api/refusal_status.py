"""How a core refusal category (``core/errors.py``) surfaces over HTTP."""

from __future__ import annotations

from collections.abc import Mapping

from etsy_listings.core.errors import ConflictError, MissingError, RefusedError, StaleError
from etsy_listings.core.workspace.workspace import InvalidNameError

REFUSAL_STATUS: Mapping[type[Exception], int] = {
    InvalidNameError: 400,
    MissingError: 404,
    ConflictError: 409,
    StaleError: 412,
    RefusedError: 422,
}
"""Each refusal category (``core/errors.py``) as the status it surfaces as.

The one place a core refusal becomes a status code, so a route only lets it
through. Core declares the category and never a code (ADR-0052).

* ``400``: a name from a URL or a body that the server will not take as a name
  -- not a single path segment (ADR-0013 makes that a security boundary, so
  the refusal belongs to ``Workspace``), or reserved.
* ``404``: what the request names is not there.
* ``409``: the request is fine, but what the workspace holds now forbids it.
* ``412``: the request was made against a revision that has since changed;
  reload and ask again.
* ``422``: the request's own content cannot be taken.

The detail is the refusal's message: a ``UserFacingError``'s message is the
whole of what should reach a reader. A route whose refusal carries more than a
sentence -- a staging refusal's remedy, an AI run's reason, the Admin page's
field errors -- still answers it itself, with :func:`refusal_status`.
Starlette picks a handler by walking the exception's MRO, so a class answers as
the first category among its bases."""


def refusal_status(refusal: Exception) -> int:
    """The status a route answering ``refusal`` itself gives it, found the way
    Starlette finds a handler."""
    for category in type(refusal).__mro__:
        if category in REFUSAL_STATUS:
            return REFUSAL_STATUS[category]
    raise TypeError(f"{type(refusal).__name__} is not a refusal category")
