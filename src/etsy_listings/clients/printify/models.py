"""What Printify's shop-scoped endpoints return.

Every model is deliberately lenient about extra keys and strict about the ones
it names: Printify adds fields without warning, and a client that treats a new
one as a validation error breaks on a day nobody deployed anything.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Shop(BaseModel):
    """One row of ``GET /v1/shops.json`` -- which is the whole of what that
    endpoint knows. No currency, no settings, no draft preference
    (docs/api-findings.md).

    The call is scoped to the token, so its answer is also the answer to "which
    shops may this token write to?" -- which is what makes ``setup`` able to
    discover the shop id rather than asking a human to find one (PRD 42).
    """

    model_config = ConfigDict(frozen=True)

    id: int
    title: str
    sales_channel: str | None = None
    """``"etsy"`` once a shop is connected, ``"disconnected"`` before that.
    Optional because Printify omits keys rather than nulling them, and nothing
    here may assume a field is present."""

    @property
    def is_connected(self) -> bool:
        """Whether a publish could reach a sales channel at all.

        ``publish.json`` against a disconnected shop is
        ``400 code 8254``, so this is the difference between "Phase 3 will
        work here" and "Phase 3 cannot be tested here".
        """
        return self.sales_channel not in (None, "", "disconnected")
