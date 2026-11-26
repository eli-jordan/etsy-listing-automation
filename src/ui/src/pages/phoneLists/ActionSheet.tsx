import { PhoneSheet } from "../../phone/PhoneSheet";

export type SheetAction =
  | { kind: "link"; label: string; href: string }
  | { kind: "action"; label: string; onSelect: () => void; danger?: boolean };

export function ActionSheet({
  title,
  actions,
  onClose,
}: {
  title: string;
  actions: SheetAction[];
  onClose: () => void;
}) {
  return (
    <PhoneSheet title={title} onClose={onClose} done={false} className="m-sheet">
      <div className="m-sheet__actions">
        {actions.map((action) =>
          action.kind === "link" ? (
            <a
              key={action.label}
              className="m-sheet__action"
              href={action.href}
              target="_blank"
              rel="noreferrer"
              onClick={onClose}
            >
              {action.label}
            </a>
          ) : (
            <button
              key={action.label}
              type="button"
              className={
                action.danger ? "m-sheet__action m-sheet__action--danger" : "m-sheet__action"
              }
              onClick={() => {
                onClose();
                action.onSelect();
              }}
            >
              {action.label}
            </button>
          ),
        )}
      </div>
      <button type="button" className="m-sheet__action m-sheet__cancel" onClick={onClose}>
        Cancel
      </button>
    </PhoneSheet>
  );
}
