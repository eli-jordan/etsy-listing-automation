import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { usePhoneModal } from "./usePhoneModal";

/**
 * A view that takes the whole phone screen, over the page and its tab bar:
 * a bar with the title and Done, and its content filling what is left. For
 * work that needs all the room the screen has -- Listing Images' Adjust,
 * where a finger drags the design on the picture -- where a bottom sheet
 * would leave the picture half the screen.
 *
 * Done, Escape and Back all close it and leave the page as it was under it
 * (`usePhoneModal`, as for a sheet). There is no grab bar: a drag inside is
 * the content's own.
 *
 * On `document.body`, like `PhoneSheet`, so the editor's sideways tab swipe
 * never reads a drag inside it. The caller mounts it only while it is open,
 * and only on a phone, so its markup has no desktop styles.
 */
export function PhoneScreen({
  title,
  onClose,
  className,
  children,
}: {
  title: string;
  onClose: () => void;
  className?: string;
  children: ReactNode;
}) {
  const screen = useRef<HTMLDivElement>(null);
  const titleId = useId();
  usePhoneModal(screen, { onClose });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div
      ref={screen}
      className={["phone-screen", className].filter(Boolean).join(" ")}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <div className="phone-screen__bar">
        <h2 id={titleId} className="phone-screen__title">
          {title}
        </h2>
        <button type="button" className="phone-screen__done" onClick={onClose}>
          Done
        </button>
      </div>
      <div className="phone-screen__body">{children}</div>
    </div>,
    document.body,
  );
}
