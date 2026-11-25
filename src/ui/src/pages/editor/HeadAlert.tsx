import { type ReactNode, useContext } from "react";
import { createPortal } from "react-dom";
import { HeadAlertSlot } from "./headAlertSlot";

/** An action's error, as the action row words it: beside the action, or on a
 * phone under the head, where it is still on screen once the "⋯" sheet that
 * held the action has closed (`HeadAlertSlot`). */
export function HeadAlert({ children }: { children: ReactNode }) {
  const slot = useContext(HeadAlertSlot);
  const alert = (
    <span className="action-row__error" role="alert">
      {children}
    </span>
  );
  return slot === null ? alert : createPortal(alert, slot);
}
