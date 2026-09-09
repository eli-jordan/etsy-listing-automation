"""Backs the ``auth`` CLI command (PRD 14, 49): every credential this tool
needs, each verified against its own API before it is stored.

Named ``authcmd`` for the same reason ``setupcmd`` and ``newcmd`` are not
``setup`` and ``new`` -- and here with a second reason, since ``auth`` would
sit one import away from the ``.auth/`` directory it writes into.

Split the same two ways: :mod:`logic` answers questions about credentials that
already exist (which are missing, how long the Etsy consent has left) and is
tested with no terminal at all; :mod:`interactive` sequences the questions and
does the I/O, with every external effect -- browser included -- arriving
through one injectable :class:`~interactive.Backends`.

The division of labour with ``setup`` is PRD 49: **credentials here, ids
there**, and this command runs first because every id ``setup`` discovers
needs a credential to discover it with.

:func:`run_auth` is the whole interface.
"""

from etsy_listings.authcmd.interactive import Backends, run_auth

__all__ = ["Backends", "run_auth"]
