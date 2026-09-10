"""Backs the ``new`` CLI command (PRD 19): a catalog choice in, a garment
profile and a listing stub out.

Named ``newcmd`` rather than ``new`` -- purely to avoid a package that shadows
the common local variable name ``new`` everywhere else in the codebase; the
CLI command itself is still ``new``.

Split two ways, and the split is the point. ``logic`` is pure: every decision
`new` makes is a function of its inputs, testable through the fake catalog
client with no terminal at all. ``interactive`` only sequences the questions,
asking each one through :mod:`etsy_listings.prompts` -- which used to live
here, and moved to the package root when ``setup`` became the second command
that had to prompt.

:func:`run_new` is the whole interface; import ``newcmd.logic`` directly to
test a decision without prompting.
"""

from etsy_listings.newcmd.interactive import run_new

__all__ = ["run_new"]
