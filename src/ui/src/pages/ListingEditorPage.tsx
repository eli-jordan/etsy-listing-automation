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

const TABS: { id: Tab; desktopPrefix?: string; label: string }[] = [
  { id: "variants", label: "Variants" },
  { id: "pricing", label: "Pricing" },
  { id: "images", desktopPrefix: "Listing ", label: "Images" },
  { id: "details", desktopPrefix: "Listing ", label: "Details" },
];

const TAB_IDS = TABS.map((t) => t.id);

function isTab(value: unknown): value is Tab {
  return TABS.some((t) => t.id === value);
}

function issueCount(issues: Issue[], tab: Tab): number {
  return issues.filter((i) => i.tab === tab && i.severity !== "info").length;
}

function forRoute(doc: ListingDetail | null, routeName: string | null): ListingDetail | null {
  return doc !== null && (doc.name || null) === routeName ? doc : null;
}

export function ListingEditorPage() {
  const { name } = useParams<{ name?: string }>();
  const navigate = useNavigate();
  const routeName = name ?? null;

  // The listing as the editor that just named it had it. Naming crosses from
  // `/listings/new` to `/listings/:name`, a different route pattern, which React
  // Router remounts across; the written document rides along in the navigation
  // so no GET can answer older than the save the unmounting editor flushed.
  const handed = (useLocation().state as { listing?: ListingDetail } | null)?.listing ?? null;
  // Used once, then dropped from the history entry, which a reload keeps.
  // Through `window.history`, which React Router does not watch, so this page
  // does not re-render and remount the editor over it.
  useEffect(() => {
    if (handed === null) return;
    const entry = window.history.state as Record<string, unknown> | null;
    if (entry !== null && typeof entry === "object" && "usr" in entry) {
      window.history.replaceState({ ...entry, usr: null }, "");
    }
  }, [handed]);
  const [fetched, setFetched] = useState<ListingDetail | null>(null);
  const [loadError, setLoadError] = useState("");

  const initial = forRoute(handed, routeName) ?? forRoute(fetched, routeName);

  useEffect(() => {
    if (initial !== null) return;
    let current = true;
    (routeName === null ? getListingDraft() : getListing(routeName))
      .then((loaded) => {
        if (!current) return;
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
  const [nameFromDesign, setNameFromDesign] = useState("");
  const [uncommittedName, setUncommittedName] = useState("");
  const aiSeo = useAiSeoMode(detail, update, flush, save, adopt);
  const phone = useIsPhone();

  function changeDesign(next: DesignMap) {
    update({ design: next });
    const chosen = representative(next);
    if (chosen === null || chosen === representative(detail.design)) return;
    if (detail.name === "" && uncommittedName.trim() === "") {
      const named = refName(chosen);
      setNameFromDesign(named);
      commitName(named);
    }
    aiSeo.run.arm();
  }

  // An edit that cannot be written keeps the seller here, the one place it
  // still exists, where the page head says why.
  function navigateOnceWritten(url: string) {
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
                onBack={(batch) => navigateOnceWritten(`/batches/${encodeURIComponent(batch)}`)}
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
                onCreateTemplate={() => navigateOnceWritten(newTemplateFromListingUrl(detail.name))}
                onDeleted={() => navigate(afterDelete(fromBatch), { replace: true })}
              />
            )
          }
          phoneReview={
            phone &&
            member !== null &&
            detail.name !== "" && <ReviewButton member={member} setMember={setMember} />
          }
          activity={<AiWorkflowIndicator steps={aiSeo.run.steps} running={aiSeo.run.busy} />}
          title={
            <EditableName
              value={name ?? nameFromDesign}
              onCommit={commitName}
              onDraftChange={setUncommittedName}
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

function newTemplateFromListingUrl(listing: string): string {
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
  phoneReview,
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
  phoneReview?: ReactNode;
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
              {phoneReview}
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
      aiSeo: AiSeoMode;
    }
  | {
      kind: "listing-template";
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
  const saveWithheld = issues.some((issue) => issue.severity === "block");
  return (
    <IssuesBanner
      issues={issues}
      activeTab={tab}
      onJumpTo={onJumpTo}
      subject="listing-template"
      when={
        saveWithheld
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
  const [openSlot, setOpenSlot] = useState<SlotTarget | null>(null);
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
    if (isPhone && next !== tab) scrollUnderStrip(tabStrip.current, pager.current, "up");
    setTab(next);
  }

  function jumpToIssue(next: Tab) {
    pickTab(next);
    // The banner sits above the tabs, so a Fix would leave the phone's tab
    // starting near the bottom of the screen. Once the banner has folded and
    // the tab has rendered, start it under the strip.
    if (isPhone) {
      requestAnimationFrame(() => scrollUnderStrip(tabStrip.current, pager.current, "either"));
    }
  }

  function commit(patch: Record<string, unknown>) {
    update(patch);
    flush();
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
        onRemovePosition={(name, placement) =>
          commit({
            template_positions: withoutPosition(detail.template_positions, name, placement),
          })
        }
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
          const count = issueCount(detail.issues, t.id);
          return (
            <div
              key={t.id}
              className={tab === t.id ? "seg-opt seg-opt--on" : "seg-opt"}
              onClick={() => pickTab(t.id)}
            >
              <TabLabel tab={t} phone={isPhone} />
              {/* Warning-coloured however many block: none stops the save (ADR-0043). */}
              {count > 0 && <span className="tab-badge tab-badge--warn">{count}</span>}
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

/** A stuck strip's rect says where it is pinned, not where the content starts: work from its CSS `top`. */
function scrollUnderStrip(
  strip: HTMLElement | null,
  content: HTMLElement | null,
  direction: "up" | "either",
) {
  if (strip === null || content === null) return;
  const style = window.getComputedStyle(strip);
  const gap = Number.parseFloat(style.marginBottom) || 0;
  const stuck = Number.parseFloat(style.top) || 0;
  const top =
    window.scrollY + content.getBoundingClientRect().top - stuck - strip.offsetHeight - gap;
  if (direction === "up" && top >= window.scrollY) return;
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
  if (tab.desktopPrefix === undefined) return tab.label;
  if (!phone) return `${tab.desktopPrefix}${tab.label}`;
  return (
    <>
      <span className="seg-opt__lead">{tab.desktopPrefix}</span>
      {tab.label}
    </>
  );
}
