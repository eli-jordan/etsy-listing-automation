"""Shared test scaffolding: the things more than one layer was building for
itself, and building differently.

Two modules, one job each.

``builders``
    Constructors for the objects a behaviour test needs before it can say
    anything -- a :class:`Lockfile`, a :class:`RunContext`, an edited copy of
    the fixture workspace's listing. Four files defined ``_ctx``, three defined
    ``_lock``, and ``_plan``/``_apply`` existed twice with *different
    signatures*, so reading one behaviour test taught you nothing about the
    next.

``scripted``
    :class:`Scripted`, the prompt double that answers a wizard by matching on
    the question's text rather than its position. It began in the ``setup``
    tests; ``new``'s tests were driving the same kind of wizard with ordinal
    reply lists, where ``"2"`` meant a template only because of where it fell
    in a directory listing.

Withheld deliberately: no builder for ``tests/unit/test_lock.py``. That file
tests :class:`Lockfile` itself, and a unit test of a type should construct it
directly -- routing it through a builder would mean the thing under test and
the thing building it move together.
"""
