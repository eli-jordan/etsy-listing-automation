import { useEffect, useId } from "react";

/**
 * An in-app confirm. `window.confirm` is browser chrome the rest of the
 * page is not, so a listing retract has to look like the rest of the shell.
 *
 * `details` is a collapsed disclosure, not always-on copy: the question is
 * the decision, the explanation is there for whoever wants it.
 */

interface Props {
  title: string;
  confirmLabel: string;
  details?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ title, confirmLabel, details, onConfirm, onCancel }: Props) {
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
      <div className="modal-dialog confirm-dialog">
        <h2 id={titleId} className="confirm-dialog__title">
          {title}
        </h2>
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
          <button type="button" className="btn btn-secondary" onClick={onConfirm} autoFocus>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
