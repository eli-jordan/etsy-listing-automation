import { type ReactNode, useContext } from "react";
import { createPortal } from "react-dom";
import { HeadAlertSlot } from "./headAlertSlot";

export function HeadAlert({ children }: { children: ReactNode }) {
  const slot = useContext(HeadAlertSlot);
  const alert = (
    <span className="action-row__error" role="alert">
      {children}
    </span>
  );
  return slot === null ? alert : createPortal(alert, slot);
}
