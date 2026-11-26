import { ArrowCounterClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowCounterClockwise";
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/csr/ArrowLeft";
import { ArrowSquareOutIcon } from "@phosphor-icons/react/dist/csr/ArrowSquareOut";
import { ArrowsClockwiseIcon } from "@phosphor-icons/react/dist/csr/ArrowsClockwise";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { PauseCircleIcon } from "@phosphor-icons/react/dist/csr/PauseCircle";
import { PlayCircleIcon } from "@phosphor-icons/react/dist/csr/PlayCircle";
import { StackPlusIcon } from "@phosphor-icons/react/dist/csr/StackPlus";
import { TrashIcon } from "@phosphor-icons/react/dist/csr/Trash";
import { type ReactNode, useState } from "react";
import { createPortal } from "react-dom";
import { setReviewed, type ListingBatch } from "../../api/batches";
import { deleteListing } from "../../api/listings";
import { ActionDivider, ActionLink } from "../../components/ActionLink";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { OpenInMenu } from "../../components/OpenInMenu";
import { etsyListingUrl, hasOpenTargets, printifyProductUrl } from "../../components/openOn";
import { useIsPhone } from "../../phone/usePhone";
import { HeadAlert } from "./HeadAlert";
import type { Patch } from "../../hooks/listingAutosave";
import type { Settled } from "../../hooks/writeLoop";
import type { ListingDetail } from "../../types";
import {
  deleteDetails,
  deleteLabel,
  deleteTitle,
  type Gesture,
  LIFECYCLE_OF,
} from "../listingLifecycle";

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

const GESTURES: Record<Exclude<Gesture, "delete">, { label: string; icon: ReactNode }> = {
  cancel: {
    label: "Undo mark for deletion",
    icon: <ArrowCounterClockwiseIcon aria-hidden="true" />,
  },
  retire: { label: "Retire", icon: <PauseCircleIcon aria-hidden="true" /> },
  "un-retire": { label: "Un-retire", icon: <PlayCircleIcon aria-hidden="true" /> },
  renew: { label: "Renew", icon: <ArrowsClockwiseIcon aria-hidden="true" /> },
};

function reviewTitle(member: ListingBatch): string | undefined {
  if (member.reviewed) return "Mark needs review";
  return member.reviewable ? undefined : "Available once the batch has drafted this listing";
}

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
  flush: () => Promise<Settled>;
  onCreateTemplate: () => void;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const name = detail.name;
  const phone = useIsPhone();

  const review = useReview(member, setMember, setError);

  function runGesture(gesture: Exclude<Gesture, "delete">) {
    setError("");
    update({ lifecycle: LIFECYCLE_OF[gesture] });
    void flush();
  }

  async function confirmDelete() {
    setConfirming(false);
    setError("");
    try {
      // Waited for, so no write crosses the delete. Whether it landed does not
      // matter: an edit that would not save goes with the listing.
      await flush();
      const row = await deleteListing(name);
      if (row === null) {
        onDeleted();
        return;
      }
      adopt({ lifecycle: "deleted", status: row.status, gestures: row.gestures });
    } catch {
      setError(`Could not ${deleteLabel(detail).toLowerCase()} ${name}`);
    }
  }

  return (
    <>
      {hasOpenTargets(detail.etsy_listing_id, detail.printify_product_id) &&
        (phone ? (
          <OpenInLinks
            etsyListingId={detail.etsy_listing_id}
            printifyProductId={detail.printify_product_id}
          />
        ) : (
          <OpenInMenu
            variant="action"
            etsyListingId={detail.etsy_listing_id}
            printifyProductId={detail.printify_product_id}
          />
        ))}
      <ActionLink icon={<StackPlusIcon aria-hidden="true" />} onClick={onCreateTemplate}>
        Create listing template
      </ActionLink>
      {((member !== null && !phone) || detail.gestures.length > 0) && <ActionDivider />}
      {/* On a phone it sits beside Deploy instead (ReviewButton). */}
      {member !== null && !phone && (
        <ActionLink
          icon={
            <CheckCircleIcon weight={member.reviewed ? "fill" : "regular"} aria-hidden="true" />
          }
          {...(member.reviewed ? { tone: "done" as const } : {})}
          aria-pressed={member.reviewed}
          title={reviewTitle(member)}
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
      {error && <HeadAlert>{error}</HeadAlert>}
      {confirming && (
        <OnBodyOnPhone phone={phone}>
          <ConfirmDialog
            title={deleteTitle(detail)}
            confirmLabel={deleteLabel(detail)}
            details={deleteDetails(detail)}
            onConfirm={() => void confirmDelete()}
            onCancel={() => setConfirming(false)}
          />
        </OnBodyOnPhone>
      )}
    </>
  );
}

function useReview(
  member: ListingBatch | null,
  setMember: (member: ListingBatch) => void,
  setError: (error: string) => void,
) {
  return (next: boolean) => {
    if (member === null) return;
    setReviewed(member.batch_id, member.row_id, next)
      .then((batch) => {
        setError("");
        const row = batch.rows.find((r) => r.id === member.row_id);
        setMember({ ...member, reviewed: row?.reviewed ?? next });
      })
      .catch((exc: Error) => setError(exc.message));
  };
}

/**
 * Mark reviewed on a phone: a button beside Deploy rather than a row of the
 * "⋯" sheet, because reviewing is what a batch's listing is opened for, and
 * the two are the head's next steps. Pressed, it reads Reviewed, and a
 * second press marks it as needing review again.
 */
export function ReviewButton({
  member,
  setMember,
}: {
  member: ListingBatch;
  setMember: (member: ListingBatch) => void;
}) {
  const [error, setError] = useState("");
  const review = useReview(member, setMember, setError);
  const label = member.reviewed ? "Reviewed" : "Mark reviewed";
  return (
    <>
      <button
        type="button"
        className={
          member.reviewed
            ? "btn btn-secondary review-btn review-btn--done"
            : "btn btn-secondary review-btn"
        }
        aria-label={label}
        aria-pressed={member.reviewed}
        title={reviewTitle(member)}
        disabled={!member.reviewable}
        onClick={() => review(!member.reviewed)}
      >
        <CheckCircleIcon weight={member.reviewed ? "fill" : "regular"} aria-hidden="true" />
        <span className="review-btn__label">{label}</span>
      </button>
      {error && <HeadAlert>{error}</HeadAlert>}
    </>
  );
}

/** On a phone the actions live in the head's "⋯" sheet, which closes as
 * soon as one is picked; the delete confirmation goes on the page body so it
 * stays on screen after the sheet holding its trigger is hidden. */
function OnBodyOnPhone({ phone, children }: { phone: boolean; children: ReactNode }) {
  return phone ? createPortal(children, document.body) : children;
}

function OpenInLinks({
  etsyListingId,
  printifyProductId,
}: {
  etsyListingId: number | null | undefined;
  printifyProductId: string | null | undefined;
}) {
  return (
    <>
      {etsyListingId !== null && etsyListingId !== undefined && (
        <a
          className="action-link"
          href={etsyListingUrl(etsyListingId)}
          target="_blank"
          rel="noreferrer"
        >
          <ArrowSquareOutIcon aria-hidden="true" />
          Open in Etsy
        </a>
      )}
      {printifyProductId !== null && printifyProductId !== undefined && (
        <a
          className="action-link"
          href={printifyProductUrl(printifyProductId)}
          target="_blank"
          rel="noreferrer"
        >
          <ArrowSquareOutIcon aria-hidden="true" />
          Open in Printify
        </a>
      )}
    </>
  );
}
