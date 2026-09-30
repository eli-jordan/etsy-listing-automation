import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { CaretDownIcon } from "@phosphor-icons/react/dist/csr/CaretDown";
import { useEffect, useRef, useState } from "react";
import { etsyListingUrl, printifyProductUrl } from "./openOn";

/**
 * The "Open in Etsy / Printify" menu.
 *
 * One component because two screens show the same menu with the same rules --
 * the listings table's rows and the editor's action row. They were always
 * going to carry the same two links, and two copies is two chances for a URL
 * shape to drift. Only the trigger differs: the table's row has room for a
 * caret, the editor's action row names the action (`variant="action"`), and
 * there the entries need only say where they go.
 *
 * An id that is absent hides its own entry rather than rendering a dead link:
 * a listing can be published to Etsy without this workspace having ever
 * recorded a Printify product (the lockfile is per-stage), and the caller
 * decides whether a menu with no entries at all is worth showing.
 *
 * Both links go to the *thing*, not to the list it is in. A menu that lands
 * you on "all products" has told you nothing you did not already know, and
 * the ids needed to address each one are already on the row (see
 * `ListingSummary.printify_product_id`).
 *
 * The Etsy one is Shop Manager's listing **editor**, not the public
 * `etsy.com/listing/{id}` storefront URL: this tool never activates a listing
 * it creates (PRD non-goal 1 -- `state` is never sent), so a listing it has
 * just applied is still an Etsy-side draft and the public URL 404s for it.
 * The editor URL works while signed in for every state a listing can be in,
 * draft and live alike, which is why it is not conditional on status.
 */

interface Props {
  etsyListingId: number | null | undefined;
  printifyProductId: string | null | undefined;
  variant?: "row" | "action";
}

export function OpenInMenu({ etsyListingId, printifyProductId, variant = "row" }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const action = variant === "action";

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

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
