import { DotsThreeIcon } from "@phosphor-icons/react/dist/csr/DotsThree";
import { useCallback, useState, type MouseEvent } from "react";
import { StatusTag } from "../../../src/components/StatusTag";
import { listing } from "./_fixtures";
import {
  CopyPathItem,
  DeployButton,
  EditorFrame,
  MenuDivider,
  MenuPanel,
  OpenOnItems,
  SaveAsTemplateItem,
  SavedState,
  useDismiss,
} from "./_parts";

export const meta = {
  title: "A · One overflow menu · v1",
  viewport: "laptop",
  description:
    "Retired in round 2 (C won, taking D's file card): Head keeps name, status, saved state and Deploy; Save as template, Open on and Copy path move into one ⋯ menu (shown open). Right-click on the name opens it too.",
};

export default function OverflowMenu() {
  const [open, setOpen] = useState(true);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);

  function onContext(event: MouseEvent) {
    event.preventDefault();
    setOpen(true);
  }

  return (
    <EditorFrame
      listing={listing}
      head={
        <div className="page-head page-head--editor hdr-head">
          <span className="page-head__crumb">Listings</span>
          <span className="page-head__sep">/</span>
          <h1 className="page-head__title" onContextMenu={onContext}>
            {listing.name}
          </h1>
          <StatusTag status={listing.status} />
          <span className="page-head__meta">
            <SavedState listing={listing} />
          </span>
          <div className="page-head__actions">
            <div className="hdr-anchor" ref={ref}>
              <button
                type="button"
                className="hdr-icon-btn"
                aria-label="More actions for this listing"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={() => setOpen((v) => !v)}
              >
                <DotsThreeIcon weight="bold" />
              </button>
              {open && (
                <MenuPanel label="Listing actions">
                  <OpenOnItems listing={listing} />
                  <MenuDivider />
                  <SaveAsTemplateItem />
                  <CopyPathItem listing={listing} />
                </MenuPanel>
              )}
            </div>
            <DeployButton />
          </div>
        </div>
      }
    />
  );
}
