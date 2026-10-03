// The Listing templates page with a pluggable gallery: every frame in this
// scene is the same page and the same cards, and only the gallery differs.
import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { PlayIcon } from "@phosphor-icons/react/dist/csr/Play";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import type { ReactNode } from "react";
import { type GalleryItem, type TemplateCardData, templates } from "./_fixtures";

/** A gallery tile's picture: the render, or a video's poster with its badge. */
export function Tile({ item, className }: { item: GalleryItem; className?: string }) {
  return (
    <span className={`tc-tile ${className ?? ""}`}>
      <img src={item.src} alt="" />
      {item.kind === "video" && (
        <span className="tc-play" aria-label="Video">
          <PlayIcon weight="fill" />
        </span>
      )}
    </span>
  );
}

function Card({ template, gallery }: { template: TemplateCardData; gallery: ReactNode }) {
  return (
    <article className="bc-card">
      {gallery}
      <div className="bc-card__body">
        <span className="bc-card__name">{template.name}</span>
        <span className="bc-card__facts">{template.facts}</span>
        <span className="bc-card__facts">{template.usage}</span>
        <span className="bc-card__drop-hint">Drop PNGs or a ZIP here to start a batch</span>
      </div>
      <div className="bc-card__foot">
        <button type="button" className="btn btn-secondary">
          Start batch
        </button>
        <button type="button" className="btn btn-ghost">
          Edit
        </button>
        <span className="bc-spacer" />
        <button type="button" className="bc-quiet" aria-label={`Clone ${template.name}`}>
          <CopySimpleIcon className="bc-icon" style={{ width: 14, height: 14 }} />
        </button>
        <button type="button" className="bc-quiet" aria-label={`Delete ${template.name}`}>
          <TrashIcon className="bc-icon" style={{ width: 14, height: 14 }} />
        </button>
      </div>
    </article>
  );
}

export function TemplatesPage({
  gallery,
  gridClass,
}: {
  gallery: (template: TemplateCardData) => ReactNode;
  /** The card grid's column rule, when a direction needs a different width. */
  gridClass?: string;
}) {
  return (
    <div>
      <div className="page-head">
        <h1 className="page-head__title">Listing templates</h1>
        <span className="page-head__meta">{templates.length} templates</span>
        <div className="page-head__actions">
          <button type="button" className="btn btn-primary">
            New batch
          </button>
        </div>
      </div>
      <div className={`bc-cards ${gridClass ?? ""}`}>
        {templates.map((template) => (
          <Card key={template.name} template={template} gallery={gallery(template)} />
        ))}
      </div>
      <p className="bc-small bc-muted tc-hint">
        <InfoIcon className="bc-icon" /> To make another template, open a finished listing and
        choose Create listing template.
      </p>
    </div>
  );
}
