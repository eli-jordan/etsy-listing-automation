import type { ListingStatus } from "../types";

/** Labels and colours only; the status itself is derived in
 * `core/engine/status.py`. */

const LABELS: Record<ListingStatus, string> = {
  draft: "Draft",
  deployed: "Deployed",
  live: "Live",
  dirty: "Dirty",
  "pending-delete": "Pending delete",
  "pending-retire": "Pending retire",
  inactive: "Inactive",
  expired: "Expired",
};

const CLASSES: Record<ListingStatus, string> = {
  draft: "tag tag-neutral",
  deployed: "tag tag-accent",
  live: "tag tag-accent-2",
  dirty: "tag tag-dirty",
  "pending-delete": "tag tag-dirty",
  "pending-retire": "tag tag-neutral",
  inactive: "tag tag-neutral",
  expired: "tag tag-dirty",
};

const EXPLANATIONS: Record<ListingStatus, string> = {
  draft: "Never applied, or edited since the last apply and not yet on Etsy",
  deployed: "Applied — on Etsy as a draft, not published yet",
  live: "Published on Etsy, and unchanged since the last apply",
  dirty: "Published on Etsy, but edited since the last apply",
  "pending-delete": "Marked for deletion — apply will retract remotes and wipe files",
  "pending-retire": "Marked to pause — apply will set Etsy inactive",
  inactive: "Paused on Etsy — retired by us, or paused by Etsy",
  expired: "Etsy listing expired — renewing can cost money",
};

export function StatusTag({ status }: { status: ListingStatus }) {
  return (
    <span className="status-tag">
      <span className={CLASSES[status]}>{LABELS[status]}</span>
      <span className="status-tag__hint" role="tooltip">
        {EXPLANATIONS[status]}
      </span>
    </span>
  );
}

export const STATUS_LABELS = LABELS;
export const STATUS_EXPLANATIONS = EXPLANATIONS;
