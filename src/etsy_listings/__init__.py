"""Automation that takes a print-on-demand t-shirt design to a reviewable Etsy draft.

Eight modules, dependencies pointing strictly downward (docs/architecture.md):

===============  ============================================================
``cli``          Typer commands; turning a ``Plan`` into terminal text.
``ui``           The calibrator's FastAPI API and its React front end.
``engine``       Stage pipeline, the three-way diff, the lockfile. The *only*
                 module that computes a diff (A2).
``newcmd``       The ``new`` picker: a catalog choice to a profile + listing.
``workspace``    Where every file lives, path safety, loading config (A8).
``render``       Pure passes and frozen config; ``template.yaml``'s models (A7).
``catalog``      Printify reference data: protocol, TTL cache, fake.
``config``       ``shop.yaml`` / profile / listing / pricing models, ``Money``.
===============  ============================================================

Plus :mod:`etsy_listings.terminal`, a standard-library-only leaf that answers
"can this stream print that character?" for anything that decorates output.

Each package's ``__init__`` states its own interface and what it deliberately
does not do. Nothing is re-exported here: importing the root would otherwise
drag in OpenCV, FastAPI and Typer to read a version number.
"""

from etsy_listings.__about__ import VERSION

__all__ = ["VERSION"]
