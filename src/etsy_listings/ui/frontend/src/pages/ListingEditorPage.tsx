import { type ReactNode, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getListing, getListingDraft } from "../api/listings";
import { EditableName } from "../components/EditableName";
import { StatusTag } from "../components/StatusTag";
import { useAutosave } from "../hooks/useAutosave";
import { type MediaOwner, refName } from "../media";
import type { Issue, IssueTab, ListingDetail } from "../types";
import type { AiSeoMode } from "./editor/aiSeo/useAiSeoMode";
import { AiWorkflowIndicator } from "./editor/aiSeo/AiWorkflowIndicator";
import { useAiSeoMode } from "./editor/aiSeo/useAiSeoMode";
import { DeployControl } from "./editor/DeployControl";
import { DesignSelect } from "./editor/DesignSelect";
import { DEFAULT_PREVIEW, type PreviewDesign, previewArtwork } from "./editor/previewDesign";
import { DetailsTab } from "./editor/DetailsTab";
import { PricingTab } from "./editor/PricingTab";
import { IssuesBanner } from "./editor/IssuesBanner";
import { BackToBatch, ListingActions } from "./editor/ListingActions";
import { ImagesTab } from "./editor/ImagesTab";
import { metaFor } from "./editor/saveMeta";
import { useListingBatch } from "./editor/useListingBatch";
import { VariantsTab } from "./editor/VariantsTab";

/** Tabs container + issues banner + page head (phase 5).
 *
 * The editor is also the *create* form, and one route component serves both:
 * `/listings/new` is this page with no `:name`, opened on an empty draft from
 * `GET /api/listing-draft`. A second component for the unsaved case was tried
 * and is exactly what broke creating a listing -- it grew its own copy of the
 * patch merge, the create and the loading state, and each copy drifted. What is
 * genuinely different about an unnamed listing is only that it cannot be
 * *saved*, and that difference lives in one place: `useAutosave`, which picks
 * its transport from what exists (see its docstring). */

type Tab = IssueTab;

const TABS: { id: Tab; label: string }[] = [
  { id: "variants", label: "Variants" },
  { id: "pricing", label: "Pricing" },
  { id: "images", label: "Listing Images" },
  { id: "details", label: "Listing Details" },
];

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
  /** `null` at `/listings/new`: the listing this page is for does not exist. */
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
  const initial =
    handed !== null && handed.name === routeName
      ? handed
      : fetched !== null && (fetched.name || null) === routeName
        ? fetched
        : null;

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
      // updates its own `savedName`, `detail` and `save` before `onNamed`
      // fires), so that remount threw away state for nothing. It is not
      // nothing any more: PRD 68's chain is armed when a design is attached,
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
  /** The batch summary this editor was opened from (`?batch=`, UI doc §8):
   * a query parameter, so it survives a reload. */
  const fromBatch = useSearchParams()[0].get("batch");
  const [member, setMember] = useListingBatch(detail.name);
  // AI Mode, and the AI run behind it, live here rather than inside a tab: a
  // run outlives the tab that was showing when it started, and the chain
  // that begins one begins at the design strip, above the tab strip (PRD
  // 68). Living here rather than in `ListingEditorShell` is what lets the
  // page head report it beside the autosave line.
  /** A name the design pick chose, before the listing exists under it. */
  const [pickedName, setPickedName] = useState("");
  /** A name the seller has started typing but not committed. `detail.name` is
   * still `""` at that point -- an uncommitted name is not the listing's name
   * -- so without this a design pick would overwrite what they were typing. */
  const [typedName, setTypedName] = useState("");
  const aiSeo = useAiSeoMode(detail, update, flush, save, adopt);

  /** Everything picking a design sets off, in the one handler, because two of
   * the three need the pick itself rather than a later render of its effect.
   *
   * The name is here rather than in `ListingEditorShell` because naming is
   * `useAutosave`'s (`commitName`), and only a draft that has none gets one:
   * a listing already called something is called that on purpose, and the
   * artwork changing is not a reason to rename its directory. The design's
   * own filename is the name a seller would type anyway -- it is what `new
   * <design>` already derives on the CLI -- and it is what finally writes the
   * file, so the ordinary create flow becomes "pick a design" with nothing
   * else required. A name already taken is refused exactly as a typed one is,
   * and the page head says so. */
  function pickDesign(ref: string) {
    update({ design: ref });
    if (detail.name === "" && typedName.trim() === "") {
      const named = refName(ref);
      // Shown as the name immediately, not only once the file exists. A
      // create is refused until the document will validate (no price source,
      // usually), and `useAutosave` holds the name for the edit that retries
      // it -- so without this the seller would pick a design, see the name
      // field stay empty, pick a pricing plan, and find the listing suddenly
      // called something nobody typed. The head already says why it is not
      // saved yet.
      setPickedName(named);
      commitName(named);
    }
    // PRD 68: armed while the brief is empty, fired by the first save that
    // can run it (`useAiRun`).
    aiSeo.run.arm();
  }

  return (
    <ListingEditorShell
      detail={detail}
      update={update}
      flush={flush}
      onPickDesign={pickDesign}
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
                onBack={(batch) =>
                  void flush().then(() => navigate(`/batches/${encodeURIComponent(batch)}`))
                }
              />
            )
          }
          actions={
            // Nothing to act on until the listing exists: an unnamed draft
            // has no file to make a template from, and no lifecycle.
            detail.name !== "" && (
              <ListingActions
                detail={detail}
                member={member}
                setMember={setMember}
                update={update}
                adopt={adopt}
                flush={flush}
                onCreateTemplate={() => void flush().then(() => navigate(saveAsUrl(detail.name)))}
                onDeleted={() => navigate("/listings", { replace: true })}
              />
            )
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
          meta={metaFor(save, name)}
        />
      }
    />
  );
}

/** Where Create listing template opens the unsaved template (UI doc §1). */
function saveAsUrl(listing: string): string {
  return `/listing-templates/new?from_listing=${encodeURIComponent(listing)}`;
}

/** The page head both flows share (UI doc, *The editor head*): an identity
 * row over an action row.
 *
 * - **The identity row**: the breadcrumb (or `crumb`, Back to batch in its
 *   place), the title node, the status pill, the meta -- the save sentence,
 *   or once saved the auto-save chip with its file card -- what the editor is
 *   doing on its own, and Deploy.
 * - **The action row**: `actions`, the caller's quiet icon + label actions.
 *   Absent when there are none (an unsaved draft has nothing to act on), and
 *   the identity row then carries the head's rule itself.
 *
 * `Deploy changes →` (docs/features/deploy-20260917/spec.md decision 8) sits here rather
 * than in `ListingEditorPageContent`, because this is the one part of the
 * editor that reads the same on every tab -- an action anchored to a spot
 * that stayed empty in the mockup, not one that jumps around with the tab
 * strip. It is withheld for a draft that has no name yet (`detail.name ===
 * ""`): there is nothing on disk for `plan` to read until naming creates it. */
export function EditorHead({
  detail,
  onBack,
  title,
  meta,
  flush,
  activity,
  crumb,
  actions,
  kind = "listing",
}: {
  detail: ListingDetail;
  onBack: () => void;
  title: ReactNode;
  meta: ReactNode;
  flush: () => Promise<void>;
  /** What the editor is doing on its own right now, beside the meta line
   * (PRD 68). `null` whenever nothing is running, which is most of the
   * time. */
  activity?: ReactNode;
  /** Replaces the breadcrumb when truthy: Back to batch (UI doc §8). */
  crumb?: ReactNode;
  /** The action row's contents, when there are any. */
  actions?: ReactNode;
  /** A listing template's head has no status and no Deploy (UI doc §3): a
   * template never deploys. Its actions are its caller's. */
  kind?: "listing" | "listing-template";
}) {
  const listing = kind === "listing";

  return (
    <div className={actions ? "editor-head editor-head--actions" : "editor-head"}>
      <div className="page-head page-head--editor">
        {crumb || (
          <span className="page-head__crumb" onClick={onBack}>
            {listing ? "Listings" : "Listing templates"}
          </span>
        )}
        <span className="page-head__sep">/</span>
        {title}

        {listing && <StatusTag status={detail.status} />}
        <span className="page-head__meta">{meta}</span>
        {activity}

        {listing && detail.name !== "" && (
          <div className="page-head__actions dv-head-actions">
            <DeployControl name={detail.name} flush={flush} />
          </div>
        )}
      </div>
      {actions && (
        <div className="action-row" role="group" aria-label="Actions">
          {actions}
        </div>
      )}
    </div>
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
      /** Everything one design pick sets off -- the edit, naming an unnamed
       * draft, and arming the AI chain. Built by `ListingEditorPageContent`,
       * which is the layer that has `commitName`. */
      onPickDesign: (ref: string) => void;
      /** Owned by `ListingEditorPageContent`, not by this shell and not by
       * `DetailsTab`: a run outlives the tab it was started from --
       * switching to Variants unmounts the tab. */
      aiSeo: AiSeoMode;
    }
  | {
      /** The listing-template editor (UI doc §3): the same shell minus the
       * design-specific parts. The design row picks a preview design, the
       * banner uses the template wording, and Details has no per-listing
       * copy. Variants, Pricing and Listing Images are unchanged. */
      kind: "listing-template";
      /** Whose `./` files the Images tab shows: the template's, or -- not
       * saved yet -- its source's, through `copies`. */
      owner: MediaOwner | null;
    }
);

export function ListingEditorShell(props: ShellProps) {
  const { detail, update, flush, head } = props;
  const template = props.kind === "listing-template";
  const aiSeo = props.kind === "listing-template" ? null : props.aiSeo;
  const [tab, setTab] = useState<Tab>("variants");
  // The listing template's preview design (UI doc §3): component state, so
  // it is never in the document and is back to the bundled grid every time
  // the editor opens.
  const [preview, setPreview] = useState<PreviewDesign>(DEFAULT_PREVIEW);
  const artwork = template ? previewArtwork(preview) : undefined;
  const owner = props.kind === "listing-template" ? props.owner : undefined;

  function pickTab(next: Tab) {
    flush();
    setTab(next);
  }

  return (
    <div className="editor">
      {/* On document.body, not inside a tab: DetailsTab unmounts on every
          other tab, and the chain starts from the design strip, which is
          usually Variants. */}
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

      {template ? (
        <IssuesBanner
          issues={detail.issues}
          activeTab={tab}
          onJumpTo={pickTab}
          subject="listing-template"
          // A block is what stops the save (A36); warnings alone stop
          // nothing, so they are not told the file is being held back.
          when={
            detail.issues.some((issue) => issue.severity === "block")
              ? "Last complete version is kept until then"
              : "Checked against this template’s own configuration"
          }
        />
      ) : (
        <IssuesBanner issues={detail.issues} activeTab={tab} onJumpTo={pickTab} />
      )}

      {/* Above the tabs, not inside one: the artwork is what both Variants
          (which colours suit it) and Listing Images (which mockups show it)
          are about. */}
      {props.kind === "listing-template" ? (
        <DesignSelect preview={preview} onPreview={setPreview} />
      ) : (
        <DesignSelect design={detail.design} onPick={props.onPickDesign} />
      )}

      <div className="tabs seg">
        {TABS.map((t) => {
          const badge = badgeFor(detail.issues, t.id);
          return (
            <div
              key={t.id}
              className={tab === t.id ? "seg-opt seg-opt--on" : "seg-opt"}
              onClick={() => pickTab(t.id)}
            >
              {t.label}
              {/* One warning-coloured count, however many of them stop a
                  deploy: none of them stops the save (PRD 70), and the tab
                  is only saying there is something to look at. The banner
                  says which ones matter for deploying. */}
              {badge.block + badge.warn > 0 && (
                <span className="tab-badge tab-badge--warn">{badge.block + badge.warn}</span>
              )}
            </div>
          );
        })}
      </div>

      {tab === "variants" && (
        <VariantsTab
          detail={detail}
          onUpdate={update}
          {...(artwork === undefined ? {} : { artwork })}
        />
      )}
      {tab === "pricing" && <PricingTab detail={detail} onUpdate={update} onFlush={flush} />}
      {tab === "images" && (
        <ImagesTab
          detail={detail}
          onUpdate={update}
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
    </div>
  );
}
