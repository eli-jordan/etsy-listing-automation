import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import type { ReactNode } from "react";
import "./listingSeoReview.css";

export type SeoReviewState = "readiness" | "loading" | "proposal" | "stale" | "failed";

interface Props {
  state: SeoReviewState;
}

const proposedTags = [
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
];

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

function ProposalCard({
  title,
  current,
  proposed,
  action,
}: {
  title: string;
  current: ReactNode;
  proposed: ReactNode;
  action: string;
}) {
  return (
    <article className="seo-review__proposal-card">
      <div className="seo-review__proposal-heading">
        <h3>{title}</h3>
        <button className="btn btn-secondary" type="button">{action}</button>
      </div>
      <div className="seo-review__comparison">
        <div>
          <span>Current</span>
          {current}
        </div>
        <div>
          <span>Proposed</span>
          {proposed}
        </div>
      </div>
    </article>
  );
}

function Readiness() {
  return (
    <section className="seo-review__panel seo-review__panel--empty">
      <div>
        <span className="seo-review__eyebrow">SEO assistant</span>
        <h2>Generate reviewable listing copy</h2>
        <p>Use the design, listing brief, garment, colours, and materials to propose a title, 13 tags, and a description lead.</p>
      </div>
      <span className="seo-review__disabled-action">
        <button className="btn btn-primary" type="button" disabled>Generate SEO</button>
        <span className="seo-review__hover-card" role="tooltip">
          Add a listing brief and select a design before generating SEO copy.
        </span>
      </span>
    </section>
  );
}

function Loading() {
  return (
    <section className="seo-review__panel">
      <div>
        <span className="seo-review__eyebrow">SEO assistant</span>
        <h2>Generating your proposal</h2>
        <p>Using a snapshot of the current listing facts. You can keep editing; a changed brief or design will make the result stale.</p>
      </div>
      <div className="seo-review__loading-row" aria-label="Generation in progress">
        <span className="seo-review__loading-mark" aria-hidden="true" />
        <span>Reading design and listing context</span>
      </div>
      <button className="btn btn-secondary" data-goto="listing-seo-v1/review" type="button">View completed proposal</button>
    </section>
  );
}

function Failed() {
  return (
    <section className="seo-review__panel seo-review__panel--notice">
      <div>
        <span className="seo-review__eyebrow">SEO assistant</span>
        <h2>We could not make a valid proposal</h2>
        <p>The response still did not meet Etsy’s copy rules after one repair attempt. Nothing has changed in this listing.</p>
      </div>
      <button className="btn btn-primary" data-goto="listing-seo-v1/loading" type="button">Try again</button>
    </section>
  );
}

function Stale() {
  return (
    <section className="seo-review__panel seo-review__panel--notice">
      <div>
        <span className="seo-review__eyebrow">SEO assistant</span>
        <h2>This proposal needs a refresh</h2>
        <p>The listing brief changed after generation. Your saved title, tags, and description lead are unchanged.</p>
      </div>
      <button className="btn btn-primary" data-goto="listing-seo-v1/loading" type="button">Regenerate SEO</button>
    </section>
  );
}

function Proposal() {
  return (
    <section className="seo-review__proposal">
      <div className="seo-review__proposal-topline">
        <div>
          <span className="seo-review__eyebrow">SEO assistant</span>
          <h2>Copy proposal</h2>
          <p>Review every field before it becomes listing copy.</p>
        </div>
        <button className="btn btn-primary" type="button">Apply all pending</button>
      </div>

      <div className="seo-review__warning">
        <strong>Review note</strong>
        <span>The brief does not name a recipient, so gift language is limited to broad outdoor interest.</span>
      </div>

      <ProposalCard
        title="Title"
        action="Accept title"
        current={<p>Take A Hike Mountain Tee</p>}
        proposed={<p>Retro Take A Hike Mountain Graphic Tee</p>}
      />
      <ProposalCard
        title="Tags"
        action="Accept tags"
        current={<p className="text-muted">No tags yet</p>}
        proposed={<div className="chips">{proposedTags.map((tag) => <span className="chip" key={tag}>{tag}</span>)}</div>}
      />
      <ProposalCard
        title="Description lead"
        action="Accept lead"
        current={<p className="text-muted">No lead yet</p>}
        proposed={<p>A retro mountain graphic tee for hikers and outdoor lovers, featuring the exact words “Take A Hike” above a warm sunset trail scene.</p>}
      />

      <details className="seo-review__rationale">
        <summary>Search rationale · 7 phrases</summary>
        <p>Retro hiking shirt · core product · used in tags</p>
        <p>Mountain graphic tee · core product · used in title and tags</p>
        <p>Outdoor lover gift · bottom of funnel · used in tags</p>
      </details>
    </section>
  );
}

function ListingCopy() {
  return (
    <section className="seo-review__listing-copy">
      <div>
        <span className="seo-review__eyebrow">Listing copy</span>
        <h2>Saved fields</h2>
        <p>Accepted suggestions appear here and autosave immediately.</p>
      </div>
      <div className="field">
        <label htmlFor="seo-title">Title</label>
        <input id="seo-title" className="input" value="Take A Hike Mountain Tee" readOnly />
      </div>
      <div className="field">
        <label>Tags</label>
        <div className="chips"><span className="chips__empty">No tags yet</span></div>
      </div>
      <div className="field">
        <label htmlFor="seo-lead">Description lead</label>
        <textarea id="seo-lead" value="" placeholder="A concise first sentence for shoppers" readOnly />
      </div>
      <div className="seo-review__body-source">
        <div>
          <label htmlFor="seo-body">Description body</label>
          <p>Use a reusable body or add listing-specific copy.</p>
        </div>
        <select id="seo-body" className="input" defaultValue="common-copy/comfort-colors-standard.md">
          <option value="common-copy/comfort-colors-standard.md">Comfort Colors · standard fit and care</option>
          <option value="inline">Write listing-specific body</option>
        </select>
      </div>
    </section>
  );
}

export function ListingSeoReviewScreen({ state }: Props) {
  const panel = state === "readiness" ? <Readiness /> : state === "loading" ? <Loading /> : state === "stale" ? <Stale /> : state === "failed" ? <Failed /> : <Proposal />;

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

        {panel}
        <ListingCopy />
      </main>
    </div>
  );
}
