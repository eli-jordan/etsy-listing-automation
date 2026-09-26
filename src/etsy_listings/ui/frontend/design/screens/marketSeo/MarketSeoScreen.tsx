import { useState, type ComponentProps } from "react";
import { StatusTag } from "../../../src/components/StatusTag";
import { AiChoiceDrawer } from "../../../src/pages/editor/aiSeo/AiChoiceDrawer";
import { AiTagsDrawer } from "../../../src/pages/editor/aiSeo/AiTagsDrawer";
import { ShellSidebar } from "../../../src/shell/ShellSidebar";
import { AiWorkflowIndicator, type WorkflowStep } from "./AiWorkflowIndicator";
import { MarketListingsPanel } from "./MarketListingsPanel";
import "./marketSeo.css";

const titles = [
  "Take A Hike Shirt, Retro Hiking Tee, Mountain Sunset Graphic T-Shirt, Hiker Gift",
  "Retro Hiking Shirt, Take A Hike Mountain Tee, Outdoor Lover Gift for Hikers",
  "Take A Hike Retro Sunset T-Shirt, Vintage Mountain Graphic Tee, National Park Gift",
];

const leads = [
  "Take a hike in style with this retro mountain sunset tee, a gift for hikers that says it with a wink.",
  "A warm 70s sunset over a winding trail, topped with the words “Take A Hike” — made for weekend hikers and outdoor lovers.",
  "Trail days, road trips and campfire nights: this retro hiking shirt pairs a mountain sunset with a friendly nudge outdoors.",
];

const tagPool = [
  "retro hiking shirt", "hiker gift", "take a hike shirt", "mountain graphic tee", "outdoor lover gift",
  "national park tee", "nature shirt", "adventure shirt", "sunset hiking tee", "camping shirt",
  "trail shirt", "hiking t shirt", "70s graphic tee", "vintage mountain tee", "gift for hikers",
  "road trip shirt", "wanderlust tee", "mountain lover gift", "hiking humor", "unisex hiking tee",
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
    <svg aria-hidden="true" viewBox="0 0 20 20" width="14" height="14">
      <path className="seo-sparkle-primary" d="M8.2 2.2c.5 3.1 1.5 4.1 4.6 4.6-3.1.5-4.1 1.5-4.6 4.6-.5-3.1-1.5-4.1-4.6-4.6 3.1-.5 4.1-1.5 4.6-4.6Z" />
      <path className="seo-sparkle-secondary" d="M14.5 11.2c.3 2 1 2.7 3 3-2 .3-2.7 1-3 3-.3-2-1-2.7-3-3 2-.3 2.7-1 3-3Z" />
    </svg>
  );
}


/**
 * Listing Details with the market-informed chain: the workflow indicator in the
 * page head and the top listings panel beside the fields. Mirrors the real
 * `ListingEditorPage` + `DetailsTab` markup; only the new parts are new.
 */
export function MarketSeoScreen({
  steps,
  panel,
  brief,
  suggestions = false,
  elapsed,
}: {
  steps: WorkflowStep[] | null;
  panel: ComponentProps<typeof MarketListingsPanel>;
  brief: string;
  suggestions?: boolean;
  elapsed?: string;
}) {
  const [title, setTitle] = useState("Take A Hike Mountain Tee");
  const [lead, setLead] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [open, setOpen] = useState({ title: suggestions, tags: suggestions, lead: suggestions });
  const busy = elapsed !== undefined;
  const toggleTag = (tag: string) =>
    setTags((cur) => (cur.includes(tag) ? cur.filter((t) => t !== tag) : cur.length < 13 ? [...cur, tag] : cur));

  return (
    <div className="shell">
      <Sidebar />
      <main className="shell__main">
        <div className="editor">
          <div className="page-head">
            <span className="page-head__crumb">Listings</span>
            <span className="page-head__sep">/</span>
            <h1 className="page-head__title">Take a hike</h1>
            <StatusTag status="draft" />
            <span className="page-head__meta">Saved a moment ago</span>
            {steps && <AiWorkflowIndicator steps={steps} />}
            <div className="page-head__actions dv-head-actions">
              <button className="btn btn-primary" type="button">Deploy changes →</button>
            </div>
          </div>

          <div className="design-select">
            <div className="design-row">
              <span className="design-thumb design-thumb--empty" aria-hidden="true" />
              <div className="design-row__text">
                <div className="design-row__name">take-a-hike</div>
                <div className="design-row__file">designs/take-a-hike.png</div>
              </div>
              <button className="design-row__change" type="button">Change ▾</button>
            </div>
          </div>

          <div className="tabs seg">
            <div className="seg-opt">Variants</div>
            <div className="seg-opt">Listing Images</div>
            <div className="seg-opt seg-opt--on">Listing Details</div>
          </div>

          <div className="mkt-layout">
            <div className="details-tab">
              <fieldset className="seo-details-fieldset">
                <legend className="seo-details-legend">Listing details</legend>

                <div className="seo-brief-row">
                  <div className="field">
                    <label htmlFor="details-brief">Brief</label>
                    <textarea id="details-brief" value={brief} placeholder="Describe the design and include any exact words shown in it." readOnly />
                  </div>
                  <div className="seo-ai-mode-anchor">
                    <button className={busy ? "btn btn-secondary seo-ai-mode seo-ai-mode--busy" : "btn btn-secondary seo-ai-mode"} disabled={busy} type="button">
                      <SparkleIcon /> AI Mode
                    </button>
                  </div>
                  {busy && (
                    <div className="seo-ai-mode-progress">
                      <span className="seo-ai-mode-elapsed">Generating for {elapsed} seconds</span>
                      <button type="button">Cancel</button>
                    </div>
                  )}
                </div>

                <div className="field">
                  <label htmlFor="details-title">Title</label>
                  <div className="field__line">
                    <div className="field__stack">
                      <input id="details-title" className="input" value={title} readOnly />
                      {open.title && (
                        <AiChoiceDrawer field="title" options={titles} stale={false} rationale={[]} warnings={[]} observedText="Take A Hike"
                          onChoose={(v) => { setTitle(v); setOpen((o) => ({ ...o, title: false })); }}
                          onReject={() => setOpen((o) => ({ ...o, title: false }))} />
                      )}
                    </div>
                    <span className="field__count">{title.length} / 140</span>
                  </div>
                </div>

                <div className="field">
                  <label htmlFor="details-tag-draft">Tags</label>
                  <div className="chips">
                    {tags.map((t) => <span key={t} className="chip">{t}<span className="chip__x" onClick={() => toggleTag(t)}>×</span></span>)}
                    {tags.length === 0 && <span className="chips__empty">No tags yet</span>}
                  </div>
                  <div className="field__line">
                    <div className="field__stack">
                      <input id="details-tag-draft" className="input tag-paste" placeholder="Type or paste tags, comma separated — press Enter to add" readOnly />
                      {open.tags && (
                        <AiTagsDrawer tags={tagPool} selected={tags} stale={false} rationale={[]} warnings={[]} observedText="Take A Hike"
                          onToggle={toggleTag}
                          onAcceptBest={() => { setTags(tagPool.slice(0, 13)); setOpen((o) => ({ ...o, tags: false })); }}
                          onClose={() => setOpen((o) => ({ ...o, tags: false }))} />
                      )}
                    </div>
                    <span className="field__count">{tags.length} / 13</span>
                  </div>
                </div>

                <div className="field">
                  <label htmlFor="details-description-lead">Description Lead</label>
                  <textarea id="details-description-lead" value={lead} readOnly />
                  {open.lead && (
                    <AiChoiceDrawer field="description lead" options={leads} stale={false} rationale={[]} warnings={[]} observedText="Take A Hike"
                      onChoose={(v) => { setLead(v); setOpen((o) => ({ ...o, lead: false })); }}
                      onReject={() => setOpen((o) => ({ ...o, lead: false }))} />
                  )}
                </div>

                <div className="field">
                  <label htmlFor="details-section">Section</label>
                  <select id="details-section" className="input" defaultValue="Graphic Tees"><option>Graphic Tees</option><option>Outdoor Gifts</option></select>
                </div>
                <div className="field">
                  <label htmlFor="details-materials">Materials</label>
                  <input id="details-materials" className="input" value="ring-spun cotton" readOnly />
                  <span className="field__hint">Set by the selected garment profile.</span>
                </div>
              </fieldset>
            </div>

            <MarketListingsPanel {...panel} />
          </div>
        </div>
      </main>
    </div>
  );
}

