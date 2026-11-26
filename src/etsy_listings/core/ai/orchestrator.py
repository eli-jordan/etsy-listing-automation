"""The captured provider chain (ADR-0056), one same-provider output repair, and the
run's step and run budgets (ADR-0057).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from etsy_listings.core.ai.brief import (
    BriefRequest,
    DesignBrief,
    build_brief_task,
    validate_brief,
)
from etsy_listings.core.ai.errors import (
    OutputValidationError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    SeoAllProvidersUnavailableError,
    SeoDeadlineExceededError,
    SeoTryAgainError,
)
from etsy_listings.core.ai.market_queries import (
    MarketQueries,
    MarketQueriesRequest,
    build_market_queries_task,
    validate_market_queries,
)
from etsy_listings.core.ai.models import (
    Deadline,
    ProviderTask,
    RawProviderResult,
    RepairContext,
    RunBudget,
    SeoProposal,
    SeoRequest,
)
from etsy_listings.core.ai.prompt import build_seo_task
from etsy_listings.core.ai.providers import AiProvider
from etsy_listings.core.ai.validation import validate_proposal


def _decoded(raw_output: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise OutputValidationError(f"response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise OutputValidationError("response: expected a JSON object") from None
    return parsed


def _seo_decoder(raw_output: str) -> SeoProposal:
    return validate_proposal(_decoded(raw_output))


def _brief_decoder(raw_output: str) -> DesignBrief:
    return validate_brief(dict(_decoded(raw_output)))


def _market_queries_decoder(raw_output: str) -> MarketQueries:
    return validate_market_queries(dict(_decoded(raw_output)))


def _out_of_time(provider_name: str, budget: RunBudget, what: str) -> SeoDeadlineExceededError:
    """Name the limit that ran out in the seller's configured minutes (ADR-0057)."""
    if budget.deadline.expired:
        limit = f"{budget.limits.run_minutes}-minute run limit"
    else:
        limit = f"{budget.limits.step_minutes}-minute step limit"
    return SeoDeadlineExceededError(f"{provider_name}: {what} the {limit}")


@dataclass(frozen=True)
class _Run[Result]:
    """One task's inputs, shared by every provider that :func:`run_task` tries."""

    task: ProviderTask
    decode: Callable[[str], Result]
    budget: RunBudget
    cancel_event: threading.Event | None

    def resolve(self, provider: AiProvider, raw: RawProviderResult, step: Deadline) -> Result:
        """``raw`` decoded, or decoded after one same-provider repair within ``step``."""
        try:
            return self.decode(raw.raw_output)
        except OutputValidationError as first_error:
            if step.expired:
                raise _out_of_time(
                    raw.provider, self.budget, "no time was left for a repair within"
                ) from first_error

            try:
                # ADR-0057: the repair spends what is left of the same step.
                repaired = provider.generate(
                    self.task,
                    step,
                    repair=RepairContext(
                        prior_raw_output=raw.raw_output, reasons=first_error.reasons
                    ),
                    cancel_event=self.cancel_event,
                )
            except ProviderTimeoutError as timed_out:
                raise _out_of_time(
                    raw.provider, self.budget, "the repair did not finish within"
                ) from timed_out
            except ProviderUnavailableError as repair_error:
                raise SeoTryAgainError(
                    f"{raw.provider} became unavailable during its repair attempt: {repair_error}"
                ) from repair_error

            try:
                return self.decode(repaired.raw_output)
            except OutputValidationError as second_error:
                raise SeoTryAgainError(
                    f"{raw.provider}: the repaired response was still invalid: {second_error}"
                ) from second_error


def run_task[Result](
    task: ProviderTask,
    decode: Callable[[str], Result],
    providers: Sequence[AiProvider],
    *,
    budget: RunBudget | None = None,
    cancel_event: threading.Event | None = None,
) -> Result:
    if budget is None:
        budget = RunBudget.starting_now()
    run = _Run(task, decode, budget, cancel_event)

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
        return run.resolve(provider, raw, step)

    raise SeoAllProvidersUnavailableError(unavailable_reasons)


def generate_proposal(
    request: SeoRequest,
    seller_prompt: str,
    providers: Sequence[AiProvider],
    *,
    budget: RunBudget | None = None,
    cancel_event: threading.Event | None = None,
) -> SeoProposal:
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
    """Never cached: a second request is free to try different queries."""
    return run_task(
        build_market_queries_task(seller_prompt, request),
        _market_queries_decoder,
        providers,
        budget=budget,
        cancel_event=cancel_event,
    )
