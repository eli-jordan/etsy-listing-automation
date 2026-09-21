import { useState, type FocusEvent, type MouseEvent } from "react";
import type { CandidateNames } from "./batchDeployPresentation";

function countDescription(names: CandidateNames): string {
  const parts: string[] = [];
  if (names.add.length > 0) parts.push(`${names.add.length} to add`);
  if (names.remove.length > 0) parts.push(`${names.remove.length} to remove`);
  if (names.edit.length > 0) parts.push(`${names.edit.length} to edit`);
  return parts.join(", ");
}

function CandidateGroup({ label, names }: { label: string; names: readonly string[] }) {
  if (names.length === 0) return null;
  const verb = label === "Add" ? "to add" : label === "Remove" ? "to remove" : "to edit";
  return (
    <div className="batch-candidate-popover__group">
      <strong>
        {label} · {names.length} {verb}
      </strong>
      <span>{names.join(", ")}</span>
    </div>
  );
}

/** The Listings-page entry point. It is intentionally unaware of navigation or
 * run creation; PR4 supplies that callback while this module owns the compact
 * accessible orientation aid. */
export function BatchCandidateControl({
  names,
  onDeploy,
  disabled = false,
}: {
  names: CandidateNames;
  onDeploy: () => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const description = countDescription(names);
  const popoverId = "batch-candidate-popover";

  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setOpen(false);
  }

  function handleMouseLeave(event: MouseEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(document.activeElement)) setOpen(false);
  }

  const label = description === "" ? "Deploy changes" : `Deploy changes: ${description}`;

  return (
    <div
      className="batch-candidate-control"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={handleMouseLeave}
      onFocus={() => setOpen(true)}
      onBlur={handleBlur}
    >
      <button
        type="button"
        className="btn btn-primary batch-candidate-control__button"
        aria-label={label}
        aria-controls={popoverId}
        aria-describedby={open ? popoverId : undefined}
        aria-expanded={open}
        disabled={disabled}
        onClick={onDeploy}
      >
        <span aria-hidden="true">↗</span>
        <span>Deploy changes</span>
        {description !== "" && (
          <span className="batch-candidate-control__counts" aria-hidden="true">
            {names.add.length > 0 && <span className="tag tag-accent-2">+{names.add.length}</span>}
            {names.remove.length > 0 && (
              <span className="tag tag-dirty">−{names.remove.length}</span>
            )}
            {names.edit.length > 0 && <span className="tag tag-accent">~{names.edit.length}</span>}
          </span>
        )}
      </button>
      {open && (
        <aside id={popoverId} className="batch-candidate-popover" role="tooltip">
          <h3>Candidate changes</h3>
          <CandidateGroup label="Add" names={names.add} />
          <CandidateGroup label="Edit" names={names.edit} />
          <CandidateGroup label="Remove" names={names.remove} />
          <p>Open to generate a fresh plan across all listings.</p>
        </aside>
      )}
    </div>
  );
}
