import { CopySimpleIcon } from "@phosphor-icons/react/dist/csr/CopySimple";
import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { UploadSimpleIcon } from "@phosphor-icons/react/dist/csr/UploadSimple";
import { type DragEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { stageDesigns, StagingRefused } from "../api/batches";
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
 * A card's footer holds Start batch, Edit, Clone and Delete -- the only
 * places those actions live, since the listing-template editor's head has
 * none (UI doc §3). Clone opens the same unsaved *name it* state Save as
 * does. Every card is also a drop target: a drop goes straight to staging
 * with that template, and a refused one lands on New batch with the template
 * chosen and the refusal shown (UI doc, closed question 2). Recent batches
 * sits below the cards (PR 5).
 */

const DELETE_DETAILS =
  "The listing template's folder and its own files are removed. Batches and listings made from it are unaffected: they keep their own copies.";

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** What a drag over a card is carrying, as far as a drag can tell: only the
 * kinds and types of its items, never their names, until the drop. */
function dragged(transfer: DataTransfer): { count: number; allPngs: boolean } {
  const files = Array.from(transfer.items ?? []).filter((item) => item.kind === "file");
  return { count: files.length, allPngs: files.every((item) => item.type === "image/png") };
}

function TemplateCard({
  template,
  onDelete,
  onDropFiles,
}: {
  template: ListingTemplateSummary;
  onDelete: () => void;
  onDropFiles: (files: File[]) => void;
}) {
  const owner = { kind: "listing-template", name: template.name } as const;
  const pricing = template.pricing_plan_name ?? "Prices set per size";
  const encoded = encodeURIComponent(template.name);
  // Every card is a drop target, and the overlay exists only during a drag
  // (UI doc §2). A counter, not a flag: entering a child fires `dragleave`
  // on the card before `dragenter` on the child.
  const [over, setOver] = useState<{ depth: number; count: number; allPngs: boolean } | null>(null);

  function enter(event: DragEvent<HTMLElement>) {
    if (!Array.from(event.dataTransfer.types ?? []).includes("Files")) return;
    event.preventDefault();
    const carrying = dragged(event.dataTransfer);
    setOver((current) => ({ ...carrying, depth: (current?.depth ?? 0) + 1 }));
  }

  function leave() {
    setOver((current) =>
      current === null || current.depth <= 1 ? null : { ...current, depth: current.depth - 1 },
    );
  }

  function drop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setOver(null);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) onDropFiles(files);
  }

  const what =
    over === null
      ? ""
      : over.allPngs
        ? plural(over.count, "PNG", "PNGs")
        : plural(over.count, "file", "files");

  return (
    <article
      className={over === null ? "bc-card" : "bc-card bc-card--over"}
      onDragEnter={enter}
      onDragOver={(event) => {
        if (over !== null) event.preventDefault();
      }}
      onDragLeave={leave}
      onDrop={drop}
    >
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
        <span className="bc-card__drop-hint">Drop PNGs or a ZIP here to start a batch</span>
      </div>
      <div className="bc-card__foot">
        <Link className="btn btn-secondary" to={`/batches/new?template=${encoded}`}>
          Start batch
        </Link>
        <Link className="btn btn-ghost" to={`/listing-templates/${encoded}`}>
          Edit
        </Link>
        <span className="bc-spacer" />
        <Link
          className="bc-quiet"
          title="Clone listing template"
          aria-label={`Clone ${template.name}`}
          to={`/listing-templates/new?from_template=${encoded}`}
        >
          <CopySimpleIcon className="bc-icon" style={{ width: 14, height: 14 }} />
        </Link>
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
      {over !== null && (
        <div className="bc-card__overlay">
          <UploadSimpleIcon className="bc-icon" />
          <strong>Drop to stage {what}</strong>
          <span className="bc-small">
            with {template.name}. You review everything before any listing is created.
          </span>
        </div>
      )}
    </article>
  );
}

export function ListingTemplatesPage() {
  const [templates, setTemplates] = useState<ListingTemplateSummary[] | null>(null);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  const navigate = useNavigate();

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

  /** A drop on a card: straight to staging, never past it (UI doc §2).
   * Refused, it shows New batch's refusal state with the template chosen,
   * the files named (closed question 2). */
  function stageOn(name: string, files: File[]) {
    setError("");
    stageDesigns(name, files)
      .then((session) => navigate(`/batches/staging/${session.id}`))
      .catch((exc: unknown) => {
        if (exc instanceof StagingRefused) {
          navigate(`/batches/new?template=${encodeURIComponent(name)}`, {
            state: { refused: { ...exc.refusal, files: files.map((file) => file.name) } },
          });
          return;
        }
        setError(exc instanceof Error ? exc.message : "The designs could not be staged.");
      });
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
              onDropFiles={(files) => stageOn(template.name, files)}
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
