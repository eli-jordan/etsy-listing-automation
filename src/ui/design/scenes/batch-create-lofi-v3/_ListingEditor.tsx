// A batch-created listing opened from the batch summary. Adds three things to
// the ordinary editor: a way back to the batch, Mark reviewed, and a stale
// proposal that can still be used; the drawer's wording is the warning.
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/csr/ArrowLeft";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { StatusTag } from "../../../src/components/StatusTag";
import { AiModeMark } from "../../../src/pages/editor/aiSeo/AiChoiceDrawer";
import { Shell } from "./_Shell";
import { batchLabel } from "./_fixtures";

const titles = [
  "After Rain Trail Tee, Misty Forest Hiking Shirt",
  "Rainy Day Hiker Graphic Tee, Pacific Northwest Trail",
  "After The Rain Mountain Path Shirt for Hikers",
];

const tags = [
  "rainy day hike",
  "forest trail tee",
  "hiking shirt",
  "pnw graphic tee",
  "misty mountains",
  "hiker gift",
  "nature lover tee",
  "trail runner",
  "outdoor shirt",
  "comfort colors tee",
  "camping tee",
  "rain lover gift",
  "adventure tee",
];

export function ListingFromBatch() {
  return (
    <Shell active="listings">
      <div className="editor">
        <button type="button" className="btn btn-secondary bc-back" data-goto="batch-create-lofi-v3/batch-summary">
          <ArrowLeftIcon />
          Back to batch {batchLabel}
        </button>

        <div className="page-head page-head--editor">
          <span className="page-head__crumb">Listings</span>
          <span className="page-head__sep">/</span>
          <h1 className="page-head__title">after-rain-trail-2</h1>
          <StatusTag status="draft" />
          <div className="page-head__actions">
            <button type="button" className="btn btn-ghost" data-goto="batch-create-lofi-v3/template-new">
              Save as listing template
            </button>
            <button type="button" className="btn btn-secondary" aria-pressed="false">
              <CheckIcon style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 6 }} />
              Mark reviewed
            </button>
            <button type="button" className="btn btn-primary">
              Deploy changes →
            </button>
          </div>
        </div>

        <div className="design-select">
          <div className="design-row">
            <span className="design-thumb design-thumb--empty" aria-hidden="true" />
            <div className="design-row__text">
              <div className="design-row__name">after-rain-trail-2.png</div>
              <div className="design-row__file">designs/after-rain-trail-2.png</div>
            </div>
          </div>
        </div>

        <div className="tabs seg" role="tablist" aria-label="Listing editor sections">
          <div className="seg-opt">Variants</div>
          <div className="seg-opt">Pricing</div>
          <div className="seg-opt">Listing Images</div>
          <div className="seg-opt seg-opt--on">Listing Details</div>
        </div>

        <div className="details-tab">
          <fieldset className="seo-details-fieldset">
            <legend className="seo-details-legend">Listing details</legend>

            <div className="field">
              <label htmlFor="d-brief">Brief</label>
              <textarea
                id="d-brief"
                readOnly
                value="Hand-drawn forest trail after rain, puddles on the path and mist in the pines. Words: “after rain”. Edited: soft, calm mood, not sporty."
              />
              <span className="field__hint">Written by AI for this batch, then edited by you.</span>
            </div>

            <div className="field">
              <label htmlFor="d-title">Title</label>
              <div className="field__line">
                <div className="field__stack">
                  <input id="d-title" className="input" type="text" placeholder="The title shoppers see on Etsy" readOnly />
                  <div className="seo-suggestion-slot">
                    <aside className="seo-suggestion seo-suggestion--stale" role="region" aria-label="title AI suggestions">
                      <div className="seo-suggestion__topline">
                        <div className="seo-suggestion__identity">
                          <AiModeMark />
                          <span>Out of date: brief edited since. Still usable</span>
                        </div>
                        <div className="seo-suggestion__actions">
                          <button type="button">Regenerate</button>
                          <button type="button">Reject all</button>
                        </div>
                      </div>
                      <div className="seo-choice-list">
                        {titles.map((t, i) => (
                          <button key={t} type="button">
                            <span>{i + 1}</span>
                            {t}
                          </button>
                        ))}
                      </div>
                    </aside>
                  </div>
                </div>
                <span className="field__count">0 / 140</span>
              </div>
            </div>

            <div className="field">
              <label>Tags</label>
              <div className="chips">
                {tags.map((t) => (
                  <span key={t} className="chip">
                    {t}
                  </span>
                ))}
              </div>
              <span className="field__hint">
                13 / 13 · accepted from AI Mode.{" "}
                <button type="button" className="bc-link">
                  Show suggestions again
                </button>
              </span>
            </div>
          </fieldset>
        </div>
      </div>

    </Shell>
  );
}
