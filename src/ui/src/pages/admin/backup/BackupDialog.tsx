import { type ReactNode, useRef } from "react";
import { SheetGrabber } from "../../../phone/SheetGrabber";

/** On a phone, a bottom sheet (phone/admin.css). */
export function BackupDialog({
  labelledBy,
  onDismiss,
  children,
}: {
  labelledBy: string;
  onDismiss: (() => void) | null;
  children: ReactNode;
}) {
  const sheet = useRef<HTMLDivElement>(null);
  return (
    <div className="bk-scrim">
      <div
        ref={sheet}
        className="bk-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
      >
        <SheetGrabber sheetRef={sheet} onDismiss={onDismiss} />
        {children}
      </div>
    </div>
  );
}
