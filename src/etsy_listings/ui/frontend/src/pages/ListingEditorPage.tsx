import { type ReactNode, useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { getListing, getListingDraft } from "../api/listings";
import { EditableName } from "../components/EditableName";
import { OpenOnMenu } from "../components/OpenOnMenu";
import { hasOpenTargets } from "../components/openOn";
import { StatusTag } from "../components/StatusTag";
import { useAutosave } from "../hooks/useAutosave";
import type { Issue, IssueTab, ListingDetail } from "../types";
import type { AiSeoMode } from "./editor/aiSeo/useAiSeoMode";
import type { AutoDesignBrief } from "./editor/aiSeo/useAutoDesignBrief";
import { AiActivityIndicator } from "./editor/aiSeo/AiActivityIndicator";
import { useAiSeoMode } from "./editor/aiSeo/useAiSeoMode";
import { useAutoDesignBrief } from "./editor/aiSeo/useAutoDesignBrief";
import { DeployControl } from "./editor/DeployControl";
import { DesignSelect } from "./editor/DesignSelect";
import { DetailsTab } from "./editor/DetailsTab";
import { IssuesBanner } from "./editor/IssuesBanner";
import { ImagesTab } from "./editor/ImagesTab";
import { metaFor } from "./editor/saveMeta";
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
      // nothing any more: PRD 68's chain starts when a design is attached,
      // which on a new listing is usually *before* it is named, and a
      // remount there aborted the request the seller was waiting on.
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
  const { detail, update, flush, commitName, save } = useAutosave(name, initial, { onNamed });
  // Both AI requests live here rather than inside a tab: each outlives the
  // tab that was showing when it started, and the chain that begins them
  // begins at the design strip, above the tab strip (PRD 68). Living here
  // rather than in `ListingEditorShell` is what lets the page head report
  // them beside the autosave line.
  const aiSeo = useAiSeoMode(detail, update, flush, save);
  const autoBrief = useAutoDesignBrief(detail.brief, detail.garment_profile, update, flush, aiSeo);

  return (
    <ListingEditorShell
      detail={detail}
      update={update}
      flush={flush}
      aiSeo={aiSeo}
      autoBrief={autoBrief}
      head={
        <EditorHead
          detail={detail}
          onBack={onBack}
          flush={flush}
          activity={<AiActivityIndicator auto={autoBrief} aiSeo={aiSeo} />}
          title={
            <EditableName
              value={name ?? ""}
              onCommit={commitName}
              error={
                save.kind === "name-taken"
                  ? { name: save.name, message: "that name is already taken" }
                  : null
              }
              busy={save.kind === "saving"}
            />
          }
          meta={metaFor(save, detail, name)}
        />
      }
    />
  );
}

/** The page head both flows share: breadcrumb, a title node, the open menu
 * once there is something to open, the status pill, and a meta line.
 *
 * `Deploy changes →` (docs/deploy-changes.md decision 8) sits here rather
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
}) {
  // Not keyed off `status`: a listing can carry a Printify product without an
  // Etsy listing id, and an id it has is worth a link whatever state Etsy
  // reports it in. `OpenOnMenu` hides the entry it has no id for.
  const hasLinks = hasOpenTargets(detail.etsy_listing_id, detail.printify_product_id);

  return (
    <div className="page-head">
      <span className="page-head__crumb" onClick={onBack}>
        Listings
      </span>
      <span className="page-head__sep">/</span>
      {title}

      {hasLinks && (
        <OpenOnMenu
          etsyListingId={detail.etsy_listing_id}
          printifyProductId={detail.printify_product_id}
        />
      )}

      <StatusTag status={detail.status} />
      <span className="page-head__meta">{meta}</span>
      {activity}

      {detail.name !== "" && (
        <div className="page-head__actions dv-head-actions">
          <DeployControl name={detail.name} flush={flush} />
        </div>
      )}
    </div>
  );
}

export function ListingEditorShell({
  detail,
  update,
  flush,
  aiSeo,
  autoBrief,
  head,
}: {
  detail: ListingDetail;
  update: (patch: Record<string, unknown>) => void;
  flush: () => void;
  /** Owned by `ListingEditorPageContent`, not by this shell and not by
   * `DetailsTab`: a request outlives the tab it was started from -- switching
   * to Variants used to unmount the tab and abort a proposal mid-flight. */
  aiSeo: AiSeoMode;
  autoBrief: AutoDesignBrief;
  head: ReactNode;
}) {
  const [tab, setTab] = useState<Tab>("variants");

  function pickTab(next: Tab) {
    flush();
    setTab(next);
  }

  return (
    <div className="editor">
      {head}

      <IssuesBanner issues={detail.issues} activeTab={tab} onJumpTo={pickTab} />

      {/* Above the tabs, not inside one: the artwork is what both Variants
          (which colours suit it) and Listing Images (which mockups show it)
          are about. */}
      <DesignSelect
        design={detail.design}
        onPick={(ref) => {
          update({ design: ref });
          // Immediately, in the same handler: the brief request needs the
          // design and the garment profile, both of which are in hand here,
          // and nothing about it waits on the save this `update` schedules
          // (PRD 68).
          autoBrief.start(ref);
        }}
      />

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
              {badge.block > 0 && <span className="tab-badge tab-badge--block">{badge.block}</span>}
              {badge.block === 0 && badge.warn > 0 && (
                <span className="tab-badge tab-badge--warn">{badge.warn}</span>
              )}
            </div>
          );
        })}
      </div>

      {tab === "variants" && <VariantsTab detail={detail} onUpdate={update} />}
      {tab === "images" && <ImagesTab detail={detail} onUpdate={update} />}
      {tab === "details" && (
        <DetailsTab detail={detail} onUpdate={update} onFlush={flush} aiSeo={aiSeo} />
      )}
    </div>
  );
}
