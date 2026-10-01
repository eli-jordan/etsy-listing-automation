"""Which pricing plans a workspace has, and which suit a garment.

Shared by both ways a listing is created: the listings editor's plan picker
(``GET /api/pricing-plans``) and the ``new`` wizard's. Both used to read this
from ``newcmd.logic``, which took the server through the wizard package and
its terminal prompts; here, one interpretation serves both and each adapter
renders the rows its own way (module-structure plan, PR 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.pricing_plan import PricingPlan
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class PricingPlanOption:
    """A loadable plan and whether it was built for the garment asked about."""

    path: Path
    plan: PricingPlan
    compatible: bool


def load_candidate_pricing_plans(workspace: Workspace) -> list[tuple[Path, PricingPlan]]:
    """Every discovered plan that actually loads. A plan that won't parse or
    fails currency validation is skipped, not fatal -- one broken file costs
    its own row, not the whole picker."""
    result: list[tuple[Path, PricingPlan]] = []
    for path in workspace.pricing_plan_files():
        try:
            result.append((path, workspace.load_pricing_plan(path)))
        except (ConfigLoadError, ValidationError):
            continue
    return result


def pricing_plan_options(
    plans: list[tuple[Path, PricingPlan]], garment_profile: str
) -> list[PricingPlanOption]:
    """``plans``, those declaring exactly this garment profile first, each
    group by file stem, case-insensitively.

    An *exact* ``plan.garment_profile == garment_profile`` match: a plan
    declares its garment directly, so nothing is inferred. An empty
    ``garment_profile`` -- a listing that has not chosen one yet -- therefore
    marks no plan that names a garment.
    """
    options = [
        PricingPlanOption(path=path, plan=plan, compatible=plan.garment_profile == garment_profile)
        for path, plan in plans
    ]
    options.sort(key=lambda option: (not option.compatible, option.path.stem.lower()))
    return options


def pricing_plan_ref(plan_path: Path, *, root: Path) -> str:
    """The write-side counterpart to :meth:`Workspace.resolve_ref` -- a
    workspace-rooted POSIX ref, e.g. ``'pricing-plans/tee-basic.yaml'``
    (ADR-0046). Needed because discovery under ``pricing-plans/`` allows
    nesting, so the ref can't be hardcoded the way ``designs/{name}.png``
    is."""
    return plan_path.resolve().relative_to(root.resolve()).as_posix()
