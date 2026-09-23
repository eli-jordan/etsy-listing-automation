import { useEffect, useRef, useState } from "react";
import { listCommonCopy, listEtsySections, listPricingPlans } from "../../api/listings";
import type {
  CommonCopySummary,
  EtsySectionSummary,
  ListingDetail,
  PricingPlanSummary,
} from "../../types";
import { AiChoiceDrawer } from "./aiSeo/AiChoiceDrawer";
import { AiSeoControl } from "./aiSeo/AiSeoControl";
import { AiTagsDrawer } from "./aiSeo/AiTagsDrawer";
import { useAiSeoMode } from "./aiSeo/useAiSeoMode";

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

/** The sentinel the body-source `<select>` uses for "write it here" --
 * distinct from every real value that field can hold, since a `ref` is
 * always a `common-copy/...` path (`Workspace.common_copy_file`). */
const INLINE_BODY = "inline";

/** `check_copy_is_concrete`/`check_description_ref`
 * (`config/listing_validation.py`) file every description issue -- the empty
 * lead that blocks deployment, and a `ref` that will not resolve -- under
 * this one `where`, matching `_COPY_WHERE["description"]` exactly. Both are
 * shown together beneath the description fields, the same block issues the
 * page-level banner surfaces, but visible without leaving the tab. */
const DESCRIPTION_ISSUE_WHERE = "Listing Details › Description";

/** The current body source as the `<select>` reads it: the stored `ref`, or
 * the inline sentinel when neither `ref` nor `text` is set (a fresh draft
 * defaults to writing it here, matching PR2's prior default). */
function bodySourceValue(description: EtsyDescription): string {
  return description.ref ?? INLINE_BODY;
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
  const [commonCopy, setCommonCopy] = useState<CommonCopySummary[]>([]);
  const aiSeo = useAiSeoMode(detail, onUpdate, onFlush);
  const aiModeButtonRef = useRef<HTMLButtonElement>(null);
  const titleDrawerRef = useRef<HTMLDivElement>(null);
  const hadAiSeoProposal = useRef(false);
  const tags = detail.etsy.tags;
  const titleError = detail.field_errors["etsy.title"];
  const sectionError = detail.field_errors["etsy.section"];
  const title = detail.etsy.title;
  const materials = detail.garment_materials ?? [];
  const description = detail.etsy.description;
  const descriptionIssues = detail.issues.filter((i) => i.where === DESCRIPTION_ISSUE_WHERE);
  const selectedCommonCopy = commonCopy.find((c) => c.ref === description.ref);

  useEffect(() => {
    listEtsySections().then(setSections);
  }, []);

  useEffect(() => {
    listPricingPlans(detail.garment_profile)
      .then(setPlans)
      .catch(() => setPlans([]));
  }, [detail.garment_profile]);

  useEffect(() => {
    listCommonCopy().then(setCommonCopy);
  }, []);

  // Accessibility (`docs/ui-listing-seo-interactions.md` section 10):
  // "Keyboard focus moves to the first useful control in the first opened
  // drawer after generation, and returns to a sensible field or AI Mode
  // control when the last drawer closes." Every drawer opens together right
  // after a successful `generate()` (a fresh proposal starts every field
  // unresolved), so the title drawer -- first in the field order -- is
  // always "the first opened drawer" at that moment; closing every drawer
  // (rejecting, choosing, or resolving each one) is exactly when `proposal`
  // goes back to `null`.
  useEffect(() => {
    const hasProposal = aiSeo.proposal !== null;
    if (hasProposal && !hadAiSeoProposal.current) {
      titleDrawerRef.current?.querySelector<HTMLButtonElement>(".seo-choice-list button")?.focus();
    } else if (!hasProposal && hadAiSeoProposal.current) {
      aiModeButtonRef.current?.focus();
    }
    hadAiSeoProposal.current = hasProposal;
  }, [aiSeo.proposal]);

  function setBodySource(source: string) {
    if (source === INLINE_BODY) {
      onUpdate({
        etsy: { description: { ...description, text: description.text ?? "", ref: null } },
      });
      return;
    }
    onUpdate({ etsy: { description: { ...description, text: null, ref: source } } });
  }

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
      <fieldset className="seo-details-fieldset">
        <legend>Listing details</legend>

        <AiSeoControl mode={aiSeo} buttonRef={aiModeButtonRef} />

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
          {aiSeo.proposal?.unresolved.title && (
            <div ref={titleDrawerRef}>
              <AiChoiceDrawer
                field="title"
                options={aiSeo.proposal.proposal.titles}
                stale={aiSeo.stale}
                rationale={aiSeo.proposal.proposal.rationale}
                warnings={aiSeo.proposal.proposal.warnings}
                observedText={aiSeo.proposal.proposal.observed_text}
                onChoose={aiSeo.chooseTitle}
                onReject={aiSeo.rejectTitle}
              />
            </div>
          )}
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
          {aiSeo.proposal?.unresolved.tags && (
            <AiTagsDrawer
              tags={aiSeo.proposal.proposal.tags}
              selected={tags}
              stale={aiSeo.stale}
              rationale={aiSeo.proposal.proposal.rationale}
              warnings={aiSeo.proposal.proposal.warnings}
              observedText={aiSeo.proposal.proposal.observed_text}
              onToggle={aiSeo.toggleTag}
              onAcceptBest={aiSeo.acceptBestTags}
              onClose={aiSeo.closeTags}
            />
          )}
        </div>

        <div className="field">
          <label htmlFor="details-description-lead">Description lead</label>
          <textarea
            id="details-description-lead"
            value={description.lead}
            onChange={(event) =>
              onUpdate({
                etsy: { description: { ...description, lead: event.target.value } },
              })
            }
            onBlur={onFlush}
          />
          {aiSeo.proposal?.unresolved.lead && (
            <AiChoiceDrawer
              field="description lead"
              options={aiSeo.proposal.proposal.description_leads}
              stale={aiSeo.stale}
              rationale={aiSeo.proposal.proposal.rationale}
              warnings={aiSeo.proposal.proposal.warnings}
              observedText={aiSeo.proposal.proposal.observed_text}
              onChoose={aiSeo.chooseLead}
              onReject={aiSeo.rejectLead}
            />
          )}
        </div>

        <div className={descriptionIssues.length > 0 ? "field field--invalid" : "field"}>
          <label htmlFor="details-description-source">Description body source</label>
          <select
            id="details-description-source"
            className="input"
            value={bodySourceValue(description)}
            onChange={(event) => {
              setBodySource(event.target.value);
              onFlush();
            }}
          >
            <option value={INLINE_BODY}>Write inline body</option>
            {commonCopy.map((file) => (
              <option key={file.ref} value={file.ref}>
                {file.title}
              </option>
            ))}
            {/* A stored ref this workspace's common-copy listing does not
                offer (removed, renamed, or broken) still has to appear
                selected -- otherwise the select would silently show
                "Write inline body" for a listing that has not actually
                changed source. `descriptionIssues` is what tells the seller
                why it will not resolve. */}
            {description.ref !== null && selectedCommonCopy === undefined && (
              <option value={description.ref}>{description.ref}</option>
            )}
          </select>

          {description.ref === null ? (
            <textarea
              id="details-description-text"
              aria-label="Description body"
              value={description.text ?? ""}
              onChange={(event) =>
                onUpdate({
                  etsy: { description: { ...description, text: event.target.value, ref: null } },
                })
              }
              onBlur={onFlush}
            />
          ) : (
            <div className="common-copy-meta">
              {selectedCommonCopy && (
                <p className="common-copy-meta__title">{selectedCommonCopy.title}</p>
              )}
              {selectedCommonCopy?.summary && (
                <p className="common-copy-meta__summary">{selectedCommonCopy.summary}</p>
              )}
              <p className="field__hint">{description.ref}</p>
            </div>
          )}

          {descriptionIssues.map((issue, index) => (
            <span key={index} className="field__error">
              {issue.message}
            </span>
          ))}
        </div>

        <div className="field">
          <label htmlFor="details-description-preview">Description preview</label>
          {/* The server's own join of lead + resolved body
              (`Workspace.compose_description`) -- rendered as-is, never
              rejoined here, so this can never disagree with what Printify,
              Etsy, and the deploy comparison view will actually send
              (AI SEO implementation plan, "Description and common-copy
              boundaries"). */}
          <p id="details-description-preview" className="description-preview">
            {detail.description_composed}
          </p>
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
