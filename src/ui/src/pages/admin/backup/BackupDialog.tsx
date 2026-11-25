import { type ReactNode, useRef } from "react";
import { SheetGrabber } from "../../../phone/SheetGrabber";

/**
 * The backup pages' modal frame: the scrim and the dialog box every repair,
 * restore and repository dialog shares. On a phone it is a bottom sheet
 * (phone/admin.css), modal like every sheet (`SheetGrabber`), and one with
 * `onDismiss` gets a grab bar that swipes it away; off the phone the grab
 * bar renders nothing.
 */
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
