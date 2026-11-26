"""Automation that takes a print-on-demand t-shirt design to a reviewable Etsy draft.

Nothing is re-exported here, so importing the root to read the version loads no
OpenCV, FastAPI or Typer.
"""

from etsy_listings.__about__ import VERSION

__all__ = ["VERSION"]
