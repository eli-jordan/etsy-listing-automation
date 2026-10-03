// The chosen editor head (round 2, from v1's direction C): an identity row
// (crumb, name, status, Deploy) over a quiet action row. Interactive: every
// menu, the file card, the delete confirmation and its undo work in place;
// each frame only picks the state it opens in.
import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { StackIcon } from "@phosphor-icons/react/dist/csr/Stack";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { useCallback, useEffect, useState } from "react";
import { ConfirmDialog } from "../../../src/components/ConfirmDialog";
import { StatusTag } from "../../../src/components/StatusTag";
import type { HeaderListing } from "./_fixtures";
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
        <MenuPanel label="Open in" align="left" style={{ minWidth: 220 }}>
          {listing.etsyListingId !== null && (
            <MenuItem
              icon={<span className="row-menu__badge row-menu__badge--etsy">E</span>}
              href="#etsy"
              hint="Shop Manager listing editor"
            >
              Etsy
            </MenuItem>
          )}
          {listing.printifyProductId !== null && (
            <MenuItem
              icon={<span className="row-menu__badge row-menu__badge--printify">P</span>}
              href="#printify"
              hint="Printify product"
            >
              Printify
            </MenuItem>
          )}
        </MenuPanel>
      )}
    </div>
  );
}

function SavedFileCard({ listing, startOpen }: { listing: HeaderListing; startOpen: boolean }) {
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
        onClick={() => setOpen((v) => !v)}
      >
        <span className="page-head__dot" aria-hidden="true" />
        {listing.savedAgo}
        <CaretDownIcon />
      </button>
      {open && (
        <div
          className="row-menu__panel hdr-menu--right hdr-filecard"
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

export function ActionHeader({
  listing,
  opened = "none",
  marked = false,
}: {
  listing: HeaderListing;
  opened?: Opened;
  marked?: boolean;
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
            <span className="page-head__crumb">Listings</span>
            <span className="page-head__sep">/</span>
            <h1 className="page-head__title">{listing.name}</h1>
            <StatusTag status={isMarked ? "pending-delete" : listing.status} />
            <div className="page-head__actions">
              <DeployButton />
            </div>
          </div>
          <div className="hdr-subrow">
            <OpenInMenu listing={listing} startOpen={opened === "open-in"} />
            <button type="button" className="hdr-link">
              <StackIcon /> Create listing template
            </button>
            <span className="hdr-subrow__sep" aria-hidden="true" />
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
            <span className="hdr-subrow__end">
              <SavedFileCard listing={listing} startOpen={opened === "file-card"} />
            </span>
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
