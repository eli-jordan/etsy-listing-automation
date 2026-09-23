import { useEffect, useRef, useState } from "react";
import { listCommonCopy, listEtsySections, listPricingPlans } from "../../api/listings";
import type {
  CommonCopySummary,
  EtsySectionSummary,
  ListingDetail,
  PricingPlanSummary,
} from "../../types";
import type { SaveState } from "../../hooks/useAutosave";
import { AiChoiceDrawer } from "./aiSeo/AiChoiceDrawer";
import { DescriptionSourcePicker } from "./DescriptionSourcePicker";
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

/** `check_copy_is_concrete`/`check_description_ref`
 * (`config/listing_validation.py`) file every description issue -- the empty
 * lead that blocks deployment, and a `ref` that will not resolve -- under
 * this one `where`, matching `_COPY_WHERE["description"]` exactly. Both are
 * shown together beneath the description fields, the same block issues the
 * page-level banner surfaces, but visible without leaving the tab. */
const DESCRIPTION_ISSUE_WHERE = "Listing Details › Description";

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
  onFlush: () => void;
  save?: SaveState | undefined;
}

export function DetailsTab({ detail, onUpdate, onFlush, save }: Props) {
  const [tagDraft, setTagDraft] = useState("");
  const [sections, setSections] = useState<EtsySectionSummary[]>([]);
  const [plans, setPlans] = useState<PricingPlanSummary[]>([]);
  const [commonCopy, setCommonCopy] = useState<CommonCopySummary[]>([]);
  const [previewOpen, setPreviewOpen] = useState(false);
  const previewRef = useRef<HTMLDivElement>(null);
  const previewButtonRef = useRef<HTMLButtonElement>(null);
  const aiSeo = useAiSeoMode(detail, onUpdate, onFlush, save);
  const wasGenerating = useRef(false);
  const [drawerMotion, setDrawerMotion] = useState(false);
  if (aiSeo.phase === "loading") {
    wasGenerating.current = true;
  } else if (wasGenerating.current) {
    wasGenerating.current = false;
    const reveal = aiSeo.proposal !== null && document.visibilityState === "visible";
    if (reveal !== drawerMotion) setDrawerMotion(reveal);
  }
  if (aiSeo.proposal === null && drawerMotion) setDrawerMotion(false);
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

  useEffect(() => {
    if (!previewOpen) return;
    function onPointerDown(event: PointerEvent) {
      if (!previewRef.current?.contains(event.target as Node)) setPreviewOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setPreviewOpen(false);
        previewButtonRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [previewOpen]);

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

  function setBodySource(source: string | null) {
    if (source === null) {
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
        <legend className="seo-details-legend">Listing details</legend>

        <div className="seo-brief-row">
          <div className="field">
            <label htmlFor="details-brief">Brief</label>
            <textarea
              id="details-brief"
              placeholder="Describe the design and include any exact words shown in it."
              value={detail.brief}
              onChange={(event) => onUpdate({ brief: event.target.value })}
              onBlur={onFlush}
            />
          </div>
          <AiSeoControl mode={aiSeo} buttonRef={aiModeButtonRef} />
        </div>

        <div className={titleError ? "field field--invalid" : "field"}>
          <label htmlFor="details-title">Title</label>
          <div className="field__line">
            <div className="field__stack">
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
              {aiSeo.proposal?.unresolved.title && (
                <div ref={titleDrawerRef}>
                  <AiChoiceDrawer
                    enter={drawerMotion}
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
            <span className="field__count">
              {title.length} / {MAX_TITLE_LENGTH}
            </span>
          </div>
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
          <div className="field__line">
            <div className="field__stack">
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
              {aiSeo.proposal?.unresolved.tags && (
                <AiTagsDrawer
                  enter={drawerMotion}
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
            <span className="field__count">
              {tags.length} / {MAX_TAGS}
            </span>
          </div>
        </div>

        <div className="field">
          <label htmlFor="details-description-lead">Description Lead</label>
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
              enter={drawerMotion}
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
          <label htmlFor="details-description-source">Description Body</label>
          <DescriptionSourcePicker
            value={description.ref ?? null}
            items={commonCopy}
            onSelect={(source) => {
              setBodySource(source);
              onFlush();
            }}
          />

          {description.ref === null && (
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
          )}

          {descriptionIssues.map((issue, index) => (
            <span key={index} className="field__error">
              {issue.message}
            </span>
          ))}
        </div>

        <div className="description-preview-control" ref={previewRef}>
          <button
            ref={previewButtonRef}
            type="button"
            className="description-preview-control__link"
            aria-expanded={previewOpen}
            aria-controls="details-description-preview"
            onClick={() => setPreviewOpen((open) => !open)}
          >
            Description preview
          </button>
          {/* The server's own join of lead + resolved body
              (`Workspace.compose_description`) -- rendered as-is, never
              rejoined here, so this can never disagree with what Printify,
              Etsy, and the deploy comparison view will actually send
              (AI SEO implementation plan, "Description and common-copy
              boundaries"). */}
          {previewOpen && (
            <div
              id="details-description-preview"
              className="description-preview-card"
              role="region"
              aria-label="Description preview"
            >
              <strong className="description-preview-card__title">Description preview</strong>
              <p className="description-preview">{detail.description_composed}</p>
            </div>
          )}
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
