import { useEffect, useState } from "react";
import { listEtsySections, listPricingPlans } from "../../api/listings";
import type { EtsySectionSummary, ListingDetail, PricingPlanSummary } from "../../types";

/** Title/tags/description/section/pricing (phase 5).
 *
 * Section is a dropdown of the live shop's sections (`GET /api/etsy/sections`,
 * `EtsyShopClient.shop_sections` -- unscoped, needs only the workspace's app
 * key pair) when that list is available, falling back to the original free
 * text field for a workspace that hasn't configured a shop id or Etsy
 * credentials yet -- an ordinary state short of `setup`/`auth etsy`, not an
 * error.
 *
 * Pricing plan is selectable (`GET /api/pricing-plans`, already built for the
 * "+ New listing" flow) and each resolved size carries an editable price,
 * written as a per-size override into `Listing.prices` -- `resolved_price()`
 * already prefers that over the plan, so no new resolution rule is needed. */

/** A `"<amount> <CURRENCY>"` string (a `PriceField`'s wire form), split for
 * an editable amount plus a fixed currency suffix -- the currency itself is
 * the workspace's, not something this field lets you change per size. */
function splitAmount(raw: string): { amount: string; currency: string } {
  const [amount, currency] = raw.split(" ");
  return { amount: amount ?? "", currency: currency ?? "" };
}

/** Etsy's own ceilings, mirrored from `config/listing.py`'s MAX_* constants.
 * Shown as counters rather than enforced here: the server is what refuses a
 * candidate (and says so through `field_errors`), and a field that silently
 * truncates what you paste is worse than one that tells you it is over. */
const MAX_TITLE_LENGTH = 140;
const MAX_TAGS = 13;

type EtsyDescription = ListingDetail["etsy"]["description"];

/** A one-line summary of the body source PR2's minimal control preserves but
 * does not yet let you change (that selector is PR6's). `ref`/`text` are
 * mutually exclusive on the server (`config/description.py`), so at most one
 * of these ever applies. */
function descriptionBodyHint(description: EtsyDescription): string {
  if (description.ref) return `Body: ${description.ref}`;
  if (description.text) return "Body: listing-specific text";
  return "No body set";
}

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
  onFlush: () => void;
}

export function DetailsTab({ detail, onUpdate, onFlush }: Props) {
  const [tagDraft, setTagDraft] = useState("");
  const [sections, setSections] = useState<EtsySectionSummary[]>([]);
  const [plans, setPlans] = useState<PricingPlanSummary[]>([]);
  const tags = detail.etsy.tags;
  const titleError = detail.field_errors["etsy.title"];
  const sectionError = detail.field_errors["etsy.section"];
  const title = detail.etsy.title;
  const materials = detail.garment_materials ?? [];

  useEffect(() => {
    listEtsySections().then(setSections);
  }, []);

  useEffect(() => {
    listPricingPlans(detail.garment_profile)
      .then(setPlans)
      .catch(() => setPlans([]));
  }, [detail.garment_profile]);

  function commitTags() {
    const additions = tagDraft
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t !== "" && !tags.includes(t));
    if (additions.length > 0) {
      onUpdate({ etsy: { tags: [...tags, ...additions] } });
    }
    setTagDraft("");
  }

  function removeTag(tag: string) {
    onUpdate({ etsy: { tags: tags.filter((t) => t !== tag) } });
  }

  return (
    <div className="details-tab">
      <fieldset>
        <legend>Listing details</legend>

        <div className={titleError ? "field field--invalid" : "field"}>
          <label htmlFor="details-title">Title</label>
          <input
            id="details-title"
            className="input"
            type="text"
            placeholder="The title shoppers see on Etsy"
            value={detail.etsy.title}
            onChange={(event) => onUpdate({ etsy: { title: event.target.value } })}
            onBlur={onFlush}
          />
          {titleError && <span className="field__error">{titleError}</span>}
          <span className="field__hint">
            {title.length} / {MAX_TITLE_LENGTH}
          </span>
        </div>

        <div className="field">
          <label htmlFor="details-tag-draft">Tags</label>
          <div className="chips">
            {tags.map((tag) => (
              <span key={tag} className="chip">
                {tag}
                <span className="chip__x" onClick={() => removeTag(tag)}>
                  ×
                </span>
              </span>
            ))}
            {tags.length === 0 && <span className="chips__empty">No tags yet</span>}
          </div>
          <input
            id="details-tag-draft"
            className="input tag-paste"
            type="text"
            placeholder="Type or paste tags, comma separated — press Enter to add"
            value={tagDraft}
            onChange={(event) => setTagDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitTags();
              }
            }}
            onBlur={commitTags}
          />
          <span className="field__hint">
            {tags.length} / {MAX_TAGS}
          </span>
        </div>

        <div className="field">
          <label htmlFor="details-description-lead">Description lead</label>
          <textarea
            id="details-description-lead"
            value={detail.etsy.description.lead}
            onChange={(event) =>
              onUpdate({
                etsy: { description: { ...detail.etsy.description, lead: event.target.value } },
              })
            }
            onBlur={onFlush}
          />
          {/* The full common-copy selector and inline-body editor are PR6's
              (docs/ai-seo-implementation-plan.md) -- this keeps the structured
              value intact through autosave and shows which body source, if
              any, is set, without letting this control silently drop it. */}
          <span className="field__hint">{descriptionBodyHint(detail.etsy.description)}</span>
        </div>

        <div className={sectionError ? "field field--invalid" : "field"}>
          <label htmlFor="details-section">Section</label>
          {sections.length > 0 ? (
            <select
              id="details-section"
              className="input"
              value={detail.etsy.section ?? ""}
              onChange={(event) => {
                onUpdate({ etsy: { section: event.target.value || null } });
                onFlush();
              }}
            >
              <option value="">No section</option>
              {sections.map((s) => (
                <option key={s.id} value={s.title}>
                  {s.title}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="details-section"
              className="input"
              type="text"
              value={detail.etsy.section ?? ""}
              onChange={(event) => onUpdate({ etsy: { section: event.target.value || null } })}
              onBlur={onFlush}
            />
          )}
          {sectionError && <span className="field__error">{sectionError}</span>}
        </div>

        {/* Materials belong to the chosen garment. The listing can show the
            Etsy-facing value but must not let one listing contradict its
            shared garment profile. */}
        <div className="field">
          <label htmlFor="details-materials">Materials</label>
          <input
            id="details-materials"
            className="input"
            type="text"
            value={materials.join(", ")}
            readOnly
          />
          <span className="field__hint">Set by the selected garment profile.</span>
        </div>
      </fieldset>

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
