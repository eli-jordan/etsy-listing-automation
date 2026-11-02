import { WarningOctagonIcon } from "@phosphor-icons/react/dist/csr/WarningOctagon";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import type { ReactNode } from "react";

/**
 * The alarm header Admin's confirmation dialogs share (the currency dialog,
 * and the template limits confirmation that reuses it): warning icon, title,
 * one line of context and the close button, which cancels.
 */
export function AlarmHeader({
  titleId,
  title,
  children,
  onCancel,
}: {
  titleId: string;
  title: ReactNode;
  children: ReactNode;
  onCancel: () => void;
}) {
  return (
    <div className="sp-modal__alarm">
      <WarningOctagonIcon size={40} weight="fill" />
      <div>
        <h2 id={titleId}>{title}</h2>
        <p>{children}</p>
      </div>
      <button type="button" className="sp-modal__close" aria-label="Cancel" onClick={onCancel}>
        <XIcon size={16} />
      </button>
    </div>
  );
}
