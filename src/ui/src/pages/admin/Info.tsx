import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { INFO } from "./shopFields";

/** The field one open info card belongs to, owned by the page so opening
 * another closes the first (interactions, *Listing defaults, info cards*). */
export interface InfoState {
  open: string | null;
  toggle: (field: string) => void;
}

/** An info button and, while open, its card. Cards explain; they never save. */
export function Info({ field, info }: { field: string; info: InfoState }) {
  const copy = INFO[field];
  if (!copy) return null;
  const open = info.open === field;
  return (
    <span className="sp-info">
      <button
        type="button"
        className={open ? "s-info-btn is-open" : "s-info-btn"}
        aria-label={`About ${copy.title}`}
        aria-expanded={open}
        onClick={() => info.toggle(field)}
      >
        <InfoIcon size={15} weight={open ? "fill" : "regular"} />
      </button>
      {open && (
        <span className="s-info s-info--popover" role="note" aria-label={copy.title}>
          <span className="s-info__title">{copy.title}</span>
          <span className="s-info__what">{copy.what}</span>
          <span className="s-info__effect">
            <strong>If you change it: </strong>
            {copy.effect}
          </span>
          <span className="s-info__source">{copy.source}</span>
        </span>
      )}
    </span>
  );
}
