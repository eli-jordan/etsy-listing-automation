"""The captured provider chain (ADR-0056), one same-provider output repair, and the
run's step and run budgets (ADR-0057; AI SEO implementation plan, PR4, item 3;
the "Timeout and retries" and "Provider adapters" decisions).

This is the "orchestration service" the runtime design diagram and
`ai/providers.py`'s own docstring describe: it owns retry classification,
fallback order, the time budgets, and turning a provider's raw text into
a validated result -- none of that is an adapter's job.

Budgets (ADR-0057). A run hands every task one `RunBudget`. Each provider
tried gets a fresh step deadline from it, which its first attempt and its
one repair share; a step never outlasts the whole run. A provider that runs
out its step still ends the task as "Try again": only a recognised
availability failure moves on, and the next provider's allowance is then a
fresh one rather than whatever the previous provider left.

It is driven
entirely against the `AiProvider` protocol, so it works identically whether
handed `FakeAiProvider` doubles (every test in this module) or the real
`CodexProvider`/`ClaudeProvider` adapters.

Two entry points, one rule: `generate_proposal` for an SEO proposal and
`generate_brief` for a design brief. Both are thin wrappers over
:func:`run_task`, which knows about a `ProviderTask` and a function that
turns raw text into *something* -- and nothing about which of the two it is
serving. That is deliberate: the classification below is where this feature's
hardest-won behaviour lives, and a second copy of it for brief drafting is
exactly the kind of near-duplicate that drifts one fix at a time.

Classification summary (implementation plan, "Timeout and retries"):

- A :class:`~etsy_listings.core.ai.errors.ProviderUnavailableError` from the
  *first* call to a provider falls through to the next one in ``providers``.
- Any proposal-shape problem -- the raw text is not JSON, not an object, or
  fails `ai/validation.py.validate_proposal` -- counts as "malformed" and
  gets exactly one same-provider repair call, carrying every reason
  (`ai/models.py.RepairContext`). Nothing about *why* it was malformed
  changes that: a JSON decode failure and a hard-validation failure are
  repaired identically.
- Anything else -- the repaired response is still invalid, the repair call
  itself could not even reach the provider, an unrecognised process error,
  or a step or run deadline expiring -- surfaces as "Try again"
  ( :class:`~etsy_listings.core.ai.errors.SeoTryAgainError`). None of these retry
  a second provider; the settled plan only permits fallback on the first,
  recognised-unavailable failure.
- :class:`~etsy_listings.core.ai.errors.ProviderCancelledError` is never caught
  here -- it propagates as-is, since a cancelled request retains no result
  and is not a failure to report as "Try again".
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence

from etsy_listings.core.ai.brief import (
    BriefRequest,
    BriefValidationError,
    DesignBrief,
    build_brief_task,
    validate_brief,
)
from etsy_listings.core.ai.errors import (
    ProviderTimeoutError,
    ProviderUnavailableError,
    SeoAllProvidersUnavailableError,
    SeoDeadlineExceededError,
    SeoTryAgainError,
)
from etsy_listings.core.ai.market_queries import (
    MarketQueries,
    MarketQueriesRequest,
    MarketQueriesValidationError,
    build_market_queries_task,
    validate_market_queries,
)
from etsy_listings.core.ai.models import (
    Deadline,
    ProviderTask,
    RepairContext,
    RunBudget,
    SeoProposal,
    SeoRequest,
)
from etsy_listings.core.ai.prompt import build_seo_task
from etsy_listings.core.ai.providers import AiProvider
from etsy_listings.core.ai.validation import ProposalValidationError, validate_proposal


class _Malformed(Exception):
    """Internal-only: a provider's raw output could not become the result
    its task asked for, for any reason -- not valid JSON, not a JSON object,
    or a hard-validation failure. Never escapes this module; every case it
    covers is repaired identically, so nothing downstream needs to
    distinguish them."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons: tuple[str, ...] = tuple(reasons)
        super().__init__("; ".join(self.reasons))


def _decoded(raw_output: str) -> Mapping[str, object]:
    """The JSON-decoding half of every decoder, which is identical for both
    tasks -- only what happens to the decoded mapping differs."""
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise _Malformed((f"response was not valid JSON: {exc}",)) from exc
    if not isinstance(parsed, Mapping):
        raise _Malformed(("response: expected a JSON object",)) from None
    return parsed


def _seo_decoder(raw_output: str) -> SeoProposal:
    try:
        return validate_proposal(_decoded(raw_output))
    except ProposalValidationError as exc:
        raise _Malformed(exc.reasons) from exc


def _brief_decoder(raw_output: str) -> DesignBrief:
    try:
        return validate_brief(dict(_decoded(raw_output)))
    except BriefValidationError as exc:
        raise _Malformed(exc.reasons) from exc


def _market_queries_decoder(raw_output: str) -> MarketQueries:
    try:
        return validate_market_queries(dict(_decoded(raw_output)))
    except MarketQueriesValidationError as exc:
        raise _Malformed(exc.reasons) from exc


def _out_of_time(provider_name: str, budget: RunBudget, what: str) -> SeoDeadlineExceededError:
    """Name the limit that ran out, in the seller's configured minutes
    (ADR-0057). A step clipped by the run deadline ran out the run."""
    if budget.deadline.expired:
        limit = f"{budget.limits.run_minutes}-minute run limit"
    else:
        limit = f"{budget.limits.step_minutes}-minute step limit"
    return SeoDeadlineExceededError(f"{provider_name}: {what} the {limit}")


def _resolve[Result](
    provider: AiProvider,
    task: ProviderTask,
    decode: Callable[[str], Result],
    budget: RunBudget,
    step: Deadline,
    raw_output: str,
    provider_name: str,
    cancel_event: threading.Event | None,
) -> Result:
    try:
        return decode(raw_output)
    except _Malformed as first_error:
        if step.expired:
            raise _out_of_time(
                provider_name, budget, "no time was left for a repair within"
            ) from first_error

        try:
            # ADR-0057: the repair spends what is left of the same step.
            repaired = provider.generate(
                task,
                step,
                repair=RepairContext(prior_raw_output=raw_output, reasons=first_error.reasons),
                cancel_event=cancel_event,
            )
        except ProviderTimeoutError as timed_out:
            raise _out_of_time(
                provider_name, budget, "the repair did not finish within"
            ) from timed_out
        except ProviderUnavailableError as repair_error:
            raise SeoTryAgainError(
                f"{provider_name} became unavailable during its repair attempt: {repair_error}"
            ) from repair_error

        try:
            return decode(repaired.raw_output)
        except _Malformed as second_error:
            raise SeoTryAgainError(
                f"{provider_name}: the repaired response was still invalid: {second_error}"
            ) from second_error


def run_task[Result](
    task: ProviderTask,
    decode: Callable[[str], Result],
    providers: Sequence[AiProvider],
    *,
    budget: RunBudget | None = None,
    cancel_event: threading.Event | None = None,
) -> Result:
    """Try captured ``providers`` in their workspace order (ADR-0056) against
    ``task``, within ``budget`` (ADR-0057). Without one, the task is a run of
    its own under the default limits.

    Each provider gets a fresh step deadline from ``budget`` for its attempt
    and its one repair, clipped to what is left of the run. A run's later
    tasks pass the same ``budget``, so they start with what earlier tasks
    and market research left.

    ``decode`` takes raw provider text and returns a validated result,
    raising `_Malformed` for anything in between -- the only thing this
    function needs to know about a task beyond how to run it, and the reason
    the whole classification rule this module documents applies to both AI
    features without either one restating it. `generate_proposal` and
    `generate_brief` below are the two callers; both exist only to build the
    task and name the decoder, so neither can end up with its own idea of
    when a provider is retried.

    ``cancel_event`` is the one `threading.Event` the settled "Cancellation"
    decision describes: an AI run being cancelled, timing out or shut down
    (`core/application/ai/runner.py`) sets it, and this is the single
    place that forwards it to whichever provider is currently running -- both
    real adapters already pass it straight through to
    `ai/process.py.run_managed`, which is what actually kills the subprocess
    tree. Left `None`, generation is simply not cancellable, which is what
    every `FakeAiProvider` test wants.

    Raises `SeoAllProvidersUnavailableError` if every provider answered with
    a recognised availability failure,
    `SeoDeadlineExceededError`/`SeoTryAgainError` for everything the settled
    plan surfaces as "Try again", and lets a
    `~etsy_listings.core.ai.errors.ProviderCancelledError` propagate untouched.
    """
    if budget is None:
        budget = RunBudget.starting_now()

    unavailable_reasons: list[str] = []
    for provider in providers:
        if budget.deadline.expired:
            raise SeoDeadlineExceededError(
                f"the {budget.limits.run_minutes}-minute run limit was reached before "
                f"every configured provider could be tried"
            )
        step = budget.step()
        try:
            raw = provider.generate(task, step, cancel_event=cancel_event)
        except ProviderTimeoutError as exc:
            raise _out_of_time(exc.provider, budget, "did not finish within") from exc
        except ProviderUnavailableError as exc:
            unavailable_reasons.append(str(exc))
            continue
        return _resolve(
            provider, task, decode, budget, step, raw.raw_output, raw.provider, cancel_event
        )

    raise SeoAllProvidersUnavailableError(unavailable_reasons)


def generate_proposal(
    request: SeoRequest,
    seller_prompt: str,
    providers: Sequence[AiProvider],
    *,
    budget: RunBudget | None = None,
    cancel_event: threading.Event | None = None,
) -> SeoProposal:
    """One complete SEO proposal for ``request``, using the seller's own
    ``prompts/seo.md`` text.

    ``seller_prompt`` is the already-read file content, never a path and
    never a default this function falls back to -- the same rule
    `ai/prompt.py.build_task_prompt` states, held one layer up so that the
    endpoint which knows the file is missing is the one that says so.
    """
    return run_task(
        build_seo_task(seller_prompt, request),
        _seo_decoder,
        providers,
        budget=budget,
        cancel_event=cancel_event,
    )


def generate_brief(
    request: BriefRequest,
    seller_prompt: str,
    providers: Sequence[AiProvider],
    *,
    budget: RunBudget | None = None,
    cancel_event: threading.Event | None = None,
) -> DesignBrief:
    """One drafted listing brief for ``request``, using the seller's own
    ``prompts/brief.md`` text.

    Shares every rule above, including the run's step limit -- a brief is a
    much smaller ask than a proposal, but it is the same kind of ask, and
    giving it its own timeout would mean two numbers to keep in agreement for
    no behaviour anyone wanted.
    """
    return run_task(
        build_brief_task(seller_prompt, request),
        _brief_decoder,
        providers,
        budget=budget,
        cancel_event=cancel_event,
    )


def generate_market_queries(
    request: MarketQueriesRequest,
    seller_prompt: str,
    providers: Sequence[AiProvider],
    *,
    budget: RunBudget | None = None,
    cancel_event: threading.Event | None = None,
) -> MarketQueries:
    """Three buyer search queries for ``request``, using the seller's own
    ``prompts/market-queries.md`` text (features/market-seo-20260924/spec.md, *Query extraction*).

    The third task over the same captured chain (ADR-0056) on a
    recognised unavailable failure, one same-provider repair, and the run's
    step and run budgets (ADR-0057).
    Never cached -- a second request is free to try different queries.
    """
    return run_task(
        build_market_queries_task(seller_prompt, request),
        _market_queries_decoder,
        providers,
        budget=budget,
        cancel_event=cancel_event,
    )
