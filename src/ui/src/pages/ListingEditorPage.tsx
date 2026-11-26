import { type ReactNode, type RefObject, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getListing, getListingDraft } from "../api/listings";
import { EditableName } from "../components/EditableName";
import { StatusTag } from "../components/StatusTag";
import { useAutosave } from "../hooks/useAutosave";
import { usePager } from "../phone/usePager";
import { useIsPhone } from "../phone/usePhone";
import type { Settled } from "../hooks/writeLoop";
import { type MediaOwner, refName } from "../media";
import type { DesignMap, Issue, IssueTab, ListingDetail } from "../types";
import type { AiSeoMode } from "./editor/aiSeo/useAiSeoMode";
import { AiWorkflowIndicator } from "./editor/aiSeo/AiWorkflowIndicator";
import { useAiSeoMode } from "./editor/aiSeo/useAiSeoMode";
import { DeployControl } from "./editor/DeployControl";
import { ArtworkStrip } from "./editor/ArtworkStrip";
import { representative, type SlotTarget, type Tone } from "./editor/artwork";
import { DesignSelect } from "./editor/DesignSelect";
import { DEFAULT_PREVIEW, type PreviewDesign, previewArtwork } from "./editor/previewDesign";
import { DetailsTab } from "./editor/DetailsTab";
import { PricingTab } from "./editor/PricingTab";
import { IssuesBanner } from "./editor/IssuesBanner";
import { withoutPosition } from "./editor/positions/document";
import { BackToBatch, ListingActions, ReviewButton } from "./editor/ListingActions";
import { HeadAlertSlot } from "./editor/headAlertSlot";
import { HeadMore } from "./editor/HeadMore";
import { ImagesTab } from "./editor/ImagesTab";
import { metaFor } from "./editor/saveMeta";
import { useListingBatch } from "./editor/useListingBatch";
import { VariantsTab } from "./editor/VariantsTab";
import { isNullableString, useViewScroll, useViewState, viewScope } from "./editor/editorView";

type Tab = IssueTab;

/** `lead` is the part of a label the phone's one-row tab strip drops
 * ("Listing Images" reads "Images" there); the desktop shows it all. */
const TABS: { id: Tab; lead?: string; label: string }[] = [
  { id: "variants", label: "Variants" },
  { id: "pricing", label: "Pricing" },
  { id: "images", lead: "Listing ", label: "Images" },
  { id: "details", lead: "Listing ", label: "Details" },
];

const TAB_IDS = TABS.map((t) => t.id);

function isTab(value: unknown): value is Tab {
  return TABS.some((t) => t.id === value);
}

function badgeFor(issues: Issue[], tab: Tab): { block: number; warn: number } {
  const scoped = issues.filter((i) => i.tab === tab);
  return {
    block: scoped.filter((i) => i.severity === "block").length,
    warn: scoped.filter((i) => i.severity === "warn").length,
  };
}

export function ListingEditorPage() {
  const { name } = useParams<{ name?: string }>();
  const navigate = useNavigate();
  const routeName = name ?? null;

  // The listing as the editor that just named it already had it. Naming one
  // crosses from `/listings/new` to `/listings/:name` -- a different route
  // *pattern*, which React Router remounts across no matter how carefully this
  // component tries to track what it is showing -- so the freshly written
  // document rides along in the navigation instead of being fetched back.
  // That is a round trip saved and, more to the point, no window in which a
  // GET could answer with a document older than the save the unmounting editor
  // just flushed.
  const handed = (useLocation().state as { listing?: ListingDetail } | null)?.listing ?? null;
  // Used once, then dropped from the browser's history entry: a reload keeps
  // history state, and the handed document is the listing as it was named,
  // long since changed on disk. `window.history` directly, not `navigate`,
  // because React Router does not watch it -- this page must not re-render
  // (and remount the editor) over it; only the next load must not see it.
  useEffect(() => {
    if (handed === null) return;
    const entry = window.history.state as Record<string, unknown> | null;
    if (entry !== null && typeof entry === "object" && "usr" in entry) {
      window.history.replaceState({ ...entry, usr: null }, "");
    }
  }, [handed]);
  const [fetched, setFetched] = useState<ListingDetail | null>(null);
  const [loadError, setLoadError] = useState("");

  // Whichever of the two is about the listing the URL currently names. Matching
  // rather than clearing on change is what makes showing a stale document
  // impossible: one left over from a previous listing simply does not match. (A
  // draft's name is `""`, which is never a route name.)
  const matchingFetched = fetched !== null && (fetched.name || null) === routeName ? fetched : null;
  const initial = handed !== null && handed.name === routeName ? handed : matchingFetched;

  useEffect(() => {
    if (initial !== null) return;
    let current = true;
    (routeName === null ? getListingDraft() : getListing(routeName))
      .then((loaded) => {
        if (!current) return;
        // Cleared here rather than at the top of the effect: a failure is about
        // one listing, and the thing that ends it is another one loading.
        setLoadError("");
        setFetched(loaded);
      })
      .catch(() => {
        if (!current) return;
        setLoadError(
          routeName === null
            ? "could not start a new listing"
            : `failed to load listing ${routeName}`,
        );
      });
    return () => {
      current = false;
    };
  }, [routeName, initial]);

  if (loadError) return <p className="app__status">{loadError}</p>;
  if (initial === null) return <p className="app__status">Loading…</p>;

  return (
    <ListingEditorPageContent
      // Deliberately unkeyed. A genuine listing switch already remounts --
      // `initial` goes `null` above while the new one loads, which unmounts
      // this whole subtree -- so the key only ever forced the *extra*
      // remount that naming a draft caused, where `handed` keeps `initial`
      // non-null. `useAutosave` handles a name change itself (`commitName`
      // updates its own name, `detail` and `save` before `onNamed`
      // fires), so that remount threw away state for nothing. It is not
      // nothing any more: ADR-0003's chain is armed when a design is attached,
      // which on a new listing is usually *before* it is named, and a
      // remount there would disarm it before the save that fires it.
      name={routeName}
      initial={initial}
      onBack={() => navigate("/listings")}
      onNamed={(next, fresh) =>
        navigate(`/listings/${encodeURIComponent(next)}`, {
          replace: true,
          state: { listing: fresh },
        })
      }
    />
  );
}

function ListingEditorPageContent({
  name,
  initial,
  onBack,
  onNamed,
}: {
  name: string | null;
  initial: ListingDetail;
  onBack: () => void;
  onNamed: (name: string, fresh: ListingDetail) => void;
}) {
  const { detail, update, adopt, flush, commitName, save } = useAutosave(name, initial, {
    onNamed,
  });
  const navigate = useNavigate();
  const fromBatch = useSearchParams()[0].get("batch");
  const [member, setMember] = useListingBatch(detail.name);
  /** A name the design pick chose, before the listing exists under it. */
  const [pickedName, setPickedName] = useState("");
  /** A name the seller has started typing but not committed. `detail.name` is
   * still `""` at that point -- an uncommitted name is not the listing's name
   * -- so without this a design pick would overwrite what they were typing. */
  const [typedName, setTypedName] = useState("");
  const aiSeo = useAiSeoMode(detail, update, flush, save, adopt);
  const phone = useIsPhone();

  function changeDesign(next: DesignMap) {
    update({ design: next });
    const chosen = representative(next);
    if (chosen === null || chosen === representative(detail.design)) return;
    if (detail.name === "" && typedName.trim() === "") {
      const named = refName(chosen);
      setPickedName(named);
      commitName(named);
    }
    aiSeo.run.arm();
  }

  /** Goes to `url` once the file holds what is on screen. Whatever is there
   * reads the file, and this editor is the one place the edit still exists,
   * so an edit that cannot be written keeps the seller here, where the page
   * head says why. */
  function whenWritten(url: string) {
    void flush().then((settled) => {
      if (settled.written) navigate(url);
    });
  }

  return (
    <ListingEditorShell
      detail={detail}
      update={update}
      flush={flush}
      onDesignChange={changeDesign}
      aiSeo={aiSeo}
      head={
        <EditorHead
          detail={detail}
          onBack={onBack}
          flush={flush}
          crumb={
            fromBatch !== null && (
              <BackToBatch
                batch={fromBatch}
                member={member}
                onBack={(batch) => whenWritten(`/batches/${encodeURIComponent(batch)}`)}
              />
            )
          }
          actions={
            detail.name !== "" && (
              <ListingActions
                detail={detail}
                member={member}
                setMember={setMember}
                update={update}
                adopt={adopt}
                flush={flush}
                onCreateTemplate={() => whenWritten(saveAsUrl(detail.name))}
                onDeleted={() => navigate(afterDelete(fromBatch), { replace: true })}
              />
            )
          }
          review={
            phone &&
            member !== null &&
            detail.name !== "" && <ReviewButton member={member} setMember={setMember} />
          }
          activity={<AiWorkflowIndicator steps={aiSeo.run.steps} running={aiSeo.run.busy} />}
          title={
            <EditableName
              value={name ?? pickedName}
              onCommit={commitName}
              onDraftChange={setTypedName}
              error={
                save.kind === "name-taken"
                  ? { name: save.name, message: "that name is already taken" }
                  : null
              }
              busy={save.kind === "saving"}
            />
          }
          meta={metaFor(save, name, "listing", phone)}
        />
      }
    />
  );
}

function afterDelete(fromBatch: string | null): string {
  return fromBatch === null ? "/listings" : `/batches/${encodeURIComponent(fromBatch)}`;
}

/** Where Create listing template opens the unsaved template (UI doc §1). */
function saveAsUrl(listing: string): string {
  return `/listing-templates/new?from_listing=${encodeURIComponent(listing)}`;
}

export function EditorHead({
  detail,
  onBack,
  title,
  meta,
  flush,
  activity,
  crumb,
  actions,
  review,
  kind = "listing",
}: {
  detail: ListingDetail;
  onBack: () => void;
  title: ReactNode;
  meta: ReactNode;
  flush: () => Promise<Settled>;
  activity?: ReactNode;
  crumb?: ReactNode;
  actions?: ReactNode;
  /** Mark reviewed, beside Deploy, on a phone (`ReviewButton`); the desktop
   * keeps it in the action row. */
  review?: ReactNode;
  kind?: "listing" | "listing-template";
}) {
  const listing = kind === "listing";
  const isPhone = useIsPhone();
  const inlineActions = isPhone ? null : actions;
  const [alertSlot, setAlertSlot] = useState<HTMLDivElement | null>(null);

  return (
    <HeadAlertSlot value={isPhone ? alertSlot : null}>
      <div className={inlineActions ? "editor-head editor-head--actions" : "editor-head"}>
        <div className="page-head page-head--editor">
          {crumb || (
            <span className="page-head__crumb" onClick={onBack}>
              {listing ? "Listings" : "Listing templates"}
            </span>
          )}
          <span className="page-head__sep">/</span>
          {title}
          {isPhone && actions && <HeadMore title={detail.name || "Actions"}>{actions}</HeadMore>}

          {listing && <StatusTag status={detail.status} />}
          <span className="page-head__meta">{meta}</span>
          {activity}

          {listing && detail.name !== "" && (
            <div className="page-head__actions dv-head-actions">
              {review}
              <DeployControl name={detail.name} flush={flush} />
            </div>
          )}
        </div>
        {isPhone && <div className="head-alerts" ref={setAlertSlot} />}
        {inlineActions && (
          <div className="action-row" role="group" aria-label="Actions">
            {inlineActions}
          </div>
        )}
      </div>
    </HeadAlertSlot>
  );
}

type ShellProps = {
  detail: ListingDetail;
  update: (patch: Record<string, unknown>) => void;
  flush: () => void;
  head: ReactNode;
} & (
  | {
      kind?: "listing";
      onDesignChange: (next: DesignMap) => void;
      /** Owned by `ListingEditorPageContent`, not by this shell and not by
       * `DetailsTab`: a run outlives the tab it was started from --
       * switching to Variants unmounts the tab. */
      aiSeo: AiSeoMode;
    }
  | {
      kind: "listing-template";
      /** Whose `./` files the Images tab shows: the template's, or -- not
       * saved yet -- its source's, through `copies`. */
      owner: MediaOwner | null;
    }
);

function ShellIssues({
  template,
  issues,
  tab,
  onJumpTo,
  onRemovePosition,
}: {
  template: boolean;
  issues: ListingDetail["issues"];
  tab: Tab;
  onJumpTo: (tab: Tab) => void;
  onRemovePosition?: (template: string, placement: string | null) => void;
}) {
  if (!template) {
    return (
      <IssuesBanner
        issues={issues}
        activeTab={tab}
        onJumpTo={onJumpTo}
        {...(onRemovePosition === undefined ? {} : { onRemovePosition })}
      />
    );
  }
  // A block is what stops the save; warnings alone stop
  // nothing, so they are not told the file is being held back.
  const blocked = issues.some((issue) => issue.severity === "block");
  return (
    <IssuesBanner
      issues={issues}
      activeTab={tab}
      onJumpTo={onJumpTo}
      subject="listing-template"
      when={
        blocked
          ? "Last complete version is kept until then"
          : "Checked against this template’s own configuration"
      }
    />
  );
}

export function ListingEditorShell(props: ShellProps) {
  const { detail, update, flush, head } = props;
  const template = props.kind === "listing-template";
  const aiSeo = props.kind === "listing-template" ? null : props.aiSeo;
  const scope = viewScope(template ? "listing-template" : "listing", detail.name);
  const [tab, setTab] = useViewState<Tab>(scope, "tab", "variants", isTab);
  useViewScroll(scope);
  /** Which base slot's Recent designs panel is open. Here, not in the strip,
   * so the card under the Variants stage can open one too (interactions
   * Part 2 §2). */
  const [openSlot, setOpenSlot] = useState<SlotTarget | null>(null);
  /** The colour on the Variants stage. Here, not in the tab, so the strip's
   * "Also printing their own design" names can preview one too -- and so
   * leaving Variants and coming back keeps the colour the seller chose. */
  const [previewed, setPreviewed] = useViewState<string | null>(
    scope,
    "previewed",
    null,
    isNullableString,
  );

  function previewColour(colour: string) {
    setPreviewed(colour);
    if (tab !== "variants") pickTab("variants");
  }

  /** The card under the stage's fix for an empty slot: that slot's panel,
   * scrolled into view, because filling it fixes every colour that needs it. */
  function chooseSlot(tone: Tone) {
    setOpenSlot({ kind: "slot", tone });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const [preview, setPreview] = useState<PreviewDesign>(DEFAULT_PREVIEW);
  const artwork = template ? previewArtwork(preview) : undefined;
  const owner = props.kind === "listing-template" ? props.owner : undefined;

  const isPhone = useIsPhone();
  const tabStrip = useRef<HTMLDivElement>(null);
  const pager = useRef<HTMLDivElement>(null);

  function pickTab(next: Tab) {
    flush();
    if (isPhone && next !== tab) toTabTop();
    setTab(next);
  }

  /** A phone tab change starts the new tab at its top -- under the stuck tab
   * strip when the page had scrolled past it. The pager slides it in. */
  function toTabTop() {
    const strip = tabStrip.current;
    const content = pager.current;
    if (strip !== null && content !== null) {
      // Where the content starts once it sits just under the strip: the
      // strip's own position says nothing while it is stuck.
      const gap = Number.parseFloat(window.getComputedStyle(strip).marginBottom) || 0;
      const top =
        window.scrollY +
        content.getBoundingClientRect().top -
        strip.getBoundingClientRect().bottom -
        gap;
      if (top < window.scrollY) window.scrollTo({ top });
    }
  }

  /** The issues banner's Fix. On a phone, the tab is also scrolled so it
   * starts right under the tab strip, whichever way that is: the banner sits
   * above the tabs, so without this a Fix leaves the seller looking at the
   * banner with the tab they asked for starting near the bottom of the
   * screen. Run once the banner has folded and the tab has rendered. The
   * desktop has no pager element, so the scroll does nothing there. */
  function jumpToIssue(next: Tab) {
    pickTab(next);
    requestAnimationFrame(() => scrollUnderStrip(tabStrip.current, pager.current));
  }

  usePager(pager, { items: TAB_IDS, current: tab, onPick: pickTab });

  return (
    <div className="editor">
      {aiSeo !== null &&
        aiSeo.run.autoNotice &&
        aiSeo.run.busy &&
        createPortal(
          <div className="ai-auto-toast" role="status">
            <p>AI Mode is writing a title, tags and a description from this design.</p>
            <button type="button" aria-label="Dismiss" onClick={aiSeo.run.dismissAutoNotice}>
              ×
            </button>
          </div>,
          document.body,
        )}
      {head}

      <ShellIssues
        template={template}
        issues={detail.issues}
        tab={tab}
        onJumpTo={jumpToIssue}
        onRemovePosition={(name, placement) => {
          // An explicit action, so it saves now rather than after the debounce.
          update({
            template_positions: withoutPosition(detail.template_positions, name, placement),
          });
          flush();
        }}
      />

      {props.kind === "listing-template" ? (
        <DesignSelect preview={preview} onPreview={setPreview} />
      ) : (
        <ArtworkStrip
          design={detail.design}
          colours={detail.colors}
          garmentProfile={detail.garment_profile}
          open={openSlot}
          onOpen={setOpenSlot}
          onChange={props.onDesignChange}
          onPreview={previewColour}
        />
      )}

      <div className="tabs seg" ref={tabStrip}>
        {TABS.map((t) => {
          const badge = badgeFor(detail.issues, t.id);
          return (
            <div
              key={t.id}
              className={tab === t.id ? "seg-opt seg-opt--on" : "seg-opt"}
              onClick={() => pickTab(t.id)}
            >
              <TabLabel tab={t} phone={isPhone} />
              {/* One warning-coloured count, however many of them stop a
                  deploy: none of them stops the save (ADR-0043), and the tab
                  is only saying there is something to look at. The banner
                  says which ones matter for deploying. */}
              {badge.block + badge.warn > 0 && (
                <span className="tab-badge tab-badge--warn">{badge.block + badge.warn}</span>
              )}
            </div>
          );
        })}
      </div>

      <TabPanel phone={isPhone} pager={pager}>
        {tab === "variants" && (
          <VariantsTab
            detail={detail}
            onUpdate={update}
            previewed={previewed}
            onPreview={setPreviewed}
            onChooseSlot={chooseSlot}
            {...(artwork === undefined ? {} : { artwork })}
          />
        )}
        {tab === "pricing" && <PricingTab detail={detail} onUpdate={update} onFlush={flush} />}
        {tab === "images" && (
          <ImagesTab
            detail={detail}
            onUpdate={update}
            onFlush={flush}
            {...(artwork === undefined ? {} : { artwork })}
            {...(owner === undefined ? {} : { owner })}
          />
        )}
        {tab === "details" &&
          (aiSeo === null ? (
            <DetailsTab kind="listing-template" detail={detail} onUpdate={update} onFlush={flush} />
          ) : (
            <DetailsTab detail={detail} onUpdate={update} onFlush={flush} aiSeo={aiSeo} />
          ))}
      </TabPanel>
    </div>
  );
}

/** Scrolls the page so `content` starts just under the tab strip at its
 * stuck position, up or down. `content` is the phone's pager: `null` on the
 * desktop. */
function scrollUnderStrip(strip: HTMLElement | null, content: HTMLElement | null) {
  if (strip === null || content === null) return;
  const style = window.getComputedStyle(strip);
  const gap = Number.parseFloat(style.marginBottom) || 0;
  const stuck = Number.parseFloat(style.top) || 0;
  const top =
    window.scrollY + content.getBoundingClientRect().top - stuck - strip.offsetHeight - gap;
  window.scrollTo({ top: Math.max(0, top) });
}

function TabPanel({
  phone,
  pager,
  children,
}: {
  phone: boolean;
  pager: RefObject<HTMLDivElement | null>;
  children: ReactNode;
}) {
  if (!phone) return children;
  return (
    <div ref={pager} className="editor-pager">
      {children}
    </div>
  );
}

function TabLabel({ tab, phone }: { tab: (typeof TABS)[number]; phone: boolean }) {
  if (tab.lead === undefined) return tab.label;
  if (!phone) return `${tab.lead}${tab.label}`;
  return (
    <>
      <span className="seg-opt__lead">{tab.lead}</span>
      {tab.label}
    </>
  );
}
