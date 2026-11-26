"""``UserFacingError`` and the refusal categories: a stdlib-only leaf every layer raises from."""

from __future__ import annotations


class UserFacingError(Exception): ...


INTERNAL_ERROR_MESSAGE = "Internal error, see the server log"
"""What reaches a client in place of a defect's own message (ADR-0041, decision 7).

A :class:`UserFacingError`'s message is the whole of what should reach a
reader; anything else is a defect, and a defect's own text can carry
whatever an internal exception happens to say -- a connection string, a
stack frame's local, a secret interpolated into an f-string. One constant so
every place that turns "not a UserFacingError" into a client-visible message
says the same thing, rather than each guessing its own wording."""


class MissingError(UserFacingError, LookupError): ...


class ConflictError(UserFacingError): ...


class StaleError(UserFacingError): ...


class RefusedError(UserFacingError, ValueError): ...
