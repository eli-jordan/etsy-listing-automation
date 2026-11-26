import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { type ReactNode, useRef } from "react";
import { SheetGrabber } from "../../phone/SheetGrabber";
import { useModalKeys } from "./useModalKeys";

/** The caller moves focus in. */
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
  const head = useRef<HTMLDivElement>(null);
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
        <SheetGrabber sheetRef={dialog} onDismiss={onCancel} head={head} />
        <div ref={head} className="sp-modal__alarm">
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
