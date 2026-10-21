import { type ReactNode, useEffect, useId } from "react";

/**
 * An in-app confirm. `window.confirm` is browser chrome the rest of the
 * page is not, so a listing retract has to look like the rest of the shell.
 *
 * `details` is a collapsed disclosure, not always-on copy: the question is
 * the decision, the explanation is there for whoever wants it.
 *
 * `children` is a body for a question that needs an answer before it can be
 * confirmed -- which file to keep when a light/dark pair is linked again
 * (`ChooseBaseDialog`) -- and `confirmDisabled` holds the confirm back until
 * it has one. One dialog rather than a second copy of the backdrop, the
 * Escape handling and the action row (multi-artwork plan, *Link dialog*).
 */

interface Props {
  title: string;
  confirmLabel: string;
  details?: string;
  children?: ReactNode;
  confirmDisabled?: boolean;
  /** Extra class on the dialog box, for a body that needs more room. */
  className?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  confirmLabel,
  details,
  children,
  confirmDisabled = false,
  className,
  onConfirm,
  onCancel,
}: Props) {
  const titleId = useId();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="modal-root" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="modal-backdrop" onClick={onCancel} aria-hidden="true" />
      <div className={["modal-dialog confirm-dialog", className].filter(Boolean).join(" ")}>
        <h2 id={titleId} className="confirm-dialog__title">
          {title}
        </h2>
        {children}
        {details !== undefined && (
          <details className="confirm-dialog__details">
            <summary>Details</summary>
            <p>{details}</p>
          </details>
        )}
        <div className="confirm-dialog__actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onConfirm}
            disabled={confirmDisabled}
            autoFocus
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
