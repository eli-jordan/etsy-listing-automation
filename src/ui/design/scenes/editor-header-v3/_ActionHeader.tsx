// The chosen editor head (round 3): an identity row (crumb or Back to batch,
// name, status, the auto-save chip with its file card, Mark reviewed, Deploy)
// over a quiet action row. The action row comes in two modes -- icon + label,
// or icon-only with a hover/focus tip. Interactive: menus, the file card, the
// delete confirmation, its undo and Mark reviewed all work in place; each
// frame only picks the state it opens in.
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/csr/ArrowLeft";
import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { StackPlusIcon } from "@phosphor-icons/react/dist/csr/StackPlus";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { ConfirmDialog } from "../../../src/components/ConfirmDialog";
import { StatusTag } from "../../../src/components/StatusTag";
import type { BatchContext, HeaderListing } from "./_fixtures";
import { DeployButton, EditorFrame, MenuItem, MenuPanel, useDismiss } from "./_parts";

export type Opened = "none" | "open-in" | "file-card" | "confirm-delete";
export type ActionMode = "labelled" | "icons";
export type TipId = "open-in" | "create-template" | "delete";

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

/** An action-row control. Labelled: icon + words. Icon-only: the icon, with
 * the words as its accessible name and a tip on hover and keyboard focus
 * that says what it does. */
function Action({
  mode,
  icon,
  label,
  tip,
  tipShown = false,
  danger = false,
  onClick,
  expanded,
  trailing,
}: {
  mode: ActionMode;
  icon: ReactNode;
  label: string;
  tip: string;
  tipShown?: boolean;
  danger?: boolean;
  onClick?: () => void;
  expanded?: boolean;
  trailing?: ReactNode;
}) {
  const tipId = useId();
  const menu = expanded !== undefined;
  const className = [
    "hdr-link",
    danger ? "hdr-link--danger" : "",
    mode === "icons" ? "hdr-link--icon" : "",
  ].join(" ");
  const button = (
    <button
      type="button"
      className={className}
      onClick={onClick}
      {...(menu ? { "aria-haspopup": "menu" as const, "aria-expanded": expanded } : {})}
      {...(mode === "icons" ? { "aria-label": label, "aria-describedby": tipId } : {})}
    >
      {icon}
      {mode === "labelled" && label}
      {trailing}
    </button>
  );
  if (mode === "labelled") return button;
  return (
    <span className={`hdr-tipwrap${tipShown ? " hdr-tipwrap--shown" : ""}${expanded ? " hdr-tipwrap--open" : ""}`}>
      {button}
      <span className="hdr-tip" role="tooltip" id={tipId}>
        <strong>{label}</strong>
        {tip}
      </span>
    </span>
  );
}

function OpenInMenu({
  listing,
  mode,
  startOpen,
  tipShown,
}: {
  listing: HeaderListing;
  mode: ActionMode;
  startOpen: boolean;
  tipShown: boolean;
}) {
  const [open, setOpen] = useState(startOpen);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  return (
    <div className="hdr-anchor" ref={ref}>
      <Action
        mode={mode}
        icon={<ArrowSquareOutIcon />}
        label="Open in"
        tip="See this listing on Etsy or Printify, in a new tab."
        tipShown={tipShown}
        expanded={open}
        onClick={() => setOpen((v) => !v)}
        trailing={<CaretDownIcon className="hdr-link__caret" weight="bold" />}
      />
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
            <dt>Last deployed</dt>
            <dd>Never</dd>
          </dl>
        </div>
      )}
    </div>
  );
}

function MarkReviewed({ batch }: { batch: BatchContext }) {
  const [reviewed, setReviewed] = useState(batch.reviewed);
  return (
    <button
      type="button"
      className="btn btn-secondary"
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
  mode = "labelled",
  opened = "none",
  marked = false,
  batch,
  tip,
}: {
  listing: HeaderListing;
  mode?: ActionMode;
  opened?: Opened;
  marked?: boolean;
  /** Opened from a batch summary: Back to batch replaces the crumb, and Mark
   * reviewed ends the action row, under Deploy. */
  batch?: BatchContext;
  /** Icon-only mode: pin one tip open, so a still frame shows it. */
  tip?: TipId;
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
          <div className={`hdr-subrow${mode === "icons" ? " hdr-subrow--icons" : ""}`}>
            <OpenInMenu
              listing={listing}
              mode={mode}
              startOpen={opened === "open-in"}
              tipShown={tip === "open-in"}
            />
            <Action
              mode={mode}
              icon={<StackPlusIcon />}
              label="Create listing template"
              tip="Start a new listing template from this listing’s variants, pricing and images."
              tipShown={tip === "create-template"}
            />
            <span className="hdr-subrow__sep" aria-hidden="true" />
            {isMarked ? (
              <Action
                mode={mode}
                icon={<ArrowCounterClockwiseIcon />}
                label="Undo mark for deletion"
                tip="Keep this listing. The next deploy will leave it on Etsy and Printify."
                tipShown={tip === "delete"}
                onClick={() => setMarked(false)}
              />
            ) : (
              <Action
                mode={mode}
                danger
                icon={<TrashIcon />}
                label={deleteLabel}
                tip={
                  remote
                    ? "Asks first. The next deploy removes it from Etsy and Printify, then deletes its files."
                    : "Asks first. Deletes this listing’s files; nothing is on Etsy or Printify yet."
                }
                tipShown={tip === "delete"}
                onClick={() => setConfirming(true)}
              />
            )}
            {batch && (
              <span className="hdr-subrow__end">
                <MarkReviewed batch={batch} />
              </span>
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
