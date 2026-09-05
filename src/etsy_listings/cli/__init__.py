"""The Typer command line: the human-facing entry point.

Owns turning a :class:`~etsy_listings.engine.change.Plan` into terminal text
and nothing else. It never compares state -- that is ``engine``'s job, and
keeping presentation on this side is what lets the CLI and the UI enforce
identical rules (A2, PRD 20). In particular nothing in ``cli.render`` may stat
a file: an output is shown as missing because the stage observed it missing.

:func:`main` is the ``etsy-listings`` console script. It does one thing before
handing over to Typer: re-encode stdout for the terminal it was actually given
(see :mod:`etsy_listings.terminal`), which is why tests drive the Typer
application directly through ``CliRunner`` instead -- a test must not have its
captured streams reconfigured underneath it.

That application object is deliberately **not** re-exported here. It is named
``app`` inside :mod:`etsy_listings.cli.app`, so exporting it would shadow the
submodule of the same name and make ``from etsy_listings.cli import app``
mean different things depending on import order. Reach for it as
``etsy_listings.cli.app.app``.
"""

from etsy_listings.cli.app import main
from etsy_listings.cli.render import format_plan

__all__ = ["main", "format_plan"]
