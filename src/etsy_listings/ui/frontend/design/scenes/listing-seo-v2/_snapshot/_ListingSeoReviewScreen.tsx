import { useState } from "react";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import type { ReactNode } from "react";
import "./listingSeoReview.css";

export type SeoReviewState = "readiness" | "loading" | "proposal" | "stale" | "failed";

interface Props {
  state: SeoReviewState;
}

type SuggestionKey = "title" | "tags" | "lead";

const proposed = {
  title: "Retro Take A Hike Mountain Graphic Tee",
  tags: [
    "retro hiking shirt",
    "mountain graphic tee",
    "take a hike shirt",
    "outdoor lover gift",
    "hiker t shirt",
    "camping graphic tee",
    "national park style",
    "adventure shirt",
    "mountain lover tee",
    "retro outdoor tee",
    "trail lover shirt",
    "nature graphic tee",
    "weekend hiker gift",
  ],
  lead: "A retro mountain graphic tee for hikers and outdoor lovers, featuring the exact words “Take A Hike” above a warm sunset trail scene.",
};

function Sidebar() {
  return (
    <ShellSidebar shopName="Pine & Thread">
      <nav className="sidebar__nav" aria-label="App navigation">
        <a className="nav-item" href="#dashboard">Dashboard</a>
        <a className="nav-item nav-item--active" href="#listings">Listings</a>
        <a className="nav-item" href="#templates">Mockup Templates</a>
      </nav>
    </ShellSidebar>
  );
}

function SparkleIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M8.2 2.2c.5 3.1 1.5 4.1 4.6 4.6-3.1.5-4.1 1.5-4.6 4.6-.5-3.1-1.5-4.1-4.6-4.6 3.1-.5 4.1-1.5 4.6-4.6Z" />
      <path d="M14.5 11.2c.3 2 1 2.7 3 3-2 .3-2.7 1-3 3-.3-2-1-2.7-3-3 2-.3 2.7-1 3-3Z" />
    </svg>
  );
}

function GenerateButton({ state }: { state: SeoReviewState }) {
  const disabled = state === "readiness" || state === "loading";
  const label = state === "loading" ? "Generating…" : state === "stale" ? "Regenerate" : "Generate";
  return (
    <span className="seo-review__generate-wrap">
      <button
        className="seo-review__generate"
        data-goto={disabled ? undefined : "listing-seo-v2/loading"}
        disabled={disabled}
        type="button"
      >
        <SparkleIcon />
        {label}
      </button>
      {state === "readiness" ? (
        <span className="seo-review__hover-card" role="tooltip">
          Select a design and add a listing brief first.
        </span>
      ) : null}
    </span>
  );
}

function SuggestionDrawer({
  children,
  label,
  stale,
  onAccept,
  onReject,
}: {
  children: ReactNode;
  label: string;
  stale?: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  return (
    <aside className={`seo-suggestion${stale ? " seo-suggestion--stale" : ""}`} aria-label={`${label} AI suggestion`}>
      <div className="seo-suggestion__topline">
        <span><SparkleIcon /> {stale ? "Suggestion is out of date" : "AI suggestion"}</span>
        <div className="seo-suggestion__actions">
          <button aria-label={`Reject suggested ${label}`} onClick={onReject} type="button">× Reject</button>
          <button aria-label={`Accept suggested ${label}`} disabled={stale} onClick={onAccept} type="button">✓ Accept</button>
        </div>
      </div>
      <div className="seo-suggestion__value">{children}</div>
    </aside>
  );
}

export function ListingSeoReviewScreen({ state }: Props) {
  const hasSuggestions = state === "proposal" || state === "stale";
  const [pending, setPending] = useState<Record<SuggestionKey, boolean>>({
    title: hasSuggestions,
    tags: hasSuggestions,
    lead: hasSuggestions,
  });
  const [title, setTitle] = useState("Take A Hike Mountain Tee");
  const [tags, setTags] = useState<string[]>([]);
  const [lead, setLead] = useState("");

  const close = (key: SuggestionKey) => setPending((current) => ({ ...current, [key]: false }));
  const accept = (key: SuggestionKey) => {
    if (key === "title") setTitle(proposed.title);
    if (key === "tags") setTags(proposed.tags);
    if (key === "lead") setLead(proposed.lead);
    close(key);
  };

  return (
    <div className="shell seo-review">
      <Sidebar />
      <main className="shell__main seo-review__main">
        <header className="page-head">
          <span className="page-head__crumb">Listings</span>
          <span className="page-head__sep">/</span>
          <h1 className="page-head__title">Take a hike</h1>
          <span className="page-head__meta">Saved just now</span>
          <span className="seo-review__draft">Draft</span>
          <button className="btn btn-secondary seo-review__deploy" type="button">Deploy changes</button>
        </header>

        <div className="design-select">
          <div className="design-row">
            <span className="design-thumb design-thumb--empty" aria-hidden="true" />
            <div className="design-row__text"><strong className="design-row__name">take-a-hike.png</strong><span>Selected design</span></div>
          </div>
        </div>

        <div className="tabs seg" role="tablist" aria-label="Listing editor sections">
          <button className="seg-opt" type="button">Variants</button>
          <button className="seg-opt" type="button">Listing Images</button>
          <button className="seg-opt seg-opt--on" type="button">Listing Details</button>
        </div>

        <section className="seo-review__fields">
          <div className="seo-review__fields-head">
            <div>
              <h2>Listing details</h2>
              <p>Copy shown to shoppers on Etsy.</p>
            </div>
            <GenerateButton state={state} />
          </div>

          {state === "failed" ? (
            <div className="seo-review__inline-status" role="status">
              <span>Couldn’t generate valid suggestions. Nothing changed.</span>
              <button data-goto="listing-seo-v2/loading" type="button">Try again</button>
            </div>
          ) : null}
          {state === "loading" ? (
            <div className="seo-review__inline-status" role="status">
              <span className="seo-review__pulse" aria-hidden="true" />
              <span>Creating suggestions from the current listing…</span>
              <button data-goto="listing-seo-v2/review" type="button">View result</button>
            </div>
          ) : null}

          <div className="field seo-field">
            <div className="seo-field__label"><label htmlFor="seo-title">Title</label><span>{title.length} / 140</span></div>
            <input id="seo-title" className="input" value={title} readOnly />
            {pending.title ? (
              <SuggestionDrawer label="title" stale={state === "stale"} onAccept={() => accept("title")} onReject={() => close("title")}>
                {proposed.title}
              </SuggestionDrawer>
            ) : null}
          </div>

          <div className="field seo-field">
            <div className="seo-field__label"><label>Tags</label><span>{tags.length} / 13</span></div>
            <div className="seo-field__surface">
              {tags.length ? <div className="chips">{tags.map((tag) => <span className="chip" key={tag}>{tag}</span>)}</div> : <span className="chips__empty">No tags yet</span>}
            </div>
            {pending.tags ? (
              <SuggestionDrawer label="tags" stale={state === "stale"} onAccept={() => accept("tags")} onReject={() => close("tags")}>
                <div className="chips">{proposed.tags.map((tag) => <span className="chip" key={tag}>{tag}</span>)}</div>
                <details className="seo-suggestion__why"><summary>Why these tags?</summary><p>Based on seven buyer phrases found in the design and brief.</p></details>
              </SuggestionDrawer>
            ) : null}
          </div>

          <div className="field seo-field">
            <div className="seo-field__label"><label htmlFor="seo-lead">Description lead</label><span>{lead.length} / 500</span></div>
            <textarea id="seo-lead" value={lead} placeholder="A concise first sentence for shoppers" readOnly />
            {pending.lead ? (
              <SuggestionDrawer label="description lead" stale={state === "stale"} onAccept={() => accept("lead")} onReject={() => close("lead")}>
                {proposed.lead}
                <p className="seo-suggestion__note">Gift language stays broad because the brief does not name a recipient.</p>
              </SuggestionDrawer>
            ) : null}
          </div>

          <div className="seo-review__body-source">
            <div>
              <label htmlFor="seo-body">Description body</label>
              <p>Use reusable common copy or write listing-specific copy.</p>
            </div>
            <select id="seo-body" className="input" defaultValue="common-copy/comfort-colors-standard.md">
              <option value="common-copy/comfort-colors-standard.md">Comfort Colors · standard fit and care</option>
              <option value="inline">Write listing-specific body</option>
            </select>
          </div>
        </section>
      </main>
    </div>
  );
}
