import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
} from "react";
import {
  stageBlocked,
  type ListingDetail,
  type ListingSummary,
  type RenderSnapshot,
} from "../../types";
import { ComparisonView } from "../deploy/ComparisonView";
import { buildComparison } from "../deploy/comparison";
import { PriceTable } from "../deploy/PriceTable";
import { StepStrip } from "../deploy/StepStrip";
import { planGroup, type BatchPlanGroup } from "./batchDeployPresentation";
import type { BatchListingState } from "./batchDeployState";

export type BatchDrawerMode = "review" | "applying" | "applied";

function dialogIsOpen(dialog: HTMLDialogElement): boolean {
  return dialog.open || dialog.hasAttribute("open");
}

function closeNativeDialog(dialog: HTMLDialogElement) {
  if (!dialogIsOpen(dialog)) return;
  if (typeof dialog.close === "function") dialog.close();
  else dialog.removeAttribute("open");
}

function openNativeDialog(dialog: HTMLDialogElement) {
  if (dialogIsOpen(dialog)) return;
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
}

const FALLBACK_COLLAPSED_GAP = 32;
const FALLBACK_EXPANDED_GAP = 16;
const MINIMUM_HEIGHT_RATIO = 0.3;

function cssPixels(element: HTMLElement, property: string, fallback: number): number {
  const value = Number.parseFloat(getComputedStyle(element).getPropertyValue(property));
  return Number.isFinite(value) ? value : fallback;
}

function drawerBounds(panel: HTMLElement): {
  minimum: number;
  collapsed: number;
  expanded: number;
} {
  const viewportHeight = window.innerHeight;
  const collapsedGap = cssPixels(panel, "--space-8", FALLBACK_COLLAPSED_GAP);
  const expandedGap = cssPixels(panel, "--space-4", FALLBACK_EXPANDED_GAP);
  const collapsed = Math.min(viewportHeight * 0.74, viewportHeight - collapsedGap);
  return {
    minimum: Math.min(viewportHeight * MINIMUM_HEIGHT_RATIO, collapsed),
    collapsed,
    expanded: Math.min(viewportHeight * 0.92, viewportHeight - expandedGap),
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function focusableElements(dialog: HTMLDialogElement): HTMLElement[] {
  return Array.from(
    dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [contenteditable="true"], [tabindex]:not([tabindex="-1"])',
    ),
  );
}

function groupLabel(group: BatchPlanGroup): string {
  switch (group) {
    case "add":
      return "Add to Etsy";
    case "change":
      return "Change on Etsy";
    case "remove":
      return "Remove from Etsy";
    case "attention":
      return "Needs attention";
  }
}

function drawerSummary(
  listing: BatchListingState | null,
  comparison: ReturnType<typeof buildComparison> | null,
): string {
  if (listing?.planFailure !== null && listing?.planFailure !== undefined) {
    return listing.planFailure;
  }
  if (listing?.failureMessage !== null && listing?.failureMessage !== undefined) {
    return listing.failureMessage;
  }
  const blockedStage = listing?.plan?.stage_plans.find((stage) => stageBlocked(stage) !== null);
  const blocked = blockedStage === undefined ? null : stageBlocked(blockedStage);
  return blocked ?? (comparison?.impacts.join(" · ") || "No changes planned");
}

function comparisonPreviews(listing: string, previewsRendered: ReadonlySet<string>): Set<string> {
  const prefix = `${listing}|`;
  return new Set(
    [...previewsRendered]
      .filter((key) => key.startsWith(prefix))
      .map((key) => key.slice(prefix.length)),
  );
}

function listingDesign(
  summary: Pick<ListingSummary, "design"> | null | undefined,
): ListingDetail["design"] {
  return summary?.design === null || summary?.design === undefined
    ? {}
    : { default: summary.design };
}

/** A real modal drawer, kept independent from the eventual review page so PR4
 * can compose it without taking ownership of its focus or diff semantics. */
export function BatchListingDrawer({
  open,
  listing,
  summary,
  mode = "review",
  previewsRendered = new Set(),
  renderSnapshot = null,
  collapsed = false,
  imageUrlForRef,
  onClose,
}: {
  open: boolean;
  listing: BatchListingState | null;
  summary?: Pick<ListingSummary, "name" | "design"> | null;
  mode?: BatchDrawerMode;
  previewsRendered?: ReadonlySet<string>;
  renderSnapshot?: RenderSnapshot | null;
  collapsed?: boolean;
  imageUrlForRef?: (ref: string) => string | null;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const suppressHandleClickRef = useRef(false);
  const [entered, setEntered] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [drawerHeight, setDrawerHeight] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const name = summary?.name ?? listing?.listing ?? "Listing";
  const plan = listing?.plan ?? listing?.reviewedPlan ?? null;
  const titleId = `batch-drawer-title-${name.replace(/[^a-z0-9]+/gi, "-")}`;
  const comparison = useMemo(() => (plan === null ? null : buildComparison(plan)), [plan]);
  const category = groupLabel(planGroup(plan, listing?.planFailure ?? null));
  const summaryText = drawerSummary(listing, comparison);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return;

    if (open) {
      restoreFocusRef.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      openNativeDialog(dialog);
      // showModal() focuses the first control and scrolls the translated panel into view.
      dialog.scrollTop = 0;
      closeRef.current?.focus({ preventScroll: true });
      const frame = window.requestAnimationFrame(() => setEntered(true));
      return () => window.cancelAnimationFrame(frame);
    }

    closeNativeDialog(dialog);
    const frame = window.requestAnimationFrame(() => setEntered(false));
    const previous = restoreFocusRef.current;
    restoreFocusRef.current = null;
    previous?.focus();
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  function handleKeyDown(event: KeyboardEvent<HTMLDialogElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const dialog = dialogRef.current;
    if (dialog === null) return;
    const focusable = focusableElements(dialog);
    if (focusable.length === 0) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }

  function handleScrimClick(event: MouseEvent<HTMLDialogElement>) {
    if (event.target === event.currentTarget) onClose();
  }

  function handleHandlePointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return;
    const panel = panelRef.current;
    if (panel === null) return;
    const bounds = drawerBounds(panel);
    const measuredHeight = panel.getBoundingClientRect().height;
    dragRef.current = {
      startY: event.clientY,
      startHeight: clamp(
        measuredHeight || drawerHeight || (expanded ? bounds.expanded : bounds.collapsed),
        bounds.minimum,
        bounds.expanded,
      ),
    };
    suppressHandleClickRef.current = false;
    setDragging(true);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handleHandlePointerMove(event: PointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    const panel = panelRef.current;
    if (drag === null || panel === null) return;
    const bounds = drawerBounds(panel);
    const height = clamp(
      drag.startHeight - (event.clientY - drag.startY),
      bounds.minimum,
      bounds.expanded,
    );
    setDrawerHeight(height);
    setExpanded(height > (bounds.collapsed + bounds.expanded) / 2);
    if (Math.abs(event.clientY - drag.startY) >= 4) suppressHandleClickRef.current = true;
  }

  function handleHandlePointerEnd(event: PointerEvent<HTMLButtonElement>) {
    dragRef.current = null;
    setDragging(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  }

  function handleHandleClick() {
    if (suppressHandleClickRef.current) {
      suppressHandleClickRef.current = false;
      return;
    }
    const panel = panelRef.current;
    if (panel === null) return;
    const nextExpanded = !expanded;
    setExpanded(nextExpanded);
    const bounds = drawerBounds(panel);
    setDrawerHeight(nextExpanded ? bounds.expanded : bounds.collapsed);
  }

  return (
    <dialog
      ref={dialogRef}
      className={`batch-drawer-dialog${entered ? " batch-drawer-dialog--entered" : ""}`}
      aria-modal="true"
      aria-labelledby={titleId}
      aria-hidden={!open}
      onClick={handleScrimClick}
      onKeyDown={handleKeyDown}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div
        ref={panelRef}
        className={`batch-drawer-panel${expanded ? " batch-drawer-panel--expanded" : ""}${dragging ? " batch-drawer-panel--dragging" : ""}`}
        style={drawerHeight === null ? undefined : { height: `${drawerHeight}px` }}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="batch-drawer__head">
          <div>
            <span className="dv-eyebrow">{category}</span>
            <h2 id={titleId}>{name}</h2>
            <p>{summaryText}</p>
          </div>
          <button ref={closeRef} type="button" className="btn btn-secondary" onClick={onClose}>
            Close
          </button>
        </header>
        <button
          type="button"
          className="batch-drawer__handle"
          aria-label={expanded ? "Collapse drawer" : "Expand drawer"}
          aria-expanded={expanded}
          aria-controls={`${titleId}-panel`}
          onClick={handleHandleClick}
          onPointerDown={handleHandlePointerDown}
          onPointerMove={handleHandlePointerMove}
          onPointerUp={handleHandlePointerEnd}
          onPointerCancel={handleHandlePointerEnd}
        >
          <span aria-hidden="true" />
        </button>
        <div id={`${titleId}-panel`} className="batch-drawer__body">
          {plan === null || comparison === null ? (
            <div className="batch-drawer__empty">
              <h3>{name}</h3>
              <p>The reviewed plan is no longer available for this listing.</p>
            </div>
          ) : (
            <>
              <StepStrip
                plan={plan}
                stageRuntime={listing?.stageRuntime ?? {}}
                heading={
                  mode === "applied"
                    ? "What apply did"
                    : mode === "applying"
                      ? "Live progress for this listing"
                      : "What apply will do"
                }
              />
              <ComparisonView
                comparison={comparison}
                listing={{ name, design: listingDesign(summary) }}
                renderSnapshot={renderSnapshot}
                previewsRendered={comparisonPreviews(name, previewsRendered)}
                collapsed={collapsed}
                etsyListingId={plan.etsy_listing_id}
                {...(imageUrlForRef === undefined ? {} : { imageUrlForRef })}
              />
              <PriceTable rows={comparison?.priceRows ?? []} />
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}
