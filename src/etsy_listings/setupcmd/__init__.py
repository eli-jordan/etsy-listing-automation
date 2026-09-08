"""Backs the ``setup`` CLI command (PRD 43): an empty directory in, a
workspace ``new`` can run in out.

Named ``setupcmd`` for the same reason ``newcmd`` is not ``new`` -- ``setup``
is a word with too much history in a Python package tree to make a good module
name.

Split the same two ways: :mod:`logic` decides (which directories are missing,
what ``shop.yaml`` should say, how to set a key in ``.env`` without disturbing
the rest) and is tested with no terminal at all; :mod:`interactive` only
sequences the questions and does the I/O.

The one rule that shapes both halves: **`setup` fills gaps, it does not
correct answers.** Re-running it on a configured workspace must be safe, so an
existing value always wins over a freshly collected one, and the ids Phase 3
fills in are never dropped.

:func:`run_setup` is the whole interface.
"""

from etsy_listings.setupcmd.interactive import run_setup

__all__ = ["run_setup"]
