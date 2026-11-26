import { type ReactNode, useRef } from "react";
import { SheetGrabber } from "../../../phone/SheetGrabber";

/** On a phone, a bottom sheet (phone/admin.css). */
export function BackupDialog({
  labelledBy,
  onDismiss,
  children,
}: {
  labelledBy: string;
  /** What a swipe down does: the dialog's own Cancel or Close, or
   * null while the dialog must not be dismissed (a step still working). */
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
