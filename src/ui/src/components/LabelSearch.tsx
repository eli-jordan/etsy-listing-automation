// The search box both pages share: labels are pills inside it, and plain text
// narrows what they leave by title. The caller owns both values, and applies
// them to its own list.
import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { Fragment, type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { holdsLabels } from "./labelRules";
import "./LabelSearch.css";

interface Option {
  tag: string;
  count: number;
  /** Adding it would leave nothing, so taking it replaces the pills. */
  swap: boolean;
}

/** A tag's group: the text before its colon, or null for a plain tag. Lower case,
 * so a hand-edited `Theme:` sits with `theme:`; the heading capitalises it anyway. */
function groupOf(tag: string): string | null {
  const colon = tag.indexOf(":");
  return colon > 0 ? tag.slice(0, colon).toLowerCase() : null;
}

/** Each label once, as first written: hand edits keep their case, and matching
 * ignores it. */
function distinctTags(items: string[][]): string[] {
  const spellings = new Map<string, string>();
  for (const tag of items.flat()) {
    const key = tag.toLowerCase();
    if (!spellings.has(key)) spellings.set(key, tag);
  }
  return [...spellings.values()];
}

/** Labels the typed text could mean, in their groups A to Z with plain tags last.
 * Within a group: narrowing ones first, then those starting with it, as a whole or
 * after the colon, then by count. */
function optionsFor(items: string[][], term: string, on: string[]): Option[] {
  const starts = (tag: string) => {
    const text = tag.toLowerCase();
    return Number(text.startsWith(term) || text.slice(text.indexOf(":") + 1).startsWith(term));
  };
  return distinctTags(items)
    .filter((tag) => tag.toLowerCase().includes(term) && !holdsLabels(on, [tag]))
    .map((tag) => {
      const narrowed = items.filter((tags) => holdsLabels(tags, [...on, tag])).length;
      return narrowed > 0
        ? { tag, count: narrowed, swap: false }
        : { tag, count: items.filter((tags) => holdsLabels(tags, [tag])).length, swap: true };
    })
    .sort(
      (a, b) =>
        Number(groupOf(a.tag) === null) - Number(groupOf(b.tag) === null) ||
        (groupOf(a.tag) ?? "").localeCompare(groupOf(b.tag) ?? "") ||
        Number(a.swap) - Number(b.swap) ||
        starts(b.tag) - starts(a.tag) ||
        b.count - a.count ||
        a.tag.localeCompare(b.tag),
    );
}

/** The highlight after an arrow key: it wraps at both ends, and -1 is nothing yet. */
function stepped(active: number, count: number, step: 1 | -1): number {
  if (active < 0) return step === 1 ? 0 : count - 1;
  return (active + step + count) % count;
}

/** The label with the typed part in bold. */
function Marked({ tag, term }: { tag: string; term: string }) {
  const at = term ? tag.toLowerCase().indexOf(term) : -1;
  if (at < 0) return <span>{tag}</span>;
  return (
    <span>
      {tag.slice(0, at)}
      <strong>{tag.slice(at, at + term.length)}</strong>
      {tag.slice(at + term.length)}
    </span>
  );
}

export function LabelSearch({
  items,
  on,
  onOn,
  query,
  onQuery,
}: {
  /** Every searchable item's tags. */
  items: string[][];
  on: string[];
  onOn: (next: string[]) => void;
  query: string;
  onQuery: (next: string) => void;
}) {
  const [menu, setMenu] = useState(false);
  const [active, setActive] = useState(-1);
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const activeRow = useRef<HTMLDivElement>(null);

  // Outside clicks rather than blur: a click on an option must not close it first.
  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (box.current?.contains(event.target as Node)) return;
      setMenu(false);
      setActive(-1);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const term = query.trim().toLowerCase();
  const options = optionsFor(items, term, on);
  const menuOpen = menu && options.length > 0;
  const grouped = options.some((option) => groupOf(option.tag) !== null);
  const menuId = `${id}-menu`;
  const optionId = (index: number) => `${id}-option-${index}`;

  // The menu scrolls, and arrow keys walk past what it shows.
  useEffect(() => {
    activeRow.current?.scrollIntoView({ block: "nearest" });
  }, [active, menuOpen]);

  // Nothing stays highlighted through a close: Enter must keep meaning "title
  // search" until the seller presses an arrow key again (spec *Search*).
  const close = () => {
    setMenu(false);
    setActive(-1);
  };

  const take = (option: Option) => {
    onOn(option.swap ? [option.tag] : [...on, option.tag]);
    onQuery("");
    close();
    field.current?.focus();
  };
  const move = (event: KeyboardEvent, step: 1 | -1) => {
    event.preventDefault();
    if (options.length === 0) return;
    setMenu(true);
    setActive((current) => stepped(current, options.length, step));
  };
  const confirm = () => {
    const option = menuOpen ? options[active] : undefined;
    if (option) take(option);
    else close();
  };
  const keys: Record<string, (event: KeyboardEvent) => void> = {
    ArrowDown: (event) => move(event, 1),
    ArrowUp: (event) => move(event, -1),
    Enter: confirm,
    Escape: close,
    // An open menu would otherwise stay over the rail once focus has moved on.
    Tab: close,
    Backspace: () => {
      if (query !== "" || on.length === 0) return;
      onOn(on.slice(0, -1));
      setActive(-1);
    },
  };

  return (
    <div className="label-search" ref={box}>
      <div
        className="input label-search__box"
        onClick={() => {
          field.current?.focus();
          setMenu(true);
        }}
      >
        <MagnifyingGlassIcon weight="bold" />
        {on.map((tag) => (
          <span key={tag} className="tag tag-accent label-search__pill">
            {tag}
            <button
              type="button"
              className="label-search__x"
              aria-label={`Remove ${tag}`}
              onClick={(event) => {
                event.stopPropagation();
                onOn(on.filter((t) => t !== tag));
                setActive(-1);
                // The button is about to go, and focus would fall out of the page.
                field.current?.focus();
              }}
            >
              <XIcon weight="bold" />
            </button>
          </span>
        ))}
        <input
          ref={field}
          className="label-search__field"
          type="text"
          role="combobox"
          aria-label="Search templates by title or label"
          aria-expanded={menuOpen}
          aria-autocomplete="list"
          aria-controls={menuOpen ? menuId : undefined}
          aria-activedescendant={menuOpen && active >= 0 ? optionId(active) : undefined}
          placeholder={on.length > 0 ? "Search titles…" : "Search or add a label…"}
          value={query}
          onChange={(event) => {
            onQuery(event.target.value);
            setMenu(true);
            setActive(-1);
          }}
          onKeyDown={(event) => keys[event.key]?.(event)}
        />
      </div>
      {menuOpen && (
        <div className="label-search__menu" id={menuId} role="listbox" aria-label="Labels">
          {options.map((option, index) => {
            const group = groupOf(option.tag);
            const startsGroup = index === 0 || groupOf(options[index - 1]?.tag ?? "") !== group;
            return (
              <Fragment key={option.tag}>
                {grouped && startsGroup && (
                  <div className="label-search__group" role="presentation">
                    {group ?? "Other"}
                  </div>
                )}
                <div
                  id={optionId(index)}
                  ref={index === active ? activeRow : undefined}
                  role="option"
                  aria-selected={index === active}
                  className={`label-search__item${index === active ? " label-search__item--active" : ""}`}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => take(option)}
                >
                  <Marked tag={option.tag} term={term} />
                  {option.swap && (
                    <span className="label-search__swap">replaces {on.join(", ")}</span>
                  )}
                  <span className="label-search__count">{option.count}</span>
                </div>
              </Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}
