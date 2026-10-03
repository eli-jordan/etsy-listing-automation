import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { MinusCircleIcon } from "@phosphor-icons/react/dist/csr/MinusCircle";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { StatusTag } from "../../../src/components/StatusTag";
import { Shell } from "./_Shell";

export const meta = {
  title: "Save as listing template · v1",
  viewport: "laptop",
  description:
    "Wireframe: dialog over the listing editor naming the template and showing what it keeps and what each new listing gets fresh.",
};

const kept: { label: string; detail: string }[] = [
  { label: "Product", detail: "Comfort Colors 1717 · 5 colours" },
  { label: "Prices", detail: "Standard NOK plan, plus 1 size override" },
  { label: "Gallery", detail: "4 images, in order. 2 listing-only images are copied into the template" },
  { label: "Etsy settings", detail: "Auto-renew, section Hiking tees, shipping profile Norway Post" },
];

const reset = [
  "Design artwork: each new listing gets one design from the batch",
  "Brief: written fresh for every design",
  "Title, tags and description lead: suggested per listing for you to accept",
  "Lifecycle, Printify and Etsy identity, renders and past AI proposals",
];

export default function SaveAsTemplateDialog() {
  return (
    <Shell active="listings">
      <div className="page-head page-head--editor">
        <span className="page-head__crumb">Listings</span>
        <span className="page-head__sep">›</span>
        <h1 className="page-head__title">mountain-sunrise-tee</h1>
        <StatusTag status="live" />
        <div className="page-head__actions">
          <button type="button" className="btn btn-secondary">
            Save as listing template
          </button>
          <button type="button" className="btn btn-primary">
            Deploy
          </button>
        </div>
      </div>
      <div style={{ height: 560, borderRadius: "var(--radius-sm)", background: "var(--color-surface)" }} />

      <div className="modal-root">
        <div className="modal-backdrop" />
        <div className="modal-dialog bc-modal" role="dialog" aria-labelledby="save-template-title">
          <div className="modal-dialog__head">
            <h2 className="modal-dialog__title" id="save-template-title">
              Save as listing template
            </h2>
            <button type="button" className="modal-dialog__close" aria-label="Close" data-goto="batch-create-lofi-v1/templates">
              <XIcon size={16} />
            </button>
          </div>

          <div className="field">
            <label htmlFor="template-name">Template name</label>
            <input id="template-name" className="input" type="text" defaultValue="heavyweight-tee" style={{ width: 320 }} />
            <p className="field__hint bc-small bc-muted" style={{ margin: "4px 0 0" }}>
              Lowercase letters, digits and hyphens. It must not match an existing template.
            </p>
          </div>

          <div className="bc-split">
            <div>
              <span className="section-label">Kept in the template</span>
              <ul className="bc-list bc-list--keep">
                {kept.map((k) => (
                  <li key={k.label}>
                    <CheckIcon className="bc-icon" />
                    <span>
                      <strong>{k.label}.</strong> {k.detail}
                    </span>
                  </li>
                ))}
                <li>
                  <CheckIcon className="bc-icon" />
                  <span>
                    <strong>Description body.</strong> This inline text is reused word for word:
                    <p className="bc-quote">
                      Garment-dyed 100% ring-spun cotton, relaxed fit. Printed to order in Europe.
                      Wash inside out at 30°C…
                    </p>
                  </span>
                </li>
              </ul>
            </div>
            <div>
              <span className="section-label">Fresh for every new listing</span>
              <ul className="bc-list bc-list--reset">
                {reset.map((r) => (
                  <li key={r}>
                    <MinusCircleIcon className="bc-icon" />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="bc-dialog-foot">
            <span className="bc-small bc-muted">
              Saving checks the template locally. It never contacts Printify or Etsy.
            </span>
            <span className="bc-spacer" />
            <button type="button" className="btn btn-secondary" data-goto="batch-create-lofi-v1/templates">
              Cancel
            </button>
            <button type="button" className="btn btn-primary" data-goto="batch-create-lofi-v1/templates">
              Save listing template
            </button>
          </div>
        </div>
      </div>
    </Shell>
  );
}
