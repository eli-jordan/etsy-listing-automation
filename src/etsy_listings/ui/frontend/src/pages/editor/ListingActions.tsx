import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/csr/ArrowLeft";
import { ArrowsClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowsClockwise";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { PauseCircleIcon } from "@phosphor-icons/react/dist/csr/PauseCircle";
import { PlayCircleIcon } from "@phosphor-icons/react/dist/csr/PlayCircle";
import { StackPlusIcon } from "@phosphor-icons/react/dist/csr/StackPlus";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { type ReactNode, useState } from "react";
import { setReviewed, type ListingBatch } from "../../api/batches";
import { deleteListing } from "../../api/listings";
import { ActionDivider, ActionLink } from "../../components/ActionLink";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { OpenInMenu } from "../../components/OpenInMenu";
import { hasOpenTargets } from "../../components/openOn";
import type { Patch } from "../../hooks/useAutosave";
import type { ListingDetail } from "../../types";
import {
  deleteDetails,
  deleteLabel,
  deleteTitle,
  type Gesture,
  LIFECYCLE_OF,
} from "../listingLifecycle";

/**
 * The listing editor's side of its head (UI doc, *The editor head* and §8):
 * Back to batch in the breadcrumb's place, and the action row's contents.
 */

/** Back to batch, in the breadcrumb's place, only when the editor was opened
 * from the batch summary (`?batch=`). It names its batch in its tooltip, so
 * the identity row keeps its room for the name and Deploy. */
export function BackToBatch({
  batch,
  member,
  onBack,
}: {
  batch: string;
  member: ListingBatch | null;
  onBack: (batch: string) => void;
}) {
  const label = member !== null && member.batch_id === batch ? ` ${member.label}` : "";
  return (
    <button
      type="button"
      className="back-crumb"
      title={`Back to batch${label}`}
      onClick={() => onBack(batch)}
    >
      <ArrowLeftIcon aria-hidden="true" />
      Back to batch
    </button>
  );
}

/** The lifecycle gestures other than delete, as the action row words them.
 * `cancel` is the table's Undo on a pending delete. */
const GESTURES: Record<Exclude<Gesture, "delete">, { label: string; icon: ReactNode }> = {
  cancel: {
    label: "Undo mark for deletion",
    icon: <ArrowCounterClockwiseIcon aria-hidden="true" />,
  },
  retire: { label: "Retire", icon: <PauseCircleIcon aria-hidden="true" /> },
  "un-retire": { label: "Un-retire", icon: <PlayCircleIcon aria-hidden="true" /> },
  renew: { label: "Renew", icon: <ArrowsClockwiseIcon aria-hidden="true" /> },
};

/**
 * The listing's action row: Open in, Create listing template, then Mark
 * reviewed for a batch's listing and the listing's lifecycle gestures --
 * exactly the Listings table's, as the server serves them on the detail
 * (PRD 66), with the table's confirmation for deleting.
 *
 * Delete goes through `DELETE`, like the table, after flushing: a wipe
 * leaves the editor for Listings; a mark adopts what the server answered.
 * The other gestures are ordinary edits to `lifecycle`, sent at once through
 * the editor's own autosave, whose response carries the new status.
 */
export function ListingActions({
  detail,
  member,
  setMember,
  update,
  adopt,
  flush,
  onCreateTemplate,
  onDeleted,
}: {
  detail: ListingDetail;
  member: ListingBatch | null;
  setMember: (member: ListingBatch) => void;
  update: (patch: Patch) => void;
  adopt: (patch: Patch) => void;
  flush: () => Promise<void>;
  onCreateTemplate: () => void;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const name = detail.name;

  function review(next: boolean) {
    if (member === null) return;
    setReviewed(member.batch_id, member.row_id, next)
      .then((batch) => {
        setError("");
        const row = batch.rows.find((r) => r.id === member.row_id);
        setMember({ ...member, reviewed: row?.reviewed ?? next });
      })
      .catch((exc: Error) => setError(exc.message));
  }

  function runGesture(gesture: Exclude<Gesture, "delete">) {
    setError("");
    update({ lifecycle: LIFECYCLE_OF[gesture] });
    void flush();
  }

  async function confirmDelete() {
    setConfirming(false);
    setError("");
    try {
      await flush();
      const row = await deleteListing(name);
      if (row === null) {
        onDeleted();
        return;
      }
      // Already written: shown, not saved again.
      adopt({ lifecycle: "deleted", status: row.status, gestures: row.gestures });
    } catch {
      setError(`Could not ${deleteLabel(detail).toLowerCase()} ${name}`);
    }
  }

  return (
    <>
      {hasOpenTargets(detail.etsy_listing_id, detail.printify_product_id) && (
        <OpenInMenu
          variant="action"
          etsyListingId={detail.etsy_listing_id}
          printifyProductId={detail.printify_product_id}
        />
      )}
      <ActionLink icon={<StackPlusIcon aria-hidden="true" />} onClick={onCreateTemplate}>
        Create listing template
      </ActionLink>
      {(member !== null || detail.gestures.length > 0) && <ActionDivider />}
      {member !== null && (
        <ActionLink
          icon={
            <CheckCircleIcon weight={member.reviewed ? "fill" : "regular"} aria-hidden="true" />
          }
          {...(member.reviewed ? { tone: "done" as const } : {})}
          aria-pressed={member.reviewed}
          title={
            member.reviewed
              ? "Mark needs review"
              : member.reviewable
                ? undefined
                : "Available once the batch has drafted this listing"
          }
          disabled={!member.reviewable}
          onClick={() => review(!member.reviewed)}
        >
          {member.reviewed ? "Reviewed" : "Mark reviewed"}
        </ActionLink>
      )}
      {detail.gestures.map((gesture) =>
        gesture === "delete" ? (
          <ActionLink
            key={gesture}
            tone="danger"
            icon={<TrashIcon aria-hidden="true" />}
            onClick={() => setConfirming(true)}
          >
            {deleteLabel(detail)}
          </ActionLink>
        ) : (
          <ActionLink
            key={gesture}
            icon={GESTURES[gesture].icon}
            onClick={() => runGesture(gesture)}
          >
            {GESTURES[gesture].label}
          </ActionLink>
        ),
      )}
      {error && (
        <span className="action-row__error" role="alert">
          {error}
        </span>
      )}
      {confirming && (
        <ConfirmDialog
          title={deleteTitle(detail)}
          confirmLabel={deleteLabel(detail)}
          details={deleteDetails(detail)}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setConfirming(false)}
        />
      )}
    </>
  );
}
