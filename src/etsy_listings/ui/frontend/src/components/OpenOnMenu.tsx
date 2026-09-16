import { useEffect, useRef, useState } from "react";
import { etsyListingUrl, printifyProductUrl } from "./openOn";

/**
 * The "▾ Open on Etsy / Open on Printify" menu, from the design mockup.
 *
 * One component because two screens show the same menu with the same rules --
 * the listings table's applied rows and the editor's page head. They were
 * always going to carry the same two links, and two copies is two chances for
 * a URL shape to drift.
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
}

export function OpenOnMenu({ etsyListingId, printifyProductId }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  return (
    <div className="row-menu row-menu--inline" ref={rootRef}>
      <button
        type="button"
        className="row-menu__trigger row-menu__trigger--caret"
        title="Open on Etsy or Printify"
        aria-label="Open on Etsy or Printify"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="row-menu__caret" aria-hidden="true">
          ▾
        </span>
      </button>
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
              Open on Etsy
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
              Open on Printify
            </a>
          )}
        </div>
      )}
    </div>
  );
}
