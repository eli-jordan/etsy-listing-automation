import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  createListingTemplate,
  getListingTemplateDraft,
  ListingTemplateNameRefused,
} from "../api/listingTemplates";
import { EditableName, type NameRefusal } from "../components/EditableName";
import { mediaKind, mediaLabel, ownedTile } from "../media";
import type { Issue, ListingTemplateDraft, ListingTemplateSource } from "../types";

/**
 * A new listing template in its *name it* state (UI doc §1; the
 * `template-new` mockup frame): Save as listing template, and later Clone,
 * land here with nothing written. The head is the template editor's --
 * breadcrumb, an empty focused `EditableName`, *Not saved — name this
 * template to save it* -- and committing a unique name is what writes it.
 * Leaving without one discards the draft, because there is nothing on disk
 * to discard.
 *
 * Below the head is a read-only summary of what was kept (batch plan PR 1):
 * garment, colours, pricing, gallery and description source. The design,
 * brief, title, tags and lead are simply absent, which is the whole
 * explanation of what a template leaves behind. PR 6 turns this summary into
 * the listing-template editor in its unsaved state.
 */

const HOW_TO =
  "To make a listing template, open a finished listing and choose Save as listing template.";

function sourceFrom(params: URLSearchParams): ListingTemplateSource | null {
  const listing = params.get("from_listing");
  if (listing) return { kind: "listing", name: listing };
  const template = params.get("from_template");
  if (template) return { kind: "listing-template", name: template };
  return null;
}

/** `IssuesBanner`'s markup with the template wording the mockup gives it:
 * a template never deploys, so nothing here says *Prevents deploying*. Read
 * only -- the fix is in the source, not on this page. */
function TemplateIssues({ issues }: { issues: Issue[] }) {
  const visible = issues.filter((issue) => issue.severity !== "info");
  if (visible.length === 0) return null;
  return (
    <div className="issues">
      <div className="issues__head">
        <span className="issues__summary issues__summary--warn">
          {visible.length} to fix before this template saves
        </span>
        <span className="issues__when">Checked against what this template keeps</span>
      </div>
      {visible.map((issue, index) => (
        <div key={`${issue.where}-${index}`} className="issue issue--warn">
          <span className="issue__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="15" height="15">
              <path
                d="M10.3 3.9a2 2 0 0 1 3.4 0l8.1 14.1A2 2 0 0 1 20.1 21H3.9a2 2 0 0 1-1.7-3z"
                fill="var(--color-warning)"
              />
              <path
                d="M12 9v4.6M12 17.2v.01"
                fill="none"
                stroke="var(--color-warning-ink)"
                strokeWidth="2.2"
                strokeLinecap="round"
              />
            </svg>
          </span>
          <span className="issue__body">
            <span className="issue__text">{issue.message}</span>
            <span className="issue__where">{issue.where}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function pricingLine(draft: ListingTemplateDraft): string {
  if (draft.pricing_plan_name) return `Pricing plan: ${draft.pricing_plan_name}`;
  const sizes = Object.entries(draft.prices).map(([size, amount]) => `${size} ${amount}`);
  return sizes.length > 0 ? `Prices set per size: ${sizes.join(" · ")}` : "No prices";
}

function descriptionLine(draft: ListingTemplateDraft): string {
  const body = draft.etsy.description;
  if (body.ref) return `Common copy: ${draft.description_title ?? body.ref}`;
  if (body.text) return "Written in this template";
  return "No description body";
}

/** What the template keeps, read only. The `.details-tab` field layout and
 * the gallery reel's tiles, so nothing here is a new look. */
function KeptSummary({ draft }: { draft: ListingTemplateDraft }) {
  // A local file's copy does not exist until the save: draw it from where its
  // source keeps it. A clone's source *is* a listing template.
  const owner = draft.source;
  const sourceRef = new Map(draft.assets.map((asset) => [asset.ref, asset.source_ref]));
  const images = draft.media.filter((entry) => mediaKind(entry) === "image").length;
  const videos = draft.media.length - images;
  const body = draft.etsy.description;
  return (
    <div className="details-tab">
      <div className="field">
        <label>Garment</label>
        <span>{draft.garment ?? draft.garment_profile}</span>
      </div>
      <div className="field">
        <label>Colours</label>
        <span>{draft.colors.join(", ")}</span>
      </div>
      <div className="field">
        <label>Pricing</label>
        <span>{pricingLine(draft)}</span>
      </div>
      <div className="reel">
        <div className="reel__head">
          <span className="reel__title">Listing gallery</span>
          <span className="reel__count">{images === 1 ? "1 image" : `${images} images`}</span>
          {videos > 0 && (
            <span className="reel__count">{videos === 1 ? "1 video" : `${videos} videos`}</span>
          )}
        </div>
        <div className="reel__track">
          {draft.media.map((entry, index) => {
            const from = typeof entry === "string" ? (sourceRef.get(entry) ?? entry) : entry;
            return (
              <div
                key={`${mediaLabel(entry)}-${index}`}
                className="rtile"
                title={mediaLabel(entry)}
              >
                <div className="rtile__face">
                  {mediaKind(entry) === "video" ? (
                    <span className="rtile__play">▶</span>
                  ) : (
                    <img src={ownedTile(from, owner)} alt={mediaLabel(entry)} />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="field">
        <label>Description Body</label>
        <span>{descriptionLine(draft)}</span>
        {!body.ref && body.text && <p className="description-preview">{body.text}</p>}
        <span className="field__hint">
          Each listing&rsquo;s own description lead is placed above this body.
        </span>
      </div>
      {draft.etsy.section && (
        <div className="field">
          <label>Section</label>
          <span>{draft.etsy.section}</span>
        </div>
      )}
    </div>
  );
}

export function ListingTemplateNewPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const source = sourceFrom(params);
  const sourceKey = source === null ? null : `${source.kind}:${source.name}`;
  const [draft, setDraft] = useState<{ key: string; draft: ListingTemplateDraft } | null>(null);
  const [loadError, setLoadError] = useState("");
  const [refusal, setRefusal] = useState<NameRefusal | null>(null);
  const [notSaved, setNotSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (source === null || sourceKey === null) return;
    let current = true;
    getListingTemplateDraft(source)
      .then((loaded) => {
        if (current) setDraft({ key: sourceKey, draft: loaded });
      })
      .catch((error: unknown) => {
        if (current) setLoadError(error instanceof Error ? error.message : String(error));
      });
    return () => {
      current = false;
    };
    // `source` is rebuilt every render; its key is what identifies it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey]);

  if (source === null) return <p className="app__status">{HOW_TO}</p>;
  if (loadError) return <p className="app__status">{loadError}</p>;
  const current = draft?.key === sourceKey ? draft.draft : null;
  if (current === null) return <p className="app__status">Loading…</p>;

  function commit(name: string) {
    if (source === null) return;
    setBusy(true);
    setRefusal(null);
    createListingTemplate(name, source)
      .then((result) => {
        if (result.saved) {
          navigate("/listing-templates");
          return;
        }
        setNotSaved(true);
      })
      .catch((error: unknown) => {
        setRefusal({
          name,
          message:
            error instanceof ListingTemplateNameRefused ? error.message : "could not save it",
        });
      })
      .finally(() => setBusy(false));
  }

  return (
    <div className="editor">
      <div className="page-head page-head--editor">
        <span className="page-head__crumb" onClick={() => navigate("/listing-templates")}>
          Listing templates
        </span>
        <span className="page-head__sep">/</span>
        <EditableName
          value=""
          onCommit={commit}
          error={refusal}
          busy={busy}
          placeholder="Name this template…"
          label="Template name"
        />
        <span className="page-head__meta">
          {notSaved
            ? "Not saved — fix the listing it comes from, then name it again"
            : "Not saved — name this template to save it"}
        </span>
      </div>

      <TemplateIssues issues={current.issues} />
      <KeptSummary draft={current} />
    </div>
  );
}
