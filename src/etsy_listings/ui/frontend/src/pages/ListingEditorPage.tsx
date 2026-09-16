import { type ReactNode, useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { getListing, getListingDraft } from "../api/listings";
import { EditableName } from "../components/EditableName";
import { OpenOnMenu } from "../components/OpenOnMenu";
import { hasOpenTargets } from "../components/openOn";
import { StatusTag } from "../components/StatusTag";
import { useAutosave } from "../hooks/useAutosave";
import type { Issue, IssueTab, ListingDetail } from "../types";
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
      // A genuine listing switch remounts; naming or renaming this one does
      // not lose anything by remounting either, because `useAutosave` drains
      // what is pending before the name changes and again on unmount.
      key={routeName ?? "new"}
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

  return (
    <ListingEditorShell
      detail={detail}
      update={update}
      flush={flush}
      head={
        <EditorHead
          detail={detail}
          onBack={onBack}
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
 * once there is something to open, the status pill, and a meta line. */
export function EditorHead({
  detail,
  onBack,
  title,
  meta,
}: {
  detail: ListingDetail;
  onBack: () => void;
  title: ReactNode;
  meta: ReactNode;
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
    </div>
  );
}

export function ListingEditorShell({
  detail,
  update,
  flush,
  head,
}: {
  detail: ListingDetail;
  update: (patch: Record<string, unknown>) => void;
  flush: () => void;
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
      <DesignSelect design={detail.design} onPick={(ref) => update({ design: ref })} />

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
      {tab === "details" && <DetailsTab detail={detail} onUpdate={update} onFlush={flush} />}
    </div>
  );
}
