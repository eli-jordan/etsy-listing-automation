// Listing-template editor, built to match the listing editor as closely as
// possible: same head layout, same design row (reworded as a *preview*
// design), same four tabs. Differences, all deliberate:
//   - head: no status or Deploy; Clone, Delete and Start batch instead
//   - design row: picks a preview design only, never production artwork
//   - Listing Images: the Files group "This listing" reads "This template"
//   - Listing Details: no Brief, Title, Tags, Description lead or AI Mode
// Modes are the tab on show; "new" is Variants right after creation with the
// name empty and focused, "unsaved" is Variants holding an incomplete edit.
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { Shell } from "./_Shell";
import { listingTemplates } from "./_fixtures";

export type TemplateEditorMode = "new" | "variants" | "unsaved" | "pricing" | "images" | "details";
type TabId = "variants" | "pricing" | "images" | "details";

const tpl = listingTemplates[0];
const [lifestyle, black, ivory, moss] = tpl.gallery;

const colours: { name: string; swatch: string; shade: "dark" | "light" }[] = [
  { name: "Black", swatch: "#1f1d1c", shade: "dark" },
  { name: "Ivory", swatch: "#efe7d4", shade: "light" },
  { name: "Moss", swatch: "#5f6b3c", shade: "dark" },
  { name: "Blue Jean", swatch: "#6c7f94", shade: "dark" },
  { name: "Pepper", swatch: "#4a4744", shade: "dark" },
  { name: "Butter", swatch: "#f0d98c", shade: "light" },
];
const enabledColours = ["Black", "Ivory", "Moss", "Blue Jean", "Pepper"];

function Tabs({ on }: { on: TabId }) {
  const tabs: { id: TabId; label: string; goto: string }[] = [
    { id: "variants", label: "Variants", goto: "batch-create-lofi-v3/template-variants" },
    { id: "pricing", label: "Pricing", goto: "batch-create-lofi-v3/template-pricing" },
    { id: "images", label: "Listing Images", goto: "batch-create-lofi-v3/template-images" },
    { id: "details", label: "Listing Details", goto: "batch-create-lofi-v3/template-details" },
  ];
  return (
    <div className="tabs seg" role="tablist" aria-label="Listing template sections">
      {tabs.map((t) => (
        <div
          key={t.id}
          role="tab"
          aria-selected={on === t.id}
          className={on === t.id ? "seg-opt seg-opt--on" : "seg-opt"}
          data-goto={on === t.id ? undefined : t.goto}
        >
          {t.label}
        </div>
      ))}
    </div>
  );
}

/** The listing editor's design row, reworded: a preview design only. */
function PreviewDesign({ open }: { open: boolean }) {
  return (
    <div className="design-select">
      <div className="design-row">
        <img className="design-thumb" src={ivory} alt="" />
        <div className="design-row__text">
          <div className="design-row__name">Preview: Bundled grid</div>
          <div className="design-row__file">
            Only for previewing this template. Each batch listing gets its own design.
          </div>
        </div>
        <button type="button" className="design-row__change" aria-label="Change preview design" aria-expanded={open}>
          Change ▾
        </button>
      </div>
      {open && (
        <div className="add-panel">
          <span className="section-label">Preview designs</span>
          <div className="template-grid">
            {[
              ["Bundled grid", "bundled test design", true],
              ["Bundled type sample", "bundled test design", false],
              ["night-hike-club", "designs/night-hike-club.png", false],
              ["cedar-trail", "designs/cedar-trail.png", false],
            ].map(([name, file, on]) => (
              <button
                key={String(name)}
                type="button"
                className={on ? "template-card template-card--active" : "template-card"}
              >
                <span className="template-card__name">{name}</span>
                <span className="template-card__kind">{file}</span>
              </button>
            ))}
          </div>
          <button type="button" className="btn-like btn-like--ghost btn-sm">
            Upload a PNG to preview…
          </button>
        </div>
      )}
    </div>
  );
}

function VariantsTab({ unsaved }: { unsaved: boolean }) {
  const on = unsaved ? [] : enabledColours;
  return (
    <div className="layout--variants">
      <fieldset>
        <legend>Variants</legend>
        <div className="field">
          <label htmlFor="tpl-garment">Garment profile</label>
          <select id="tpl-garment" defaultValue="cc1717">
            <option value="cc1717">Comfort Colors 1717</option>
          </select>
        </div>
        <div className="field">
          <label>Sizes</label>
          <div className="garment-card__sizes">
            {["S", "M", "L", "XL", "2XL", "3XL"].map((s) => (
              <span key={s} className="size-pill">
                {s}
              </span>
            ))}
          </div>
        </div>
        <div className={unsaved ? "field field--invalid" : "field"}>
          <div className="colors-panel__head">
            <label style={{ margin: 0 }}>Colours</label>
            <span className="colors-panel__count">
              {on.length} of {colours.length} included
            </span>
          </div>
          <div className="shade-picker">
            <button type="button" className="btn-like btn-sm">
              Dark
            </button>
            <button type="button" className="btn-like btn-sm">
              Light
            </button>
            <span className="shade-picker__hint">only these shades</span>
          </div>
          {unsaved && <span className="field__error">Turn on at least one colour.</span>}
          {colours.map((c) => {
            const enabled = on.includes(c.name);
            return (
              <div key={c.name} className={enabled ? "color-row" : "color-row color-row--off"}>
                <button type="button" className="color-row__text" aria-label={`Preview ${c.name}`}>
                  <span className="color-row__swatch" style={{ background: c.swatch }} aria-hidden="true" />
                  <span className="color-row__name">{c.name}</span>
                </button>
                <span className={c.shade === "dark" ? "tag tag-neutral" : "tag tag-accent"}>{c.shade}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={enabled}
                  aria-label={c.name}
                  className={enabled ? "switch switch--on" : "switch"}
                >
                  <span className="switch__knob" />
                </button>
              </div>
            );
          })}
        </div>
      </fieldset>
      <div className="variants-preview">
        <div className="preview-stage preview-stage--large">
          <img src={black} alt="Black with the preview design" />
        </div>
        <p className="variants-preview__hint">
          Click a colour to preview it — helps judge whether it suits the design.
        </p>
      </div>
    </div>
  );
}

function PricingTab() {
  const prices: [string, string][] = [
    ["S", "349"],
    ["M", "349"],
    ["L", "349"],
    ["XL", "349"],
    ["2XL", "379"],
    ["3XL", "399"],
  ];
  return (
    <div className="pricing-tab">
      <fieldset>
        <legend>Pricing</legend>
        <div className="field">
          <label htmlFor="tpl-plan">Plan</label>
          <select id="tpl-plan" className="input" defaultValue="standard">
            <option value="standard">Standard NOK</option>
            <option value="premium">Premium NOK</option>
          </select>
        </div>
        <div className="price-table">
          {prices.map(([size, amount]) => (
            <div key={size} className="price-table__cell">
              <span className="price-table__size">{size}</span>
              <input
                className="input price-table__input"
                type="number"
                aria-label={`Price for size ${size}`}
                defaultValue={amount}
              />
              <span className="price-table__currency">NOK</span>
            </div>
          ))}
        </div>
      </fieldset>
    </div>
  );
}

function ImagesTab() {
  const reel: [string, string][] = [
    [lifestyle, "lifestyle-porch · Moss"],
    [black, "flat-lay · Black"],
    [ivory, "flat-lay · Ivory"],
    [moss, "size-chart.png"],
  ];
  return (
    <div className="images-tab">
      <div className="locator">
        <div className="locator__head">
          <span className="locator__title">Add media</span>
          <span className="locator__hint">Hover to preview · click to add</span>
        </div>
        <div className="seg locator__modes">
          <button type="button" className="seg-opt" aria-pressed="false">
            Mockup templates
          </button>
          <button type="button" className="seg-opt seg-opt--on" aria-pressed="true">
            Files
          </button>
        </div>
        <div className="locator__search">
          <svg viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-3.5-3.5" />
          </svg>
          <input className="input" type="text" placeholder="Search files…" />
        </div>
        <div className="locator__list">
          <div role="group" aria-label="This template" className="loc-group">
            <span className="loc-group__label">This template</span>
            <div className="loc-images">
              <button type="button" className="loc-img loc-img--in" aria-pressed="true" aria-label="size-chart.png">
                <span className="loc-img__face">
                  <img src={moss} alt="" />
                </span>
                <span className="loc-img__name">size-chart.png</span>
              </button>
            </div>
          </div>
          <div role="group" aria-label="Shared" className="loc-group">
            <span className="loc-group__label">Shared</span>
            <div className="loc-images">
              {[
                [lifestyle, "care-guide.png"],
                [ivory, "shop-banner.png"],
              ].map(([src, name]) => (
                <button key={name} type="button" className="loc-img" aria-pressed="false" aria-label={name}>
                  <span className="loc-img__face">
                    <img src={src} alt="" />
                  </span>
                  <span className="loc-img__name">{name}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="images-right">
        <div className="preview-pane">
          <div className="preview-stage preview-stage--large">
            <button type="button" className="preview-stage__open">
              <img src={lifestyle} alt="lifestyle-porch · Moss" />
            </button>
          </div>
          <div className="preview-foot">
            <span className="preview-meta">
              <span className="preview-meta__title">lifestyle-porch · Moss</span>
              <span className="preview-meta__path">mockup template, with the preview design</span>
            </span>
            <span className="preview-actions">
              <button type="button" className="btn-like btn-like--ghost btn-sm">
                Remove from listing
              </button>
            </span>
          </div>
        </div>

        <div className="reel">
          <div className="reel__head">
            <span className="reel__title">Listing gallery</span>
            <span className="reel__count">4 of 20 images</span>
            <span className="reel__count">0 of 1 videos</span>
            <span className="reel__hint">Drag a tile to change the order Etsy shows them in</span>
          </div>
          <div className="reel__track">
            {reel.map(([src, label], i) => (
              <div key={label} className={i === 0 ? "rtile rtile--selected" : "rtile"}>
                <div className="rtile__face">
                  <img src={src} alt={label} />
                  <span className="rtile__pos">{i + 1}</span>
                  <span className="rtile__x" role="button" aria-label={`Remove ${label}`}>
                    ×
                  </span>
                  {i === 0 && <span className="rtile__first">Etsy thumbnail</span>}
                </div>
                <span className="rtile__label">{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function DetailsTab() {
  return (
    <div className="details-tab">
      <fieldset className="seo-details-fieldset">
        <legend className="seo-details-legend">Listing details</legend>

        <p className="field__hint" style={{ margin: "0 0 var(--space-3)" }}>
          Brief, title, tags and description lead are written for each listing in a batch.
        </p>

        <div className="field">
          <label htmlFor="tpl-body">Description Body</label>
          <div className="description-source-picker">
            <button id="tpl-body" className="input description-source-picker__trigger" type="button" aria-haspopup="listbox">
              <span>Write listing-specific body</span>
              <span aria-hidden="true" className="description-source-picker__chevron" />
            </button>
          </div>
          <textarea
            aria-label="Description body"
            readOnly
            value={
              "Garment-dyed 100% ring-spun cotton, relaxed fit.\nPrinted to order in Europe. Wash inside out at 30°C."
            }
          />
        </div>

        <div className="description-preview-control">
          <button type="button" className="description-preview-control__link" aria-expanded="false">
            Description preview
          </button>
        </div>

        <div className="field">
          <label htmlFor="tpl-section">Section</label>
          <select id="tpl-section" className="input" defaultValue="Hiking tees">
            <option value="">No section</option>
            <option>Hiking tees</option>
            <option>Outdoor gifts</option>
          </select>
        </div>

        <div className="field">
          <label htmlFor="tpl-materials">Materials</label>
          <input id="tpl-materials" className="input" type="text" value="ring-spun cotton" readOnly />
          <span className="field__hint">Set by the selected garment profile.</span>
        </div>
      </fieldset>
    </div>
  );
}

export function TemplateEditor({ mode }: { mode: TemplateEditorMode }) {
  const tab: TabId = mode === "new" || mode === "unsaved" ? "variants" : mode;
  return (
    <Shell active="listing-templates">
      <div className="editor">
        <div className="page-head page-head--editor">
          <span className="page-head__crumb" data-goto="batch-create-lofi-v3/templates">
            Listing templates
          </span>
          <span className="page-head__sep">/</span>
          {mode === "new" ? (
            <input
              className="input bc-tpl-name"
              type="text"
              placeholder="Name this template"
              aria-label="Template name"
              autoFocus
            />
          ) : (
            <h1 className="page-head__title">{tpl.name}</h1>
          )}
          {mode === "new" && (
            <span className="page-head__meta">Name it to save. Copied from mountain-sunrise-tee.</span>
          )}
          {mode === "unsaved" && (
            <span className="bc-status bc-status--warn bc-small">
              <WarningIcon className="bc-icon" />
              <span className="bc-status__text">Not saved: at least one colour is needed</span>
            </span>
          )}
          {mode !== "new" && mode !== "unsaved" && <span className="page-head__meta">Saved just now</span>}
          <div className="page-head__actions">
            {mode !== "new" && (
              <>
                <button type="button" className="btn btn-ghost" data-goto="batch-create-lofi-v3/template-new">
                  Clone
                </button>
                <button type="button" className="btn btn-ghost">
                  Delete
                </button>
              </>
            )}
            <button
              type="button"
              className="btn btn-primary"
              disabled={mode === "new"}
              title={mode === "new" ? "Name the template first" : undefined}
              data-goto={mode === "new" ? undefined : "batch-create-lofi-v3/new-batch"}
            >
              Start batch
            </button>
          </div>
        </div>

        <PreviewDesign open={mode === "variants"} />
        <Tabs on={tab} />
        {tab === "variants" && <VariantsTab unsaved={mode === "unsaved"} />}
        {tab === "pricing" && <PricingTab />}
        {tab === "images" && <ImagesTab />}
        {tab === "details" && <DetailsTab />}
      </div>
    </Shell>
  );
}
