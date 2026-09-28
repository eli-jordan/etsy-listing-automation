import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { deleteListingTemplate, listListingTemplates } from "../api/listingTemplates";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { mediaLabel, ownedTile } from "../media";
import type { ListingTemplateSummary } from "../types";
import { RecentBatches } from "./RecentBatches";

/**
 * The Listing templates page (UI doc §2), from the `templates` mockup frame:
 * one card per listing template, with its gallery, garment, colour count,
 * pricing and how many batches used it.
 *
 * Start batch and New batch open New batch (batch plan PR 2), a card's with
 * its template preselected. Edit, Clone and the card-as-drop-target arrive
 * with the listing-template editor (PR 6). Delete is here because a
 * template a seller can make is one they must be able to remove. Recent
 * batches sits below the cards (PR 5).
 */

const DELETE_DETAILS =
  "The listing template's folder and its own files are removed. Batches and listings made from it are unaffected: they keep their own copies.";

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

function TemplateCard({
  template,
  onDelete,
}: {
  template: ListingTemplateSummary;
  onDelete: () => void;
}) {
  const owner = { kind: "listing-template", name: template.name } as const;
  const pricing = template.pricing_plan_name ?? "Prices set per size";
  return (
    <article className="bc-card">
      <div className="bc-card__gallery">
        {template.media.slice(0, 3).map((entry, index) => (
          <img
            key={`${mediaLabel(entry)}-${index}`}
            src={ownedTile(entry, owner)}
            alt=""
            loading="lazy"
          />
        ))}
      </div>
      <div className="bc-card__body">
        <span className="bc-card__name">{template.name}</span>
        <span className="bc-card__facts">
          {template.garment} · {plural(template.colour_count, "colour", "colours")} · {pricing}
        </span>
        <span className="bc-card__facts">
          {plural(template.media.length, "gallery image", "gallery images")} ·{" "}
          {template.batch_count === 0
            ? "No batches yet"
            : `Used by ${plural(template.batch_count, "batch", "batches")}`}
        </span>
      </div>
      <div className="bc-card__foot">
        <Link
          className="btn btn-secondary"
          to={`/batches/new?template=${encodeURIComponent(template.name)}`}
        >
          Start batch
        </Link>
        <span className="bc-spacer" />
        <button
          type="button"
          className="bc-quiet"
          title="Delete listing template"
          aria-label={`Delete ${template.name}`}
          onClick={onDelete}
        >
          <TrashIcon className="bc-icon" style={{ width: 14, height: 14 }} />
        </button>
      </div>
    </article>
  );
}

export function ListingTemplatesPage() {
  const [templates, setTemplates] = useState<ListingTemplateSummary[] | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    listListingTemplates()
      .then((loaded) => {
        if (current) setTemplates(loaded);
      })
      .catch(() => {
        if (current) setError("Could not load listing templates");
      });
    return () => {
      current = false;
    };
  }, []);

  function confirmDelete(name: string) {
    setDeleting(null);
    deleteListingTemplate(name)
      .then(() => {
        setError("");
        setTemplates((rows) => (rows ?? []).filter((row) => row.name !== name));
      })
      .catch(() => setError(`Could not delete ${name}`));
  }

  const rows = templates ?? [];

  return (
    <>
      <div className="page-head">
        <h1 className="page-head__title">Listing templates</h1>
        {templates !== null && (
          <span className="page-head__meta">{plural(rows.length, "template", "templates")}</span>
        )}
        <div className="page-head__actions">
          <Link className="btn btn-primary" to="/batches/new">
            New batch
          </Link>
        </div>
      </div>

      {error && (
        <p className="app__status" role="alert">
          {error}
        </p>
      )}

      {rows.length > 0 && (
        <div className="bc-cards">
          {rows.map((template) => (
            <TemplateCard
              key={template.name}
              template={template}
              onDelete={() => setDeleting(template.name)}
            />
          ))}
        </div>
      )}

      {templates !== null && (
        <p className="bc-small bc-muted bc-row" style={{ marginTop: "var(--space-3)" }}>
          <InfoIcon className="bc-icon" />
          To make another template, open a finished listing and choose Save as listing template.
        </p>
      )}

      <RecentBatches />

      {deleting !== null && (
        <ConfirmDialog
          title={`Delete ${deleting}?`}
          confirmLabel="Delete"
          details={DELETE_DETAILS}
          onConfirm={() => confirmDelete(deleting)}
          onCancel={() => setDeleting(null)}
        />
      )}
    </>
  );
}
