import { CheckIcon } from "@phosphor-icons/react/dist/csr/Check";
import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { listingDesignThumbnailUrl } from "../../api/listings";
import { SheetGrabber } from "../../phone/SheetGrabber";
import { useIsPhone } from "../../phone/usePhone";
import type { ListingDesignSummary } from "../../types";

interface Props {
  title: string;
  hint: string;
  cloth: string;
  current: string | null;
  library: readonly ListingDesignSummary[];
  onPick: (ref: string) => void;
  onClose: () => void;
}

export function ArtworkPicker({ title, hint, cloth, current, library, onPick, onClose }: Props) {
  const [query, setQuery] = useState("");
  const sheet = useRef<HTMLDivElement>(null);
  const phone = useIsPhone();
  const matches = library.filter((d) => d.name.toLowerCase().includes(query.toLowerCase()));

  const dialog = (
    <div className="modal-root" role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal-backdrop" onClick={onClose} aria-hidden="true" />
      <div ref={sheet} className="modal-dialog design-picker">
        <SheetGrabber sheetRef={sheet} onDismiss={onClose} />
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
            // A phone's keyboard would cover the list being chosen from.
            autoFocus={!phone}
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
                <span className="modal-design-row__thumb design-tile" style={{ background: cloth }}>
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
  return phone ? createPortal(dialog, document.body) : dialog;
}
