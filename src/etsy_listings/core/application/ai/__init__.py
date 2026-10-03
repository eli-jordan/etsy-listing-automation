"""AI work: brief, market research and proposal as one streamed, cancellable
run per listing, and the batch queue that drafts every created batch row
through the same runs (features/market-seo-20260924/spec.md, *AI runs*;
ADR-0048 through ADR-0050).

Runs live in memory and are forgotten on restart; each gets its own thread,
never the deployment worker. The queue's rows are its record, in the batch
cache. Everything here is process-local: nothing guards two servers on one
workspace, and CLI apply never touches the queue (ADR-0050). Serving a run's
events -- SSE framing, reconnect headers, noticing a client went away -- is
the server's (``server/api/airuns.py``).

Import each module directly; this package re-exports nothing. Public
interfaces:

``coordinator``
    ``AiCoordinator`` -- the one object a host constructs, starts and stops:
    ``start_run``, ``blocked``, ``yield_to_deploy``, and its ``registry`` and
    ``queue``.
``registry``
    ``AiRunRegistry`` -- one active run per listing, deploy holds; ``AiRun``
    -- a run's phase, steps, cancel event and replayable event log, with the
    blocking ``wait_for_events`` an SSE loop polls; ``Conflict``.
``runner``
    ``AiRunner`` -- the chain on a thread per run, its watchdog and shutdown;
    ``MarketClientFactory``, ``default_market_client``.
``batch_queue``
    ``BatchQueue`` -- the dispatcher: concurrency, round-robin across
    batches, interrupted-row recovery, the seller's controls, ``blocked``
    and the deploy handoff; ``queue_order``.
``readiness``
    ``unready_reason``, ``batch_blocked`` -> ``AiReadinessBlock``,
    ``default_ai_providers`` and the ``ProviderFactory`` seam.
``listing_proposals``
    ``read_proposal``, ``resolve_proposal``: the cached proposal judged and
    resolved (ADR-0049).
``events``
    The ``AnyAiRunEvent`` union and ``WorkflowStep``. Transport-independent
    pydantic models, so the same models are the wire payload rather than a
    second representation.
"""
