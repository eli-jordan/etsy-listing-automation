import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { CopyIcon } from "@phosphor-icons/react/dist/csr/Copy";
import { StackIcon } from "@phosphor-icons/react/dist/csr/Stack";
import { useCallback, useEffect, useState } from "react";
import { StatusTag } from "../../../src/components/StatusTag";
import { listing } from "./_fixtures";
import { DeployButton, EditorFrame, MenuPanel, OpenOnItems, useDismiss } from "./_parts";

export const meta = {
  title: "D · Grouped buttons + file card · v1",
  viewport: "laptop",
  description:
    "Retired in round 2 (C won, taking D's file card): Smallest change: Save as template and Open on join Deploy as one right-aligned button group; the path moves into a file card that opens from Saved 3 mins ago (shown open).",
};

function OpenOnButton() {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  return (
    <div className="hdr-anchor" ref={ref}>
      <button
        type="button"
        className="hdr-icon-btn hdr-icon-btn--wide"
        aria-label="Open on Etsy or Printify"
        title="Open on Etsy or Printify"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ArrowSquareOutIcon />
        <CaretDownIcon className="hdr-icon-btn__caret" weight="bold" />
      </button>
      {open && (
        <MenuPanel label="Open on">
          <OpenOnItems listing={listing} />
        </MenuPanel>
      )}
    </div>
  );
}

function SavedFileCard() {
  const [open, setOpen] = useState(true);
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

export default function GroupedButtons() {
  return (
    <EditorFrame
      listing={listing}
      head={
        <div className="page-head page-head--editor hdr-head">
          <span className="page-head__crumb">Listings</span>
          <span className="page-head__sep">/</span>
          <h1 className="page-head__title">{listing.name}</h1>
          <StatusTag status={listing.status} />
          <SavedFileCard />
          <div className="page-head__actions">
            <button type="button" className="btn btn-secondary">
              <StackIcon /> Save as template
            </button>
            <OpenOnButton />
            <DeployButton />
          </div>
        </div>
      }
    />
  );
}
