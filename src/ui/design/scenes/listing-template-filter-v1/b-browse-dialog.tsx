import { ArrowsOutSimpleIcon } from "@phosphor-icons/react/dist/csr/ArrowsOutSimple";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useState } from "react";
import { hasTags, tagCounts, templates } from "./_fixtures";
import { ColourChoices, ImagesScreen, LocatorShell, TemplateRow, usePicker } from "./_ImagesScreen";

export const meta = {
  title: "B · Browse dialog · v1",
  viewport: "laptop",
  description:
    "A large photo browser over the Images tab: tags on top, photos below, colours beside the chosen photo. Retired: C won because it needs no clicks when the title matches.",
};

export default function Frame() {
  const picker = usePicker("cc1717-woman-in-cardigan-by-tree");
  const [browsing, setBrowsing] = useState(true);
  const [on, setOn] = useState(["christmas"]);
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState("cc1717-woman-in-cardigan-by-tree");
  const [open, setOpen] = useState<string | null>(null);
  const [listQuery, setListQuery] = useState("");

  const shown = templates.filter((t) => t.name.includes(query.toLowerCase()) && hasTags(t, on));
  const offered = tagCounts(shown, on);
  const picked = templates.find((t) => t.name === chosen) ?? templates[0]!;
  const toggle = (tag: string) =>
    setOn((current) =>
      current.includes(tag) ? current.filter((t) => t !== tag) : [...current, tag],
    );

  return (
    <ImagesScreen
      picker={picker}
      locator={
        <LocatorShell>
          <div className="locator__search">
            <svg viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.5-3.5" />
            </svg>
            <input
              className="input"
              type="text"
              placeholder="Search templates…"
              value={listQuery}
              onChange={(event) => setListQuery(event.target.value)}
            />
          </div>
          <button type="button" className="btn btn-secondary lf-browse" onClick={() => setBrowsing(true)}>
            <ArrowsOutSimpleIcon className="lf-icon" /> Browse templates by photo
          </button>
          <div className="locator__list">
            {templates
              .filter((t) => t.name.includes(listQuery.toLowerCase()))
              .map((t) => (
              <TemplateRow
                key={t.name}
                template={t}
                picker={picker}
                open={open === t.name}
                onToggleOpen={() => setOpen((c) => (c === t.name ? null : t.name))}
              />
            ))}
          </div>
        </LocatorShell>
      }
      overlay={
        browsing && (
          <div className="lf-backdrop">
            <div className="lf-dialog" role="dialog" aria-modal="true" aria-label="Browse templates">
              <header className="lf-dialog__head">
                <h2>Browse templates</h2>
                <span className="lf-muted">
                  {shown.length} of {templates.length}
                </span>
                <input
                  className="input lf-dialog__search"
                  type="text"
                  aria-label="Search templates"
                  placeholder="Search templates…"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
                <button
                  type="button"
                  className="lf-close"
                  aria-label="Close"
                  onClick={() => setBrowsing(false)}
                >
                  <XIcon weight="bold" />
                </button>
              </header>
              <div className="lf-pills">
                {on.map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    className="tag template-rail__pill template-rail__pill--on"
                    aria-pressed="true"
                    onClick={() => toggle(tag)}
                  >
                    {tag}
                  </button>
                ))}
                {offered.map(([tag, count]) => (
                  <button
                    key={tag}
                    type="button"
                    className="tag template-rail__pill"
                    aria-pressed="false"
                    onClick={() => toggle(tag)}
                  >
                    {tag} {count}
                  </button>
                ))}
                {on.length > 0 && (
                  <button type="button" className="lf-link" onClick={() => setOn([])}>
                    Clear
                  </button>
                )}
              </div>
              <div className="lf-dialog__body">
                <div className="lf-grid">
                  {shown.map((t) => {
                    const count = picker.inCount(t.name);
                    return (
                      <button
                        key={t.name}
                        type="button"
                        className={`lf-photo${t.name === chosen ? " lf-photo--on" : ""}`}
                        aria-pressed={t.name === chosen}
                        onClick={() => setChosen(t.name)}
                      >
                        <span className="lf-photo__face">
                          <img src={t.src} alt="" />
                          {count > 0 && <span className="lf-photo__count">{count} in listing</span>}
                        </span>
                        <span className="lf-photo__name">{t.name.replace("cc1717-", "")}</span>
                      </button>
                    );
                  })}
                  {shown.length === 0 && <p className="locator__empty">No template matches that search.</p>}
                </div>
                <aside className="lf-side">
                  <img src={picked.src} alt={picked.name} />
                  <strong>{picked.name.replace("cc1717-", "")}</strong>
                  <ColourChoices template={picked.name} picker={picker} />
                </aside>
              </div>
              <footer className="lf-dialog__foot">
                <span>{picker.media.length} of 20 images in the listing</span>
                <button type="button" className="btn btn-primary" onClick={() => setBrowsing(false)}>
                  Done
                </button>
              </footer>
            </div>
          </div>
        )
      }
    />
  );
}
