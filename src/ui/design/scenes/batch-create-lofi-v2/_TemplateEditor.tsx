// Shared listing-template editor. It reuses the listing editor's tabs and
// controls but has no design, SEO copy, lifecycle or deploy actions.
//   new     - just created from a listing (or cloned): name it to save
//   images  - Listing Images tab with the calibrator's test-design preview
//   unsaved - an edit that makes the template incomplete is held, not saved
import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { WarningIcon } from "@phosphor-icons/react/dist/csr/Warning";
import { Shell } from "./_Shell";
import { listingTemplates } from "./_fixtures";

export type TemplateEditorMode = "new" | "images" | "unsaved";

const colours: { name: string; swatch: string; shade: "dark" | "light" }[] = [
  { name: "Black", swatch: "#1f1d1c", shade: "dark" },
  { name: "Ivory", swatch: "#efe7d4", shade: "light" },
  { name: "Moss", swatch: "#5f6b3c", shade: "dark" },
  { name: "Blue Jean", swatch: "#6c7f94", shade: "dark" },
  { name: "Pepper", swatch: "#4a4744", shade: "dark" },
  { name: "Butter", swatch: "#f0d98c", shade: "light" },
];
const enabledColours = ["Black", "Ivory", "Moss", "Blue Jean", "Pepper"];

const gallery = listingTemplates[0].gallery;
const galleryNames = ["lifestyle · Moss", "flat lay · Black", "flat lay · Ivory", "close-up · Moss"];

function Tabs({ on }: { on: "variants" | "images" | "details" }) {
  const tab = (id: typeof on, label: string, goto?: string) => (
    <div className={on === id ? "seg-opt seg-opt--on" : "seg-opt"} data-goto={goto}>
      {label}
    </div>
  );
  return (
    <div className="tabs seg" role="tablist" aria-label="Listing template sections">
      {tab("variants", "Variants", "batch-create-lofi-v2/template-unsaved")}
      {tab("images", "Listing Images", "batch-create-lofi-v2/template-editor")}
      {tab("details", "Pricing & Details")}
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
          <img src={gallery[1]} alt="Black flat lay with the test design" />
        </div>
        <p className="variants-preview__hint">Previewing with the Bundled grid test design.</p>
      </div>
    </div>
  );
}

function ImagesTab() {
  return (
    <div className="bc-tpl-images">
      <div>
        <section className="design-picker">
          <h3 className="design-picker__heading">Test design</h3>
          <select className="input design-picker__select" aria-label="Test design" defaultValue="grid">
            <optgroup label="Bundled">
              <option value="grid">Bundled grid</option>
              <option value="type">Bundled type sample</option>
            </optgroup>
            <optgroup label="My uploads">
              <option value="night">night-hike-club.png</option>
            </optgroup>
          </select>
          <label className="design-picker__upload">
            <span>＋ Upload a PNG…</span>
            <input type="file" accept="image/png" />
          </label>
        </section>
        <p className="bc-small bc-muted" style={{ marginTop: "var(--space-2)" }}>
          Only for previewing. Each batch listing gets its own design.
        </p>

        <span className="section-label" style={{ marginTop: "var(--space-4)" }}>
          Gallery · 4 images, in listing order
        </span>
        <div className="bc-tpl-gallery">
          {gallery.map((src, i) => (
            <figure key={galleryNames[i]} className={i === 0 ? "bc-tpl-tile bc-tpl-tile--on" : "bc-tpl-tile"}>
              <img src={src} alt="" />
              <figcaption>
                {i + 1}. {galleryNames[i]}
                {i >= 2 && <span className="tag tag-neutral">template file</span>}
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
      <div className="preview-stage preview-stage--large">
        <img src={gallery[0]} alt="Lifestyle mockup with the test design" />
      </div>
    </div>
  );
}

export function TemplateEditor({ mode }: { mode: TemplateEditorMode }) {
  const template = listingTemplates[0];
  return (
    <Shell active="listing-templates">
      <div className="editor">
        <div className="page-head page-head--editor">
          <span className="page-head__crumb" data-goto="batch-create-lofi-v2/templates">
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
            <h1 className="page-head__title">{template.name}</h1>
          )}
          {mode === "new" && (
            <span className="page-head__meta">Name it to save. Copied from mountain-sunrise-tee.</span>
          )}
          {mode === "images" && <span className="page-head__meta">Saved just now</span>}
          {mode === "unsaved" && (
            <span className="bc-status bc-status--warn bc-small">
              <WarningIcon className="bc-icon" />
              <span className="bc-status__text">Not saved: fix the colours below</span>
            </span>
          )}
          <div className="page-head__actions">
            {mode !== "new" && (
              <>
                <button type="button" className="bc-quiet" title="Clone listing template" data-goto="batch-create-lofi-v2/template-new">
                  <CopySimpleIcon className="bc-icon" style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 4 }} />
                  Clone
                </button>
                <button type="button" className="bc-quiet" title="Delete listing template">
                  <TrashIcon className="bc-icon" style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 4 }} />
                  Delete
                </button>
              </>
            )}
            <button
              type="button"
              className="btn btn-primary"
              disabled={mode === "new"}
              title={mode === "new" ? "Name the template first" : undefined}
              data-goto={mode === "new" ? undefined : "batch-create-lofi-v2/new-batch"}
            >
              Start batch
            </button>
          </div>
        </div>

        {mode === "unsaved" && (
          <div className="dv-callout dv-callout--drift" style={{ marginBottom: "var(--space-4)" }}>
            <WarningIcon className="dv-callout__icon" />
            <div>
              <strong>This change isn't saved yet.</strong> A template needs at least one colour, so
              heavyweight-tee keeps its last complete version until you turn one back on.
            </div>
          </div>
        )}

        <Tabs on={mode === "images" ? "images" : "variants"} />
        {mode === "images" ? <ImagesTab /> : <VariantsTab unsaved={mode === "unsaved"} />}
      </div>
    </Shell>
  );
}
