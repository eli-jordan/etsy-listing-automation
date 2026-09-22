import { useEffect, useState } from "react";
import { StatusTag } from "../../src/components/StatusTag";
import { ShellSidebar } from "../../src/shell/ShellSidebar";
import "./listingSeoReview.css";

type SuggestionKey = "title" | "tags" | "lead";
type AiModeState = "idle" | "loading" | "ready";

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

function ChoiceDrawer({ field, options, onChoose, onReject }: { field: "title" | "description lead"; options: string[]; onChoose: (value: string) => void; onReject: () => void }) {
  return (
    <aside className="card seo-suggestion" aria-label={`${field} AI suggestions`}>
      <div className="seo-suggestion__head">
        <span className="section-label"><SparkleIcon /> Choose one</span>
        <button className="btn btn-ghost seo-suggestion__reject" onClick={onReject} type="button">Reject all</button>
      </div>
      <div className="seo-choice-list">
        {options.map((option, index) => (
          <button className="template-card seo-choice" key={option} onClick={() => onChoose(option)} type="button">
            <span className="tag tag-accent">{index + 1}</span>
            <span>{option}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function TagsDrawer({ selected, onToggle, onAcceptBest, onClose }: { selected: string[]; onToggle: (tag: string) => void; onAcceptBest: () => void; onClose: () => void }) {
  return (
    <aside className="card seo-suggestion" aria-label="tag AI suggestions">
      <div className="seo-suggestion__head">
        <span className="section-label"><SparkleIcon /> 20 ranked suggestions</span>
        <div className="seo-suggestion__actions">
          <button className="btn btn-ghost" onClick={onClose} type="button">Close</button>
          <button className="btn btn-secondary" onClick={onAcceptBest} type="button">Accept best 13</button>
        </div>
      </div>
      <TagPool label="Best 13" tags={tagOptions.slice(0, 13)} selected={selected} onToggle={onToggle} />
      <TagPool label="More options" tags={tagOptions.slice(13)} selected={selected} onToggle={onToggle} />
      <span className="field__hint">{selected.length} of 13 tags selected</span>
    </aside>
  );
}

function TagPool({ label, tags, selected, onToggle }: { label: string; tags: string[]; selected: string[]; onToggle: (tag: string) => void }) {
  return (
    <div className="seo-tag-group">
      <span className="section-label">{label}</span>
      <div className="chips">
        {tags.map((tag) => {
          const active = selected.includes(tag);
          return (
            <button
              aria-pressed={active}
              className={active ? "chip seo-tag-choice seo-tag-choice--selected" : "chip seo-tag-choice"}
              disabled={selected.length >= 13 && !active}
              key={tag}
              onClick={() => onToggle(tag)}
              type="button"
            >
              {active ? "✓" : "+"} {tag}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ListingSeoReviewScreen() {
  const [aiMode, setAiMode] = useState<AiModeState>("idle");
  const [pending, setPending] = useState<Record<SuggestionKey, boolean>>({ title: false, tags: false, lead: false });
  const [title, setTitle] = useState("Take A Hike Mountain Tee");
  const [tags, setTags] = useState<string[]>([]);
  const [lead, setLead] = useState("");

  useEffect(() => {
    if (aiMode !== "loading") return;
    const timer = window.setTimeout(() => {
      setPending({ title: true, tags: true, lead: true });
      setAiMode("ready");
    }, 650);
    return () => window.clearTimeout(timer);
  }, [aiMode]);

  const runAiMode = () => {
    setPending({ title: false, tags: false, lead: false });
    setAiMode("loading");
  };
  const close = (key: SuggestionKey) => setPending((current) => ({ ...current, [key]: false }));
  const chooseTitle = (value: string) => { setTitle(value); close("title"); };
  const chooseLead = (value: string) => { setLead(value); close("lead"); };
  const toggleTag = (tag: string) => setTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : current.length < 13 ? [...current, tag] : current);
  const acceptBestTags = () => { setTags(tagOptions.slice(0, 13)); close("tags"); };

  return (
    <div className="shell">
      <Sidebar />
      <main className="shell__main seo-review__main">
        <div className="editor">
          <div className="page-head">
            <span className="page-head__crumb">Listings</span><span className="page-head__sep">/</span>
            <h1 className="page-head__title">Take a hike</h1>
            <StatusTag status="draft" />
            <span className="page-head__meta">Saved just now</span>
            <div className="page-head__actions"><button className="btn btn-primary" type="button">Deploy changes →</button></div>
          </div>

          <div className="design-select"><div className="design-row">
            <span className="design-thumb design-thumb--empty" aria-hidden="true" />
            <div className="design-row__text"><div className="design-row__name">take-a-hike.png</div><div className="design-row__file">designs/take-a-hike.png</div></div>
            <button className="design-row__change" type="button">Change ▾</button>
          </div></div>

          <div className="tabs seg" role="tablist" aria-label="Listing editor sections">
            <div className="seg-opt">Variants</div><div className="seg-opt">Listing Images</div><div className="seg-opt seg-opt--on">Listing Details</div>
          </div>

          <div className="details-tab">
            <fieldset className="seo-details-fieldset">
              <legend>Listing details</legend>
              <button className="btn btn-secondary seo-ai-mode" disabled={aiMode === "loading"} onClick={runAiMode} type="button">
                <SparkleIcon /> AI Mode
              </button>

              {aiMode === "loading" ? (
                <div className="add-panel seo-loading" role="status">
                  <span className="seo-loading__dot" aria-hidden="true" />
                  Generating title, tag, and description suggestions…
                </div>
              ) : null}

              <div className="field">
                <label htmlFor="details-title">Title</label>
                <input id="details-title" className="input" value={title} readOnly />
                <span className="field__hint">{title.length} / 140</span>
                {pending.title ? <ChoiceDrawer field="title" options={titleOptions} onChoose={chooseTitle} onReject={() => close("title")} /> : null}
              </div>

              <div className="field">
                <label htmlFor="details-tag-draft">Tags</label>
                <div className="chips">
                  {tags.map((tag) => <span className="chip" key={tag}>{tag}<button aria-label={`Remove ${tag}`} className="chip__x" onClick={() => toggleTag(tag)} type="button">×</button></span>)}
                  {tags.length === 0 ? <span className="chips__empty">No tags yet</span> : null}
                </div>
                <input id="details-tag-draft" className="input tag-paste" placeholder="Type or paste tags, comma separated — press Enter to add" readOnly />
                <span className="field__hint">{tags.length} / 13</span>
                {pending.tags ? <TagsDrawer selected={tags} onToggle={toggleTag} onAcceptBest={acceptBestTags} onClose={() => close("tags")} /> : null}
              </div>

              <div className="field">
                <label htmlFor="details-description-lead">Description lead</label>
                <textarea id="details-description-lead" value={lead} placeholder="The first paragraph shoppers read" readOnly />
                {pending.lead ? <ChoiceDrawer field="description lead" options={leadOptions} onChoose={chooseLead} onReject={() => close("lead")} /> : null}
              </div>

              <div className="field">
                <label htmlFor="details-description-body">Description body</label>
                <select id="details-description-body" className="input" defaultValue="common-copy/comfort-colors-standard.md">
                  <option value="common-copy/comfort-colors-standard.md">Comfort Colors · standard fit and care</option>
                  <option value="inline">Write listing-specific body</option>
                </select>
              </div>

              <div className="field"><label htmlFor="details-section">Section</label><select id="details-section" className="input" defaultValue="Graphic Tees"><option>Graphic Tees</option><option>Outdoor Gifts</option></select></div>
              <div className="field"><label htmlFor="details-materials">Materials</label><input id="details-materials" className="input" value="ring-spun cotton" readOnly /></div>
            </fieldset>

            <fieldset>
              <legend>Pricing</legend>
              <div className="field"><label htmlFor="details-pricing-plan">Plan</label><select id="details-pricing-plan" className="input" defaultValue="standard"><option value="standard">Standard NOK pricing</option></select></div>
              <div className="price-table"><div className="price-table__cell"><span className="price-table__size">S–XL</span><input aria-label="Price for sizes S to XL" className="input price-table__input" value="349" readOnly /><span className="price-table__currency">NOK</span></div><div className="price-table__cell"><span className="price-table__size">2XL</span><input aria-label="Price for size 2XL" className="input price-table__input" value="379" readOnly /><span className="price-table__currency">NOK</span></div></div>
            </fieldset>
          </div>
        </div>
      </main>
    </div>
  );
}
