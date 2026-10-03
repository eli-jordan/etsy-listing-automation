import type { ListingStatus } from "../types";

/**
 * Where a listing has got to, as one pill. Derived server-side
 * (`engine/status.py` -- read that for the transitions); this file owns only
 * the words and the colour.
 *
 * One component because four screens show it -- the listings table, its hover
 * card, the dashboard's counts and the editor's page head -- and a status
 * whose label depended on which screen you were looking at would be worse
 * than no label.
 *
 * The colouring is the pair of questions the badge answers at a glance: is
 * there work outstanding, and is a buyer looking at it. `draft` and `dirty`
 * both mean "the workspace has something Etsy does not", so both are warm;
 * `dirty` is the louder of the two because the stale copy is the one on sale.
 * `live` is the settled state and gets the quiet green.
 */

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

/** What each state means, for the title attribute -- the words alone do not
 * say why a listing that has been applied is back to "Draft". */
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
