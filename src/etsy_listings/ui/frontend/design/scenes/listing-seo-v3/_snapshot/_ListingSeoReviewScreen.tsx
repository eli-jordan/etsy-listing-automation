import { useState } from "react";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import "./listingSeoReview.css";

export type SeoReviewState = "readiness" | "loading" | "proposal" | "stale" | "failed";

interface Props {
  state: SeoReviewState;
}

type SuggestionKey = "title" | "tags" | "lead";

const titleOptions = [
  "Retro Take A Hike Mountain Graphic Tee",
  "Take A Hike Retro Sunset Hiking Shirt",
  "Vintage Mountain Trail Outdoor Lover Tee",
];

const leadOptions = [
  "A retro mountain graphic tee for hikers and outdoor lovers, featuring the exact words “Take A Hike” above a warm sunset trail scene.",
  "Bring trail-day energy to an everyday tee with a vintage mountain sunset and the playful phrase “Take A Hike.”",
  "Made for hikers, campers, and mountain lovers, this relaxed graphic tee pairs a warm retro landscape with an outdoorsy sense of humour.",
];

const tagOptions = [
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
  "sunset mountain tee",
  "hiking humor shirt",
  "camping lover gift",
  "vintage nature tee",
  "wanderlust shirt",
  "unisex hiking tee",
  "outdoorsy graphic",
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

function SparkleIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20">
      <path d="M8.2 2.2c.5 3.1 1.5 4.1 4.6 4.6-3.1.5-4.1 1.5-4.6 4.6-.5-3.1-1.5-4.1-4.6-4.6 3.1-.5 4.1-1.5 4.6-4.6Z" />
      <path d="M14.5 11.2c.3 2 1 2.7 3 3-2 .3-2.7 1-3 3-.3-2-1-2.7-3-3 2-.3 2.7-1 3-3Z" />
    </svg>
  );
}

function AiModeButton({ state }: { state: SeoReviewState }) {
  const disabled = state === "readiness" || state === "loading";
  return (
    <span className="seo-review__generate-wrap">
      <button
        className="seo-review__generate"
        data-goto={disabled ? undefined : "listing-seo-v3/loading"}
        disabled={disabled}
        type="button"
      >
        <SparkleIcon />
        AI Mode
        {state === "loading" ? <span className="seo-review__button-pulse" aria-hidden="true" /> : null}
      </button>
      {state === "readiness" ? (
        <span className="seo-review__hover-card" role="tooltip">
          Select a design and add a listing brief first.
        </span>
      ) : null}
    </span>
  );
}

function ChoiceDrawer({
  field,
  options,
  stale,
  onChoose,
  onReject,
}: {
  field: "title" | "description lead";
  options: string[];
  stale: boolean;
  onChoose: (value: string) => void;
  onReject: () => void;
}) {
  return (
    <aside className={`seo-suggestion${stale ? " seo-suggestion--stale" : ""}`} aria-label={`${field} AI suggestions`}>
      <div className="seo-suggestion__topline">
        <span><SparkleIcon /> {stale ? "Suggestions are out of date" : "Choose one suggestion"}</span>
        <button className="seo-suggestion__quiet-action" onClick={onReject} type="button">× Reject all</button>
      </div>
      <div className="seo-choice-list">
        {options.map((option, index) => (
          <button disabled={stale} key={option} onClick={() => onChoose(option)} type="button">
            <span>{index + 1}</span>
            {option}
          </button>
        ))}
      </div>
    </aside>
  );
}

function TagsDrawer({
  selected,
  stale,
  onToggle,
  onAcceptBest,
  onClose,
}: {
  selected: string[];
  stale: boolean;
  onToggle: (tag: string) => void;
  onAcceptBest: () => void;
  onClose: () => void;
}) {
  return (
    <aside className={`seo-suggestion${stale ? " seo-suggestion--stale" : ""}`} aria-label="tag AI suggestions">
      <div className="seo-suggestion__topline">
        <span><SparkleIcon /> {stale ? "Suggestions are out of date" : "20 ranked suggestions"}</span>
        <div className="seo-suggestion__actions">
          <button className="seo-suggestion__quiet-action" onClick={onClose} type="button">Close</button>
          <button disabled={stale} onClick={onAcceptBest} type="button">✓ Accept best 13</button>
        </div>
      </div>
      <div className="seo-tag-group">
        <small>Best 13</small>
        <div className="seo-tag-pool">
          {tagOptions.slice(0, 13).map((tag) => (
            <TagChoice key={tag} tag={tag} selected={selected.includes(tag)} disabled={stale || (selected.length >= 13 && !selected.includes(tag))} onToggle={onToggle} />
          ))}
        </div>
      </div>
      <div className="seo-tag-group seo-tag-group--more">
        <small>More options</small>
        <div className="seo-tag-pool">
          {tagOptions.slice(13).map((tag) => (
            <TagChoice key={tag} tag={tag} selected={selected.includes(tag)} disabled={stale || (selected.length >= 13 && !selected.includes(tag))} onToggle={onToggle} />
          ))}
        </div>
      </div>
      <p className="seo-suggestion__count">{selected.length} of 13 tags selected</p>
    </aside>
  );
}

function TagChoice({
  tag,
  selected,
  disabled,
  onToggle,
}: {
  tag: string;
  selected: boolean;
  disabled: boolean;
  onToggle: (tag: string) => void;
}) {
  return (
    <button
      aria-pressed={selected}
      className={selected ? "seo-tag-choice seo-tag-choice--selected" : "seo-tag-choice"}
      disabled={disabled}
      onClick={() => onToggle(tag)}
      type="button"
    >
      {selected ? "✓ " : "+ "}{tag}
    </button>
  );
}

export function ListingSeoReviewScreen({ state }: Props) {
  const hasSuggestions = state === "proposal" || state === "stale";
  const [pending, setPending] = useState<Record<SuggestionKey, boolean>>({ title: hasSuggestions, tags: hasSuggestions, lead: hasSuggestions });
  const [title, setTitle] = useState("Take A Hike Mountain Tee");
  const [tags, setTags] = useState<string[]>([]);
  const [lead, setLead] = useState("");

  const close = (key: SuggestionKey) => setPending((current) => ({ ...current, [key]: false }));
  const chooseTitle = (value: string) => { setTitle(value); close("title"); };
  const chooseLead = (value: string) => { setLead(value); close("lead"); };
  const toggleTag = (tag: string) => setTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : current.length < 13 ? [...current, tag] : current);
  const acceptBestTags = () => { setTags(tagOptions.slice(0, 13)); close("tags"); };

  return (
    <div className="shell seo-review">
      <Sidebar />
      <main className="shell__main seo-review__main">
        <header className="page-head">
          <span className="page-head__crumb">Listings</span><span className="page-head__sep">/</span>
          <h1 className="page-head__title">Take a hike</h1><span className="page-head__meta">Saved just now</span>
          <span className="seo-review__draft">Draft</span>
          <button className="btn btn-secondary seo-review__deploy" type="button">Deploy changes</button>
        </header>

        <div className="design-select"><div className="design-row">
          <span className="design-thumb design-thumb--empty" aria-hidden="true" />
          <div className="design-row__text"><strong className="design-row__name">take-a-hike.png</strong><span>Selected design</span></div>
        </div></div>

        <div className="tabs seg" role="tablist" aria-label="Listing editor sections">
          <button className="seg-opt" type="button">Variants</button><button className="seg-opt" type="button">Listing Images</button>
          <button className="seg-opt seg-opt--on" type="button">Listing Details</button>
        </div>

        <section className="seo-review__fields">
          <div className="seo-review__fields-head">
            <div><h2>Listing details</h2><p>Copy shown to shoppers on Etsy.</p></div>
            <AiModeButton state={state} />
          </div>

          {state === "failed" ? <div className="seo-review__inline-status" role="status"><span>AI Mode couldn’t generate valid suggestions. Nothing changed.</span><button data-goto="listing-seo-v3/loading" type="button">Try again</button></div> : null}
          {state === "loading" ? <div className="seo-review__inline-status" role="status"><span className="seo-review__pulse" aria-hidden="true" /><span>AI Mode is creating suggestions from the current listing…</span><button data-goto="listing-seo-v3/review" type="button">View result</button></div> : null}

          <div className="field seo-field">
            <div className="seo-field__label"><label htmlFor="seo-title">Title</label><span>{title.length} / 140</span></div>
            <input id="seo-title" className="input" value={title} readOnly />
            {pending.title ? <ChoiceDrawer field="title" options={titleOptions} stale={state === "stale"} onChoose={chooseTitle} onReject={() => close("title")} /> : null}
          </div>

          <div className="field seo-field">
            <div className="seo-field__label"><label>Tags</label><span>{tags.length} / 13</span></div>
            <div className="seo-field__surface">
              {tags.length ? <div className="seo-selected-tags">{tags.map((tag) => <button aria-label={`Remove ${tag}`} key={tag} onClick={() => toggleTag(tag)} type="button">{tag} ×</button>)}</div> : <span className="chips__empty">No tags yet</span>}
            </div>
            {pending.tags ? <TagsDrawer selected={tags} stale={state === "stale"} onToggle={toggleTag} onAcceptBest={acceptBestTags} onClose={() => close("tags")} /> : null}
          </div>

          <div className="field seo-field">
            <div className="seo-field__label"><label htmlFor="seo-lead">Description lead</label><span>{lead.length} / 500</span></div>
            <textarea id="seo-lead" value={lead} placeholder="A concise first sentence for shoppers" readOnly />
            {pending.lead ? <ChoiceDrawer field="description lead" options={leadOptions} stale={state === "stale"} onChoose={chooseLead} onReject={() => close("lead")} /> : null}
          </div>

          <div className="seo-review__body-source">
            <div><label htmlFor="seo-body">Description body</label><p>Use reusable common copy or write listing-specific copy.</p></div>
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
