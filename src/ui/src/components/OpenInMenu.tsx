import { useMenuDismiss } from "../hooks/useMenuDismiss";
import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { useRef, useState } from "react";
import { etsyListingUrl, printifyProductUrl } from "./openOn";

interface Props {
  etsyListingId: number | null | undefined;
  printifyProductId: string | null | undefined;
  variant?: "row" | "action";
}

export function OpenInMenu({ etsyListingId, printifyProductId, variant = "row" }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const action = variant === "action";

  useMenuDismiss(open, rootRef, setOpen);

  return (
    <div className="row-menu row-menu--inline" ref={rootRef}>
      {action ? (
        <button
          type="button"
          className="action-link"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          <ArrowSquareOutIcon aria-hidden="true" />
          Open in
          <CaretDownIcon className="action-link__caret" weight="bold" aria-hidden="true" />
        </button>
      ) : (
        <button
          type="button"
          className="row-menu__trigger row-menu__trigger--caret"
          title="Open in Etsy or Printify"
          aria-label="Open in Etsy or Printify"
          aria-expanded={open}
          onClick={() => setOpen((current) => !current)}
        >
          <span className="row-menu__caret" aria-hidden="true">
            ▾
          </span>
        </button>
      )}
      {open && (
        <div className="row-menu__panel">
          {etsyListingId !== null && etsyListingId !== undefined && (
            <a
              className="row-menu__item"
              href={etsyListingUrl(etsyListingId)}
              target="_blank"
              rel="noreferrer"
            >
              <span className="row-menu__badge row-menu__badge--etsy">E</span>
              {action ? "Etsy" : "Open in Etsy"}
            </a>
          )}
          {printifyProductId !== null && printifyProductId !== undefined && (
            <a
              className="row-menu__item"
              href={printifyProductUrl(printifyProductId)}
              target="_blank"
              rel="noreferrer"
            >
              <span className="row-menu__badge row-menu__badge--printify">P</span>
              {action ? "Printify" : "Open in Printify"}
            </a>
          )}
        </div>
      )}
    </div>
  );
}
