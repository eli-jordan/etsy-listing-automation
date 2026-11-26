"""The Typer command line: turns a core ``Plan`` into terminal text and compares
no state itself.

The Typer application is ``etsy_listings.cli.app.app`` and is not re-exported:
exporting it would shadow the ``app`` submodule."""

from etsy_listings.cli.app import main
from etsy_listings.cli.render import format_plan

__all__ = ["format_plan", "main"]
