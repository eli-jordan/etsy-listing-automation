import { MagnifyingGlassIcon } from "@phosphor-icons/react/dist/csr/MagnifyingGlass";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { Fragment, type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { holdsLabels } from "./labelRules";
import "./LabelSearch.css";

interface Option {
  tag: string;
  count: number;
  swap: boolean;
}

function groupOf(tag: string): string | null {
  const colon = tag.indexOf(":");
  return colon > 0 ? tag.slice(0, colon).toLowerCase() : null;
}

function distinctTags(items: string[][]): string[] {
  const spellings = new Map<string, string>();
  for (const tag of items.flat()) {
    const key = tag.toLowerCase();
    if (!spellings.has(key)) spellings.set(key, tag);
  }
  return [...spellings.values()];
}

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

const NO_HIGHLIGHT = -1;

/** The highlight after an arrow key: it wraps at both ends. */
function stepped(active: number, count: number, step: 1 | -1): number {
  if (active === NO_HIGHLIGHT) return step === 1 ? 0 : count - 1;
  return (active + step + count) % count;
}

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
  const [active, setActive] = useState(NO_HIGHLIGHT);
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const activeRow = useRef<HTMLDivElement>(null);

  // Outside clicks rather than blur: a click on an option must not close it first.
  useEffect(() => {
    const onDown = (event: MouseEvent) => {
      if (box.current?.contains(event.target as Node)) return;
      setMenu(false);
      setActive(NO_HIGHLIGHT);
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

  useEffect(() => {
    activeRow.current?.scrollIntoView({ block: "nearest" });
  }, [active, menuOpen]);

  const close = () => {
    setMenu(false);
    setActive(NO_HIGHLIGHT);
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
    Tab: close,
    Backspace: () => {
      if (query !== "" || on.length === 0) return;
      onOn(on.slice(0, -1));
      setActive(NO_HIGHLIGHT);
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
                setActive(NO_HIGHLIGHT);
                // The button unmounts, and the browser would drop focus to the body.
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
            setActive(NO_HIGHLIGHT);
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
