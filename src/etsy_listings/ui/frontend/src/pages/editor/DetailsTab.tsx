import { useState } from "react";
import type { ListingDetail } from "../../types";

/** Title/tags/description/section/pricing (phase 5). Pricing is *display*
 * only here -- selecting a different plan or editing per-size prices from
 * the UI is deferred (phase-5-listings-ui.md); section is a plain text field
 * rather than a dropdown of invented shop sections, since the real list only
 * exists on the live Etsy shop and validating it needs a real `plan()`,
 * explicitly out of scope for this module. */

interface Props {
  detail: ListingDetail;
  onUpdate: (patch: Record<string, unknown>) => void;
  onFlush: () => void;
}

export function DetailsTab({ detail, onUpdate, onFlush }: Props) {
  const [tagDraft, setTagDraft] = useState("");
  const tags = Array.isArray(detail.etsy.tags) ? detail.etsy.tags : [];
  const titleError = detail.field_errors["etsy.title"];
  const sectionError = detail.field_errors["etsy.section"];

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
        </div>

        <div className="field">
          <label htmlFor="details-description">Description</label>
          <textarea
            id="details-description"
            value={detail.etsy.description}
            onChange={(event) => onUpdate({ etsy: { description: event.target.value } })}
            onBlur={onFlush}
          />
        </div>

        <div className={sectionError ? "field field--invalid" : "field"}>
          <label htmlFor="details-section">Section</label>
          <input
            id="details-section"
            className="input"
            type="text"
            value={detail.etsy.section ?? ""}
            onChange={(event) => onUpdate({ etsy: { section: event.target.value || null } })}
            onBlur={onFlush}
          />
          {sectionError && <span className="field__error">{sectionError}</span>}
        </div>
      </fieldset>

      <fieldset>
        <legend>Pricing</legend>
        <p className="field__hint" style={{ textAlign: "left" }}>
          {detail.pricing_plan_name
            ? `Plan: ${detail.pricing_plan_name}`
            : "No pricing plan resolved -- see prices: below."}
        </p>
        {detail.resolved_prices.length > 0 ? (
          <div className="price-table">
            {detail.resolved_prices.map((price) => (
              <div key={price.size} className="price-table__cell">
                <span className="price-table__size">{price.size}</span>
                <span className="price-table__amount">{price.amount}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-muted">No resolved prices.</p>
        )}
      </fieldset>
    </div>
  );
}
