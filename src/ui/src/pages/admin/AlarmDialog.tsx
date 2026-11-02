import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { type ReactNode, useRef } from "react";
import { useModalKeys } from "./useModalKeys";

/**
 * Admin's alarm-header modal, shared by the currency and template-limits
 * confirmations: the backdrop, the close button and Escape cancel, and Tab
 * stays inside. The caller moves focus in and renders the body and foot.
 */
export function AlarmDialog({
  titleId,
  title,
  lede,
  onCancel,
  children,
}: {
  titleId: string;
  title: ReactNode;
  lede: ReactNode;
  onCancel: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  useModalKeys(dialog, onCancel);
  return (
    <div className="sa-scrim" onClick={(e) => e.target === e.currentTarget && onCancel()}>
      <div
        ref={dialog}
        className="sa-modal sp-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="sp-modal__alarm">
          <WarningOctagonIcon size={40} weight="fill" />
          <div>
            <h2 id={titleId}>{title}</h2>
            <p>{lede}</p>
          </div>
          <button type="button" className="sp-modal__close" aria-label="Cancel" onClick={onCancel}>
            <XIcon size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
