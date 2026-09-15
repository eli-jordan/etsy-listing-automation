import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getListing } from "../api/listings";
import { OpenOnMenu } from "../components/OpenOnMenu";
import { useAutosave } from "../hooks/useAutosave";
import type { Issue, IssueTab, ListingDetail } from "../types";
import { DetailsTab } from "./editor/DetailsTab";
import { IssuesBanner } from "./editor/IssuesBanner";
import { ImagesTab } from "./editor/ImagesTab";
import { VariantsTab } from "./editor/VariantsTab";

/** Tabs container + issues banner + page head (phase 5). The editor page
 * itself is always backed by a real, already-created listing (`+ New
 * listing` POSTs first and navigates here) -- so this only ever has a
 * loading state and a loaded one, never a not-yet-saved one. */

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
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const [initial, setInitial] = useState<ListingDetail | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (!name) return;
    let current = true;
    getListing(name)
      .then((loaded) => {
        if (current) setInitial(loaded);
      })
      .catch(() => {
        if (current) setLoadError(`failed to load listing ${name}`);
      });
    return () => {
      current = false;
    };
  }, [name]);

  if (!name) return null;
  if (loadError) return <p className="app__status">{loadError}</p>;
  if (!initial) return <p className="app__status">Loading…</p>;

  return (
    <ListingEditorPageContent
      key={name}
      name={name}
      initial={initial}
      onBack={() => navigate("/listings")}
    />
  );
}

function ListingEditorPageContent({
  name,
  initial,
  onBack,
}: {
  name: string;
  initial: ListingDetail;
  onBack: () => void;
}) {
  const { detail, update, flush, saving } = useAutosave(name, initial);
  const [tab, setTab] = useState<Tab>("variants");

  function pickTab(next: Tab) {
    flush();
    setTab(next);
  }

  const isPublished = detail.status === "published";

  return (
    <div className="editor">
      <div className="page-head">
        <span className="page-head__crumb" onClick={onBack}>
          Listings
        </span>
        <span className="page-head__sep">/</span>
        <h1 className="page-head__title">{name}</h1>

        {isPublished && (
          <OpenOnMenu
            etsyListingId={detail.etsy_listing_id}
            printifyProductId={detail.printify_product_id}
          />
        )}

        <span className={isPublished ? "tag tag-accent-2" : "tag tag-neutral"}>
          {isPublished ? "Published" : "Draft"}
        </span>
        {/* The path, because this editor writes a file the user also edits by
            hand and runs the CLI against -- knowing which one is the point. */}
        <span className="page-head__meta">
          <span className="page-head__path">listings/{name}/listing.yaml</span>
          {" · "}
          {saving ? "Saving…" : "Autosaved"}
        </span>
      </div>

      <IssuesBanner issues={detail.issues} activeTab={tab} onJumpTo={pickTab} />

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
