import { useState } from "react";

/**
 * The "▾ Open on Etsy / Open on Printify" menu, from the design mockup.
 *
 * One component because two screens show the same menu with the same rules --
 * the listings table's published rows and the editor's page head. They were
 * always going to carry the same two links, and two copies is two chances for
 * the Etsy URL shape to drift.
 *
 * An id that is absent hides its own entry rather than rendering a dead link:
 * a listing can be published to Etsy without this workspace having ever
 * recorded a Printify product (the lockfile is per-stage), and the caller
 * decides whether a menu with no entries at all is worth showing.
 */

interface Props {
  etsyListingId: number | null | undefined;
  printifyProductId: string | null | undefined;
}

export function OpenOnMenu({ etsyListingId, printifyProductId }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="row-menu row-menu--inline">
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
              href={`https://www.etsy.com/listing/${etsyListingId}`}
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
              href="https://printify.com/app/products"
              target="_blank"
              rel="noreferrer"
            >
              <span className="row-menu__badge row-menu__badge--printify">P</span>
              Open on Printify ({printifyProductId})
            </a>
          )}
        </div>
      )}
    </div>
  );
}
