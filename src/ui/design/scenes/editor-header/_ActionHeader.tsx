// The chosen editor head (round 4): an identity row (crumb or Back to batch,
// name, status, the auto-save chip with its file card, Deploy) over a quiet
// row of icon + label actions. Interactive: the Open in menu, the file card,
// Mark reviewed, the delete confirmation and its undo all work in place;
// each frame only picks the state it opens in.
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/csr/ArrowLeft";
import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { StackPlusIcon } from "@phosphor-icons/react/dist/csr/StackPlus";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "../../../src/components/ConfirmDialog";
import { StatusTag } from "../../../src/components/StatusTag";
import type { BatchContext, HeaderListing } from "./_fixtures";
import { DeployButton, EditorFrame, MenuItem, MenuPanel, useDismiss } from "./_parts";

export type Opened = "none" | "open-in" | "file-card" | "confirm-delete";

// The same rule and words as the Listings table (ListingsPage.tsx): a
// listing with anything on Printify or Etsy is *marked*, and the next deploy
// retracts it; a local-only one is deleted outright.
function hasRemotes(listing: HeaderListing) {
  return listing.etsyListingId !== null || listing.printifyProductId !== null;
}
const MARK_FOR_DELETION_DETAILS =
  "The listing stays in this table as pending-delete. The next apply will retract the Printify product — the Etsy draft goes with it — then remove the local files. Until then you can undo the mark.";
const DELETE_DETAILS =
  "The listing folder and its render cache are removed now. There is nothing on Printify or Etsy to retract. Designs, garment profiles and pricing plans stay.";

function OpenInMenu({ listing, startOpen }: { listing: HeaderListing; startOpen: boolean }) {
  const [open, setOpen] = useState(startOpen);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  return (
    <div className="hdr-anchor" ref={ref}>
      <button
        type="button"
        className="hdr-link"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ArrowSquareOutIcon /> Open in <CaretDownIcon className="hdr-link__caret" weight="bold" />
      </button>
      {open && (
        <MenuPanel label="Open in" align="left" style={{ minWidth: 170 }}>
          {listing.etsyListingId !== null && (
            <MenuItem
              icon={<span className="row-menu__badge row-menu__badge--etsy">E</span>}
              href="#etsy"
            >
              Etsy
            </MenuItem>
          )}
          {listing.printifyProductId !== null && (
            <MenuItem
              icon={<span className="row-menu__badge row-menu__badge--printify">P</span>}
              href="#printify"
            >
              Printify
            </MenuItem>
          )}
        </MenuPanel>
      )}
    </div>
  );
}

/** The auto-save chip beside the status chip; opens the listing file card. */
function SavedChip({ listing, startOpen }: { listing: HeaderListing; startOpen: boolean }) {
  const [open, setOpen] = useState(startOpen);
  const [copied, setCopied] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <div className="hdr-anchor" ref={ref}>
      <button
        type="button"
        className="hdr-saved-btn"
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Where this listing is saved"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="page-head__dot" aria-hidden="true" />
        {listing.savedAgo}
        <CaretDownIcon />
      </button>
      {open && (
        <div
          className="row-menu__panel hdr-menu--left hdr-filecard"
          role="dialog"
          aria-label="Listing file"
        >
          <div className="hdr-filecard__title">Listing file</div>
          <div className="hdr-filecard__row">
            <span className="hdr-path">{listing.path}</span>
            <button type="button" className="hdr-copy" onClick={() => setCopied(true)}>
              {copied ? <CheckIcon /> : <CopyIcon />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <dl className="hdr-filecard__facts">
            <dt>Saved</dt>
            <dd>3 mins ago, automatically</dd>
          </dl>
        </div>
      )}
    </div>
  );
}

/** A batch's review flag, as a row action like its neighbours. Pressed, it
 * reads Reviewed in the settled green; pressed again, it is back to needing
 * review -- the same flag the batch summary sets. */
function MarkReviewed({ batch }: { batch: BatchContext }) {
  const [reviewed, setReviewed] = useState(batch.reviewed);
  return (
    <button
      type="button"
      className={`hdr-link${reviewed ? " hdr-link--done" : ""}`}
      aria-pressed={reviewed}
      title={reviewed ? "Mark needs review" : undefined}
      onClick={() => setReviewed((v) => !v)}
    >
      <CheckCircleIcon weight={reviewed ? "fill" : "regular"} />
      {reviewed ? "Reviewed" : "Mark reviewed"}
    </button>
  );
}

export function ActionHeader({
  listing,
  opened = "none",
  marked = false,
  batch,
}: {
  listing: HeaderListing;
  opened?: Opened;
  marked?: boolean;
  /** Opened from a batch summary: Back to batch replaces the crumb, and Mark
   * reviewed joins the action row beside Mark for deletion. */
  batch?: BatchContext;
}) {
  const [confirming, setConfirming] = useState(opened === "confirm-delete");
  const [isMarked, setMarked] = useState(marked);
  const remote = hasRemotes(listing);
  const deleteLabel = remote ? "Mark for deletion" : "Delete";

  return (
    <EditorFrame
      listing={listing}
      head={
        <>
          <div className="page-head page-head--editor hdr-head hdr-c-head">
            {batch ? (
              <button type="button" className="hdr-back" title={`Back to the ${batch.label} batch`}>
                <ArrowLeftIcon /> Back to batch
              </button>
            ) : (
              <span className="page-head__crumb">Listings</span>
            )}
            <span className="page-head__sep">/</span>
            <h1 className="page-head__title">{listing.name}</h1>
            <StatusTag status={isMarked ? "pending-delete" : listing.status} />
            <SavedChip listing={listing} startOpen={opened === "file-card"} />
            <div className="page-head__actions">
              <DeployButton />
            </div>
          </div>
          <div className="hdr-subrow">
            <OpenInMenu listing={listing} startOpen={opened === "open-in"} />
            <button type="button" className="hdr-link">
              <StackPlusIcon /> Create listing template
            </button>
            <span className="hdr-subrow__sep" aria-hidden="true" />
            {batch && <MarkReviewed batch={batch} />}
            {isMarked ? (
              <button type="button" className="hdr-link" onClick={() => setMarked(false)}>
                <ArrowCounterClockwiseIcon /> Undo mark for deletion
              </button>
            ) : (
              <button
                type="button"
                className="hdr-link hdr-link--danger"
                onClick={() => setConfirming(true)}
              >
                <TrashIcon /> {deleteLabel}
              </button>
            )}
          </div>
          {confirming && (
            <ConfirmDialog
              title={
                remote
                  ? `Are you sure you want to mark ${listing.name} for deletion?`
                  : `Are you sure you want to delete ${listing.name}?`
              }
              confirmLabel={deleteLabel}
              details={remote ? MARK_FOR_DELETION_DETAILS : DELETE_DETAILS}
              onConfirm={() => {
                setConfirming(false);
                if (remote) setMarked(true);
              }}
              onCancel={() => setConfirming(false)}
            />
          )}
        </>
      }
    />
  );
}
