"""Application operations: the workflows the server and the CLI share, one
module per workflow (ADR-0052). An operation takes application inputs and its
dependencies, coordinates domain modules -- locks, read/merge/write, the
stores a change touches -- and answers with a domain result or a typed
refusal (``refusals``). It knows no HTTP status, request object or terminal,
and applies domain rules rather than restating them.

This package re-exports nothing: import each module directly, so a caller's
import names the module it depends on. The implementation-only modules sit
inside ``deploy`` and ``ai``, named in their initialisers and protected by
Import Linter so only their coordinator imports them.
"""
