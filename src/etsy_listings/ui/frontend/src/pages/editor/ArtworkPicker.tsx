import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { useState } from "react";
import { listingDesignThumbnailUrl } from "../../api/listings";
import type { ListingDesignSummary } from "../../types";

/**
 * The full design list, for whichever target is choosing a file (interactions
 * Part 1 §4, Part 2 §4): titled for it, hinting who prints it, with every
 * thumbnail on that target's cloth and the current file marked. Base slots
 * reach it through **Find a design…**; a colour's own design (multi-artwork
 * plan, PR 3) will open it directly.
 */

interface Props {
  title: string;
  hint: string;
  /** The cloth each thumbnail sits on. */
  tile: string;
  /** The ref the target prints now, marked **✓ Current**. */
  current: string | null;
  library: readonly ListingDesignSummary[];
  /** A workspace-rooted ref (PRD 73). */
  onPick: (ref: string) => void;
  onClose: () => void;
}

export function ArtworkPicker({ title, hint, tile, current, library, onPick, onClose }: Props) {
  const [query, setQuery] = useState("");
  const matches = library.filter((d) => d.name.toLowerCase().includes(query.toLowerCase()));

  return (
    <div className="modal-root" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal-backdrop" onClick={onClose} aria-hidden="true" />
      <div className="modal-dialog design-picker">
        <div className="modal-dialog__head">
          <h2 className="modal-dialog__title">{title}</h2>
          <button
            type="button"
            className="modal-dialog__close"
            aria-label="Close"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <p className="design-picker__hint">{hint}</p>
        <div className="design-picker__search">
          <MagnifyingGlassIcon weight="bold" aria-hidden="true" />
          <input
            className="input"
            type="text"
            placeholder="Search your designs…"
            value={query}
            autoFocus
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <div className="modal-dialog__list">
          {matches.map((d) => {
            const on = current === d.file;
            return (
              <button
                key={d.file}
                type="button"
                className={
                  on
                    ? "modal-design-row design-picker__row design-picker__row--on"
                    : "modal-design-row design-picker__row"
                }
                onClick={() => onPick(d.file)}
              >
                <span className="modal-design-row__thumb design-tile" style={{ background: tile }}>
                  <img src={listingDesignThumbnailUrl(d.name)} alt="" loading="lazy" />
                </span>
                <span className="design-picker__text">
                  <span className="modal-design-row__name">{d.name}</span>
                  <span className="modal-design-row__file">{d.file}</span>
                </span>
                {on && (
                  <span className="design-picker__current">
                    <CheckIcon weight="bold" aria-hidden="true" /> Current
                  </span>
                )}
              </button>
            );
          })}
          {matches.length === 0 && <p className="modal-empty">No designs match your search</p>}
        </div>
      </div>
    </div>
  );
}
