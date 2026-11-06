// Direction A: free-form tags on the workbench that exists today. The rail and
// header are the app's own classes; only the tag row and label bar are new.
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useMemo, useState } from "react";
import { ViewTabs, type View } from "../../../src/components/ViewTabs";
import { type LabelTemplate, templates as fixtures } from "./_fixtures";

const VISIBLE_TAGS = 6;
const VISIBLE_ROWS = 7;

/** A free-form tag is whatever the seller typed, so it reads lower case and
 * carries its own noun: "female model" rather than a Model group's "Female". */
function asTag(label: string): string | null {
  if (label === "On model") return null;
  if (label === "Female" || label === "Male") return `${label.toLowerCase()} model`;
  return label.toLowerCase();
}

function initialTags(): Record<string, string[]> {
  return Object.fromEntries(
    fixtures.map((t) => [t.name, t.labels.flatMap((l) => asTag(l) ?? [])]),
  );
}

function RailRow({
  template,
  tags,
  selected,
  onSelect,
}: {
  template: LabelTemplate;
  tags: string[];
  selected: boolean;
  onSelect: () => void;
}) {
  const ready = template.status === "Ready";
  return (
    <button
      type="button"
      className={`template-rail__item${selected ? " template-rail__item--active" : ""}`}
      aria-current={selected ? "true" : undefined}
      onClick={onSelect}
    >
      <img className="template-rail__thumb" src={template.src} alt="" />
      <span className="template-rail__text">
        <span className="template-rail__name">{template.name}</span>
        <span className="template-rail__meta">Colour Matrix</span>
        <span className={`tl-rail-tags${tags.length === 0 ? " tl-rail-tags--none" : ""}`}>
          {tags.length > 0 ? tags.join(" · ") : "No labels"}
        </span>
        {!ready && <span className="mg-rail-state">{template.status}</span>}
      </span>
    </button>
  );
}

function AddLabel({
  known,
  draft,
  onDraft,
  onAdd,
  onClose,
}: {
  known: string[];
  draft: string;
  onDraft: (value: string) => void;
  onAdd: (tag: string) => void;
  onClose: () => void;
}) {
  const term = draft.trim().toLowerCase();
  const suggestions = known.filter((tag) => tag.includes(term)).slice(0, 6);
  const isNew = term.length > 0 && !known.includes(term);
  return (
    <div className="tl-combo">
      <input
        className="input tl-combo__input"
        autoFocus
        aria-label="Add a label"
        placeholder="Add a label…"
        value={draft}
        onChange={(event) => onDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
          if (event.key === "Enter" && term) onAdd(suggestions[0] ?? term);
        }}
      />
      <div className="tl-pop tl-combo__list" role="listbox" aria-label="Label suggestions">
        {suggestions.map((tag) => (
          <button key={tag} type="button" role="option" className="tl-option" onClick={() => onAdd(tag)}>
            {tag}
          </button>
        ))}
        {isNew && (
          <button type="button" role="option" className="tl-option" onClick={() => onAdd(term)}>
            <PlusIcon className="tl-icon" /> Create “{term}”
          </button>
        )}
      </div>
    </div>
  );
}

export function RailScreen({
  initialOn = [],
  initialSelected,
  initialDraft,
}: {
  initialOn?: string[];
  initialSelected: string;
  /** Set to open the add-a-label field already typed into. */
  initialDraft?: string;
}) {
  const [tags, setTags] = useState(initialTags);
  const [on, setOn] = useState(initialOn);
  const [selected, setSelected] = useState(initialSelected);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"all" | LabelTemplate["status"]>("all");
  const [allTags, setAllTags] = useState(false);
  const [allRows, setAllRows] = useState(false);
  const [draft, setDraft] = useState(initialDraft ?? "");
  const [adding, setAdding] = useState(initialDraft !== undefined);
  const [view, setView] = useState<View>("calibrate");

  const shown = useMemo(() => {
    const term = search.trim().toLowerCase();
    return fixtures.filter(
      (t) =>
        t.name.includes(term) &&
        (status === "all" || t.status === status) &&
        on.every((tag) => (tags[t.name] ?? []).includes(tag)),
    );
  }, [search, status, on, tags]);

  // What the next click can still find: tags held by the templates on show,
  // busiest first. Tags that would empty the list are simply not offered.
  const counts = useMemo(() => {
    const tally = new Map<string, number>();
    for (const t of shown) {
      for (const tag of tags[t.name] ?? []) tally.set(tag, (tally.get(tag) ?? 0) + 1);
    }
    return [...tally].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [shown, tags]);

  const offered = counts.filter(([tag]) => !on.includes(tag));
  const visibleOffered = allTags ? offered : offered.slice(0, VISIBLE_TAGS);
  const hiddenTags = offered.length - visibleOffered.length;
  const rows = allRows ? shown : shown.slice(0, VISIBLE_ROWS);
  const open = fixtures.find((t) => t.name === selected) ?? fixtures[0]!;
  const openTags = tags[open.name] ?? [];
  const known = [...new Set(Object.values(tags).flat())]
    .filter((tag) => !openTags.includes(tag))
    .sort();

  const toggle = (tag: string) =>
    setOn((current) =>
      current.includes(tag) ? current.filter((t) => t !== tag) : [...current, tag],
    );
  const addTag = (tag: string) => {
    setTags((current) => ({ ...current, [open.name]: [...(current[open.name] ?? []), tag] }));
    setDraft("");
    setAdding(false);
  };
  const removeTag = (tag: string) =>
    setTags((current) => ({
      ...current,
      [open.name]: (current[open.name] ?? []).filter((t) => t !== tag),
    }));

  return (
    <div className="tl-app">
      <header className="app__header">
        <h1 className="app__title">Mockup Templates</h1>
        <span className="app__crumb-sep">/</span>
        <span className="app__crumb">{open.name}</span>
        <span className="tag mg-status mg-status--ready">{open.status}</span>
        <span className="app__meta">Colour Matrix · 33 colours</span>
      </header>

      <div className="app__workbench">
        <nav className="template-rail" aria-label="Templates">
          <input
            className="input template-rail__search"
            type="search"
            aria-label="Search templates"
            placeholder="Search templates…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <div className="template-rail__filters">
            {(
              [
                ["all", "All 16"],
                ["Needs maps", "Needs maps 1"],
                ["Ready", "Ready 15"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`tag template-rail__pill${status === value ? " template-rail__pill--on" : ""}`}
                aria-pressed={status === value}
                onClick={() => setStatus(value)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="tl-rail-labels">
            <div className="tl-rail-labels__head">
              <span>Labels</span>
              {on.length > 0 && (
                <button type="button" className="tl-link" onClick={() => setOn([])}>
                  Clear
                </button>
              )}
            </div>
            <div className="template-rail__filters">
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
              {visibleOffered.map(([tag, count]) => (
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
              {hiddenTags > 0 && (
                <button type="button" className="tl-link tl-link--pill" onClick={() => setAllTags(true)}>
                  {`+ ${hiddenTags} more`}
                </button>
              )}
            </div>
          </div>

          <section className="template-rail__group">
            <h2 className="template-rail__heading">{`Templates · ${shown.length}`}</h2>
            {rows.map((t) => (
              <RailRow
                key={t.name}
                template={t}
                tags={tags[t.name] ?? []}
                selected={t.name === selected}
                onSelect={() => setSelected(t.name)}
              />
            ))}
            {shown.length === 0 && <p className="template-rail__empty">No templates match.</p>}
            {shown.length > rows.length && (
              <button type="button" className="template-rail__more" onClick={() => setAllRows(true)}>
                {`+ ${shown.length - rows.length} more`}
              </button>
            )}
          </section>
        </nav>

        <div className="app__workspace">
          <div className="tl-labelbar">
            <span className="tl-labelbar__title">Labels</span>
            {openTags.map((tag) => (
              <span key={tag} className="tag tag-neutral tl-chip">
                {tag}
                <button
                  type="button"
                  className="tl-chip__x"
                  aria-label={`Remove ${tag}`}
                  onClick={() => removeTag(tag)}
                >
                  <XIcon weight="bold" />
                </button>
              </span>
            ))}
            {adding ? (
              <AddLabel
                known={known}
                draft={draft}
                onDraft={setDraft}
                onAdd={addTag}
                onClose={() => setAdding(false)}
              />
            ) : (
              <button type="button" className="tl-add" onClick={() => setAdding(true)}>
                <PlusIcon className="tl-icon" /> Add label
              </button>
            )}
          </div>

          <div className="app__main">
            <div className="app__preview">
              <img className="tl-photo" src={open.src} alt={open.name} />
            </div>
            <aside className="app__controls">
              <ViewTabs value={view} onChange={setView} />
              <div className="tl-stub">
                <strong>Renderer</strong>
                <span>Marigold</span>
              </div>
              <div className="tl-stub">
                <strong>Placement</strong>
                <span>Unchanged by labels</span>
              </div>
            </aside>
          </div>
        </div>
      </div>
    </div>
  );
}
