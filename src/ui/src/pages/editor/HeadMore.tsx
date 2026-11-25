import { DotsThreeIcon } from "@phosphor-icons/react/dist/csr/DotsThree";
import { type MouseEvent, type ReactNode, useCallback, useState } from "react";
import { PhoneSheet } from "./PhoneSheet";

/**
 * The phone editor head's overflow: a "⋯" button beside the title opening a
 * bottom sheet that holds the action row the desktop head shows inline
 * (Open in, Create listing template, Reviewed, the lifecycle gestures, or a
 * template's Clone and Delete).
 *
 * Picking an action closes the sheet. The actions stay mounted while it is
 * closed, so one that asks first -- Mark for deletion -- still has its
 * confirmation after the sheet has gone.
 */
export function HeadMore({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);

  function picked(event: MouseEvent<HTMLDivElement>) {
    const target = event.target as Element;
    const action = target.closest(".action-link");
    if (action !== null && !action.hasAttribute("disabled")) setOpen(false);
  }

  return (
    <>
      <button
        type="button"
        className="head-more"
        aria-label="More actions"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        <DotsThreeIcon weight="bold" aria-hidden="true" />
      </button>
      <PhoneSheet open={open} title={title} onClose={close} className="head-more-sheet">
        <div className="head-more__list" role="group" aria-label="Actions" onClick={picked}>
          {children}
        </div>
      </PhoneSheet>
    </>
  );
}
