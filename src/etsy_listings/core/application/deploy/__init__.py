"""Deployment runs: live plan/apply runs, in memory (ADR-0041, ADR-0042).

Runs in flight or recently finished, forgotten on restart; there is no
run-history recorder. The engine still computes every plan and fingerprint
and executes every stage (``engine/run.py``); this package queues runs,
drives the engine for them one at a time and records what it reports as a
replayable event log. Serving that log -- SSE framing, reconnect headers,
noticing a client went away -- is the server's (``server/api/runs.py``).

Import each module directly; this package re-exports nothing. Public
interfaces:

``registry``
    ``RunRegistry`` -- identity, conflicts, FIFO queueing, cancellation and
    retention; ``Run`` -- one run's phase and event log, with the blocking
    ``wait_for_events`` an SSE loop polls; the commands ``ListingPlan``,
    ``WorkspacePlan``, ``ListingApply``, ``WorkspaceApply`` (``RunCommand``);
    ``Conflict``.
``executor``
    ``RunExecutor`` -- the one FIFO worker thread; ``ContextFactory``.
``events``
    The ``RunEvent`` union, its phases and ``TERMINAL_PHASES``, and the
    ``Plan``/``StagePlan`` DTOs. Transport-independent pydantic models, so the
    same models are the wire payload rather than a second representation.
"""
