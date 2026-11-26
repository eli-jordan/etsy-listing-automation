import { type ReactNode, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { usePhoneModal } from "./usePhoneModal";

/**
 * For work that needs the whole screen, where a sheet would leave the picture half of it.
 * On `document.body`, so the editor's sideways tab swipe never reads a drag inside it.
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
