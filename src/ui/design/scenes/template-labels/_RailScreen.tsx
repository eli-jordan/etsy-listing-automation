// The Mockup Templates workbench with tags. The rail and header are the app's
// own classes; the search box is shared with the listing, and the label bar is
// the only other new thing here.
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useMemo, useRef, useState } from "react";
import { ViewTabs, type View } from "../../../src/components/ViewTabs";
import { LabelSearch } from "../../../src/components/LabelSearch";
import { asTag, type LabelTemplate, templates as fixtures } from "./_fixtures";

const VISIBLE_ROWS = 7;
const MAX_LABELS = 10;
const MAX_LENGTH = 30;
/** The prototype's stand-in for the calibrator's autosave debounce. */
const SAVE_DELAY = 800;

/** The text as it would be saved. */
const tidied = (text: string) => text.trim().toLowerCase().replace(/\s+/g, " ");

/** Why a new tag cannot be saved, or null when it can. */
function refusal(tag: string): string | null {
  if (tag.length > MAX_LENGTH) return `Labels can be up to ${MAX_LENGTH} characters`;
  if (!/^[a-z0-9 :-]+$/.test(tag)) return "Letters, numbers, spaces, hyphens and colons only";
  const parts = tag.split(":");
  if (parts.length > 2 || parts.some((part) => part.trim() === "")) {
    return "Use one colon with text on both sides, like theme:christmas";
  }
  return null;
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
  const term = tidied(draft);
  const suggestions = known.filter((tag) => tag.includes(term)).slice(0, 6);
  const isNew = term.length > 0 && !known.includes(term);
  const reason = isNew ? refusal(term) : null;
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
          if (event.key === "Enter" && term) {
            const tag = suggestions[0] ?? (reason ? null : term);
            if (tag) onAdd(tag);
          }
        }}
      />
      <div className="tl-pop tl-combo__list" role="listbox" aria-label="Label suggestions">
        {suggestions.map((tag) => (
          <button key={tag} type="button" role="option" className="tl-option" onClick={() => onAdd(tag)}>
            {tag}
          </button>
        ))}
        {reason && <p className="tl-reason">{reason}</p>}
        {isNew && !reason && (
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
  initialQuery = "",
  initialMenu = false,
  initialActive = -1,
}: {
  initialOn?: string[];
  initialSelected: string;
  /** Set to open the add-a-label field already typed into. */
  initialDraft?: string;
  initialQuery?: string;
  initialMenu?: boolean;
  initialActive?: number;
}) {
  const [tags, setTags] = useState(initialTags);
  const [on, setOn] = useState(initialOn);
  const [selected, setSelected] = useState(initialSelected);
  const [query, setQuery] = useState(initialQuery);
  const [status, setStatus] = useState<"all" | LabelTemplate["status"]>("all");
  const [allRows, setAllRows] = useState(false);
  const [draft, setDraft] = useState(initialDraft ?? "");
  const [adding, setAdding] = useState(initialDraft !== undefined);
  const [view, setView] = useState<View>("calibrate");
  const [saving, setSaving] = useState(false);
  const unsaved = useRef<((all: Record<string, string[]>) => Record<string, string[]>)[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // The status pills apply first, so the box only counts what they leave.
  const inStatus = useMemo(
    () => fixtures.filter((t) => status === "all" || t.status === status),
    [status],
  );
  const shown = useMemo(() => {
    const term = query.trim().toLowerCase();
    return inStatus.filter(
      (t) => t.name.includes(term) && on.every((tag) => (tags[t.name] ?? []).includes(tag)),
    );
  }, [inStatus, query, on, tags]);

  const rows = allRows ? shown : shown.slice(0, VISIBLE_ROWS);
  const open = fixtures.find((t) => t.name === selected) ?? fixtures[0]!;
  const openTags = tags[open.name] ?? [];
  const known = [...new Set(Object.values(tags).flat())]
    .filter((tag) => !openTags.includes(tag))
    .sort();

  // A chip changes only once the debounced save lands, so quick edits land together.
  const stage = (edit: (all: Record<string, string[]>) => Record<string, string[]>) => {
    unsaved.current.push(edit);
    setSaving(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const edits = unsaved.current;
      unsaved.current = [];
      setTags((current) => edits.reduce((all, apply) => apply(all), current));
      setSaving(false);
    }, SAVE_DELAY);
  };
  const addTag = (tag: string) => {
    stage((all) => ({ ...all, [open.name]: [...(all[open.name] ?? []), tag] }));
    setDraft("");
    setAdding(false);
  };
  const removeTag = (tag: string) =>
    stage((all) => ({ ...all, [open.name]: (all[open.name] ?? []).filter((t) => t !== tag) }));

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
          <LabelSearch
            items={inStatus.map((t) => tags[t.name] ?? [])}
            on={on}
            onOn={setOn}
            query={query}
            onQuery={setQuery}
            initialMenu={initialMenu}
            initialActive={initialActive}
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
              <button
                type="button"
                className="tl-add"
                disabled={openTags.length >= MAX_LABELS}
                title={
                  openTags.length >= MAX_LABELS ? `Templates hold up to ${MAX_LABELS} labels` : undefined
                }
                onClick={() => setAdding(true)}
              >
                <PlusIcon className="tl-icon" /> Add label
              </button>
            )}
            {saving && <span className="app__meta">Saving…</span>}
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
