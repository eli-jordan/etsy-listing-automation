// v1 tracks the live template-labels fixtures and the app components; exact state: git
import { useState } from "react";
import { hasTags, tagCounts, templates } from "./_fixtures";
import { ImagesScreen, LocatorShell, TemplateRow, usePicker } from "./_ImagesScreen";

export const meta = {
  title: "A · Pills in the locator · v1",
  viewport: "laptop",
  description:
    "Tag pills under the locator's search, matching the Mockup Templates rail, with christmas on. Retired: C won because it needs no clicks when the title matches.",
};

const VISIBLE_TAGS = 6;

export default function Frame() {
  const picker = usePicker("cc1717-woman-in-cardigan-by-tree");
  const [on, setOn] = useState(["christmas"]);
  const [query, setQuery] = useState("");
  const [allTags, setAllTags] = useState(false);
  const [open, setOpen] = useState<string | null>("cc1717-woman-in-cardigan-by-tree");

  const shown = templates.filter((t) => t.name.includes(query.toLowerCase()) && hasTags(t, on));
  const offered = tagCounts(shown, on);
  const visible = allTags ? offered : offered.slice(0, VISIBLE_TAGS);
  // A filter must not make the listing's own choices look gone.
  const hidden = new Set(picker.media.map((m) => m.template));
  for (const t of shown) hidden.delete(t.name);
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
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
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
            {visible.map(([tag, count]) => (
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
            {offered.length > visible.length && (
              <button type="button" className="lf-link" onClick={() => setAllTags(true)}>
                + {offered.length - visible.length} more
              </button>
            )}
            {on.length > 0 && (
              <button type="button" className="lf-link" onClick={() => setOn([])}>
                Clear
              </button>
            )}
          </div>
          <div className="locator__list">
            {shown.map((t) => (
              <TemplateRow
                key={t.name}
                template={t}
                picker={picker}
                open={open === t.name}
                onToggleOpen={() => setOpen((c) => (c === t.name ? null : t.name))}
              />
            ))}
            {shown.length === 0 && <p className="locator__empty">No template matches that search.</p>}
          </div>
          {on.length > 0 && hidden.size > 0 && (
            <p className="lf-hidden">
              {hidden.size} template{hidden.size === 1 ? "" : "s"} in this listing{" "}
              {hidden.size === 1 ? "is" : "are"} filtered out.{" "}
              <button type="button" className="lf-link" onClick={() => setOn([])}>
                Show all
              </button>
            </p>
          )}
        </LocatorShell>
      }
    />
  );
}
