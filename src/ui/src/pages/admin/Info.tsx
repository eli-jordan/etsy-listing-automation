import { InfoIcon } from "@phosphor-icons/react/dist/csr/Info";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { type CSSProperties, type RefObject, useLayoutEffect, useRef, useState } from "react";
import { useIsPhone } from "../../phone/usePhone";
import { INFO } from "./shopFields";

/** The field one open info card belongs to, owned by the page so opening
 * another closes the first (interactions, *Listing defaults, info cards*). */
export interface InfoState {
  open: string | null;
  toggle: (field: string) => void;
}

/**
 * Where a phone's card sits: under its button, across the page's content
 * width rather than 300px from the button's left edge (which ran off the
 * screen), with its arrow still pointing at the button. Measured, since the
 * button can sit anywhere in its row.
 */
function usePhoneCardPlacement(
  anchor: RefObject<HTMLSpanElement | null>,
  active: boolean,
): CSSProperties | undefined {
  const [style, setStyle] = useState<CSSProperties>();
  useLayoutEffect(() => {
    if (!active) return;
    const place = () => {
      const own = anchor.current;
      const page = own?.closest(".adm-page");
      if (!own || !page) return;
      const at = own.getBoundingClientRect();
      const content = page.getBoundingClientRect();
      setStyle({
        left: content.left - at.left,
        width: content.width,
        ["--s-info-arrow" as string]: `${at.left - content.left + at.width / 2 - 6}px`,
      });
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [anchor, active]);
  return active ? style : undefined;
}

/** An info button and, while open, its card. Cards explain; they never save. */
export function Info({ field, info }: { field: string; info: InfoState }) {
  const copy = INFO[field];
  const isPhone = useIsPhone();
  const anchor = useRef<HTMLSpanElement>(null);
  const open = info.open === field;
  const phoneStyle = usePhoneCardPlacement(anchor, isPhone && open && copy !== undefined);
  if (!copy) return null;
  return (
    <span className="sp-info" ref={anchor}>
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
        <span
          className="s-info s-info--popover"
          role="note"
          aria-label={copy.title}
          style={phoneStyle}
        >
          {isPhone && (
            <button
              type="button"
              className="s-info__close"
              aria-label={`Close ${copy.title}`}
              onClick={() => info.toggle(field)}
            >
              <XIcon size={16} />
            </button>
          )}
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
