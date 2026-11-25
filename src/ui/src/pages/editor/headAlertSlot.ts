import { createContext } from "react";

/**
 * Where an action's error shows (`HeadAlert`). On the desktop the actions sit
 * in the head's action row, and the error beside them is where it is read. On
 * a phone they live in the head's "⋯" sheet, which closes as soon as one is
 * picked -- so an error rendered beside them would be hidden with the sheet.
 * The phone head provides an element under itself instead, and the error goes
 * there.
 *
 * `null` (the desktop, and anything outside an editor head) leaves the error
 * where its action is.
 */
export const HeadAlertSlot = createContext<HTMLElement | null>(null);
