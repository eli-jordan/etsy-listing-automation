import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { PencilSimpleIcon } from "@phosphor-icons/react/dist/csr/PencilSimple";
import { useCallback, useState, type MouseEvent } from "react";
import { StatusTag } from "../../../src/components/StatusTag";
import { listing } from "./_fixtures";
import {
  CopyPathItem,
  DeployButton,
  EditorFrame,
  MenuDivider,
  MenuItem,
  MenuPanel,
  OpenOnItems,
  SaveAsTemplateItem,
  SavedState,
  useDismiss,
} from "./_parts";

export const meta = {
  title: "B · The name is the menu · v1",
  viewport: "laptop",
  description:
    "Retired in round 2 (C won, taking D's file card): The listing name is a file-style menu (click or right-click): Rename, Copy listing path, Open on Etsy/Printify, Save as listing template. Deploy stands alone on the right.",
};

export default function NameMenu() {
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
          <div className="hdr-anchor" ref={ref} onContextMenu={onContext}>
            <button
              type="button"
              className="hdr-name-btn"
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              <h1 className="page-head__title">{listing.name}</h1>
              <CaretDownIcon className="hdr-name-caret" weight="bold" />
            </button>
            {open && (
              <MenuPanel label="Listing" align="left" style={{ top: "calc(100% + 10px)" }}>
                <MenuItem icon={<PencilSimpleIcon />} hint="Double-click the name also works">
                  Rename…
                </MenuItem>
                <CopyPathItem listing={listing} />
                <MenuDivider />
                <OpenOnItems listing={listing} />
                <MenuDivider />
                <SaveAsTemplateItem />
              </MenuPanel>
            )}
          </div>
          <StatusTag status={listing.status} />
          <span className="page-head__meta">
            <SavedState listing={listing} />
          </span>
          <div className="page-head__actions">
            <DeployButton />
          </div>
        </div>
      }
    />
  );
}
