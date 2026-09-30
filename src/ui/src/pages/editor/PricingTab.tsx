import { useEffect, useState } from "react";
import { listPricingPlans } from "../../api/listings";
import type { ListingDetail, PricingPlanSummary } from "../../types";

/** Plan picker and per-size prices (phase 5).
 *
 * The same controls Listing Details used to hold. A plan is selectable
 * (`GET /api/pricing-plans`, already built for the "+ New listing" flow) and
 * each resolved size carries an editable price, written as a per-size
 * override into `Listing.prices` -- `resolved_price()` already prefers that
 * over the plan, so no new resolution rule is needed. */

/** A `"<amount> <CURRENCY>"` string (a `PriceField`'s wire form), split for
 * an editable amount plus a fixed currency suffix -- the currency itself is
 * the workspace's, not something this field lets you change per size. */
function splitAmount(raw: string): { amount: string; currency: string } {
  const [amount, currency] = raw.split(" ");
  return { amount: amount ?? "", currency: currency ?? "" };
}

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
  onFlush: () => void;
}

export function PricingTab({ detail, onUpdate, onFlush }: Props) {
  const [plans, setPlans] = useState<PricingPlanSummary[]>([]);

  useEffect(() => {
    listPricingPlans(detail.garment_profile)
      .then(setPlans)
      .catch(() => setPlans([]));
  }, [detail.garment_profile]);

  return (
    <div className="pricing-tab">
      <fieldset>
        <legend>Pricing</legend>

        <div className="field">
          <label htmlFor="details-pricing-plan">Plan</label>
          <select
            id="details-pricing-plan"
            className="input"
            value={detail.pricing_plan ?? ""}
            onChange={(event) => {
              onUpdate({ pricing_plan: event.target.value || null });
              onFlush();
            }}
          >
            {detail.pricing_plan === null && <option value="">No plan selected</option>}
            {detail.pricing_plan !== null && !plans.some((p) => p.ref === detail.pricing_plan) && (
              <option value={detail.pricing_plan}>
                {detail.pricing_plan_name ?? detail.pricing_plan}
              </option>
            )}
            {plans.map((plan) => (
              <option key={plan.ref} value={plan.ref}>
                {plan.name}
                {/* Only worth saying against a garment that was actually
                    chosen: with none, nothing *is* different. */}
                {plan.compatible || detail.garment_profile === "" ? "" : " (different garment)"}
              </option>
            ))}
          </select>
        </div>

        {detail.resolved_prices.length > 0 ? (
          <div className="price-table">
            {detail.resolved_prices.map((price) => {
              const override = detail.prices[price.size];
              const { amount, currency } = splitAmount(override ?? price.amount);
              return (
                <div key={price.size} className="price-table__cell">
                  <span className="price-table__size">{price.size}</span>
                  <input
                    className="input price-table__input"
                    type="number"
                    step="0.01"
                    aria-label={`Price for size ${price.size}`}
                    value={amount}
                    onChange={(event) =>
                      onUpdate({
                        prices: {
                          ...detail.prices,
                          [price.size]: `${event.target.value} ${currency}`,
                        },
                      })
                    }
                    onBlur={onFlush}
                  />
                  <span className="price-table__currency">{currency}</span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-muted">No resolved prices.</p>
        )}
      </fieldset>
    </div>
  );
}
