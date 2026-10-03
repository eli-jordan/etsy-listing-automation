// The listing-template editor, assembled from the listing editor's own parts:
// the real IssuesBanner, VariantsTab, PricingTab and ImagesTab mounted with a
// template-shaped ListingDetail, and the real EditableName and save line in
// the head. Only three pieces are composed here, each copying the real
// markup, because the template's version differs from the listing's:
//   - the head: no status, Deploy, Clone, Delete or Start batch
//     (those live on the Listing templates page)
//   - the design row: a *preview* design (DesignSelect's markup, reworded)
//   - Listing Details: DetailsTab without brief, title, tags, lead or AI Mode
import "./_mockApi";
import mockupIvory from "../../assets/batch-deploy/mockup-ivory.png";
import { useState } from "react";
import { EditableName } from "../../../src/components/EditableName";
import { DescriptionSourcePicker } from "../../../src/pages/editor/DescriptionSourcePicker";
import { ImagesTab } from "../../../src/pages/editor/ImagesTab";
import { PricingTab } from "../../../src/pages/editor/PricingTab";
import { SavedAgo } from "../../../src/pages/editor/SavedAgo";
import { VariantsTab } from "../../../src/pages/editor/VariantsTab";
import { metaFor } from "../../../src/pages/editor/saveMeta";
import type { Issue, ListingDetail } from "../../../src/types";
import { Shell } from "./_Shell";
import { incompleteTemplate, templateDetail } from "./_editorFixtures";

export type TemplateEditorMode = "new" | "variants" | "unsaved" | "pricing" | "images" | "details";
type Tab = "variants" | "pricing" | "images" | "details";

const TABS: { id: Tab; label: string }[] = [
  { id: "variants", label: "Variants" },
  { id: "pricing", label: "Pricing" },
  { id: "images", label: "Listing Images" },
  { id: "details", label: "Listing Details" },
];

const noop = () => {};

function badgeCount(issues: Issue[], tab: Tab): number {
  return issues.filter((i) => i.tab === tab && i.severity !== "info").length;
}

/** DesignSelect's markup and classes, with preview wording. */
function PreviewDesign({ open }: { open: boolean }) {
  const [picking, setPicking] = useState(open);
  return (
    <div className="design-select">
      <div className="design-row">
        <img className="design-thumb" src={mockupIvory} alt="" />
        <div className="design-row__text">
          <div className="design-row__name">Preview design: Bundled grid</div>
          <div className="design-row__file">
            Only for previewing this template — each listing in a batch gets its own design
          </div>
        </div>
        <button
          type="button"
          className="design-row__change"
          aria-label="Change preview design"
          aria-expanded={picking}
          onClick={() => setPicking((o) => !o)}
        >
          Change ▾
        </button>
      </div>
      {picking && (
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

/** DetailsTab's markup and classes, keeping only what a template owns. */
function TemplateDetailsTab({ detail }: { detail: ListingDetail }) {
  const [previewOpen, setPreviewOpen] = useState(false);
  const description = detail.etsy.description;
  return (
    <div className="details-tab">
      <fieldset className="seo-details-fieldset">
        <legend className="seo-details-legend">Listing details</legend>

        <div className="field">
          <label htmlFor="details-description-source">Description Body</label>
          <DescriptionSourcePicker
            value={description.ref ?? null}
            items={[
              {
                ref: "common-copy/comfort-colors-standard.md",
                title: "Comfort Colors · standard fit and care",
                summary: "Garment-dyed ring-spun cotton, relaxed fit, care notes.",
              },
            ]}
            onSelect={noop}
          />
          {description.ref == null && (
            <textarea
              id="details-description-text"
              aria-label="Description body"
              value={description.text ?? ""}
              onChange={noop}
            />
          )}
          <span className="field__hint">
            Each listing's own description lead is placed above this body.
          </span>
        </div>

        <div className="description-preview-control">
          <button
            type="button"
            className="description-preview-control__link"
            aria-expanded={previewOpen}
            onClick={() => setPreviewOpen((o) => !o)}
          >
            Description preview
          </button>
          {previewOpen && (
            <div className="description-preview-card" role="region" aria-label="Description preview">
              <strong className="description-preview-card__title">Description preview</strong>
              <p className="description-preview">{detail.description_composed}</p>
            </div>
          )}
        </div>

        <div className="field">
          <label htmlFor="details-section">Section</label>
          <select id="details-section" className="input" value={detail.etsy.section ?? ""} onChange={noop}>
            <option value="">No section</option>
            <option value="Hiking tees">Hiking tees</option>
            <option value="Outdoor gifts">Outdoor gifts</option>
          </select>
        </div>

        <div className="field">
          <label htmlFor="details-materials">Materials</label>
          <input
            id="details-materials"
            className="input"
            type="text"
            value={(detail.garment_materials ?? []).join(", ")}
            readOnly
          />
          <span className="field__hint">Set by the selected garment profile.</span>
        </div>
      </fieldset>
    </div>
  );
}

export function TemplateEditor({ mode }: { mode: TemplateEditorMode }) {
  const detail = mode === "unsaved" ? incompleteTemplate : templateDetail();
  const [tab, setTab] = useState<Tab>(
    mode === "new" || mode === "unsaved" || mode === "variants" ? "variants" : mode,
  );
  const named = mode !== "new";

  const meta =
    mode === "new" ? (
      "Not saved — name this template to save it"
    ) : mode === "unsaved" ? (
      metaFor({ kind: "unsaved" }, detail.name)
    ) : (
      <>
        <span className="page-head__path">listing-templates/{detail.name}/template.yaml</span>
        {" · "}
        <span className="page-head__saved">
          <span className="page-head__dot" aria-hidden="true" />
          <SavedAgo savedAt={Date.now()} />
        </span>
      </>
    );

  return (
    <Shell active="listing-templates">
      <div className="editor">
        <div className="page-head page-head--editor">
          <span className="page-head__crumb" data-goto="batch-create-lofi/templates">
            Listing templates
          </span>
          <span className="page-head__sep">/</span>
          <EditableName
            value={named ? detail.name : ""}
            onCommit={noop}
            placeholder="Name this template…"
            label="Template name"
          />
          <span className="page-head__meta">{meta}</span>
        </div>

        {detail.issues.length > 0 && (
          // IssuesBanner's markup; its copy is about deploying, which a
          // template never does, so it would take a template wording prop.
          <div className="issues">
            <div className="issues__head">
              <span className="issues__summary issues__summary--warn">
                {detail.issues.length} to fix before this template saves
              </span>
              <span className="issues__when">Last complete version is kept until then</span>
            </div>
            {detail.issues.map((issue) => (
              <div key={issue.where} className="issue issue--warn">
                <span className="issue__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="15" height="15">
                    <path
                      d="M10.3 3.9a2 2 0 0 1 3.4 0l8.1 14.1A2 2 0 0 1 20.1 21H3.9a2 2 0 0 1-1.7-3z"
                      fill="var(--color-warning)"
                    />
                    <path
                      d="M12 9v4.6M12 17.2v.01"
                      fill="none"
                      stroke="var(--color-warning-ink)"
                      strokeWidth="2.2"
                      strokeLinecap="round"
                    />
                  </svg>
                </span>
                <span className="issue__body">
                  <span className="issue__text">{issue.message}</span>
                  <span className="issue__where">{issue.where}</span>
                </span>
                {issue.tab === tab ? (
                  <span className="issue__fix issue__fix--here">Below</span>
                ) : (
                  <button type="button" className="issue__fix" onClick={() => setTab(issue.tab)}>
                    Fix &rarr;
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        <PreviewDesign open={mode === "variants"} />

        <div className="tabs seg">
          {TABS.map((t) => {
            const count = badgeCount(detail.issues, t.id);
            return (
              <div
                key={t.id}
                className={tab === t.id ? "seg-opt seg-opt--on" : "seg-opt"}
                onClick={() => setTab(t.id)}
              >
                {t.label}
                {count > 0 && <span className="tab-badge tab-badge--warn">{count}</span>}
              </div>
            );
          })}
        </div>

        {tab === "variants" && <VariantsTab detail={detail} onUpdate={noop} />}
        {tab === "pricing" && <PricingTab detail={detail} onUpdate={noop} onFlush={noop} />}
        {tab === "images" && <ImagesTab detail={detail} onUpdate={noop} />}
        {tab === "details" && <TemplateDetailsTab detail={detail} />}
      </div>
    </Shell>
  );
}
