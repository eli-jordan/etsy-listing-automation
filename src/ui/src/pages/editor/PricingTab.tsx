import { useEffect, useState } from "react";
import { listPricingPlans } from "../../api/listings";
import { useIsPhone } from "../../phone/usePhone";
import type { ListingDetail, PricingPlanSummary } from "../../types";

/** A `PriceField`'s `"<amount> <CURRENCY>"`, split into an editable amount and
 * the workspace's currency, which this field does not change. */
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
  const phone = useIsPhone();

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
                    {...(phone ? { inputMode: "decimal" as const } : {})}
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
