// The search box both pages share: labels are pills inside it, and plain text
// narrows what they leave by title. The caller owns both values, and applies
// them to its own list.
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { Fragment, type KeyboardEvent, useEffect, useRef, useState } from "react";
import "./LabelSearch.css";

interface Option {
  tag: string;
  count: number;
  /** Adding it would leave nothing, so taking it replaces the pills. */
  swap: boolean;
}

/** A tag's group: the text before its colon, or null for a plain tag. */
const groupOf = (tag: string) => (tag.includes(":") ? tag.slice(0, tag.indexOf(":")) : null);

const holdsAll = (tags: string[], on: string[]) => on.every((tag) => tags.includes(tag));

/** Labels the typed text could mean, in their groups A to Z with plain tags last.
 * Within a group: narrowing ones first, then those starting with it, then by count. */
function optionsFor(items: string[][], term: string, on: string[]): Option[] {
  return [...new Set(items.flat())]
    .filter((tag) => tag.includes(term) && !on.includes(tag))
    .map((tag) => {
      const narrowed = items.filter((tags) => holdsAll(tags, [...on, tag])).length;
      return narrowed > 0
        ? { tag, count: narrowed, swap: false }
        : { tag, count: items.filter((tags) => tags.includes(tag)).length, swap: true };
    })
    .sort(
      (a, b) =>
        Number(groupOf(a.tag) === null) - Number(groupOf(b.tag) === null) ||
        (groupOf(a.tag) ?? "").localeCompare(groupOf(b.tag) ?? "") ||
        Number(a.swap) - Number(b.swap) ||
        Number(b.tag.startsWith(term)) - Number(a.tag.startsWith(term)) ||
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
  const at = term ? tag.indexOf(term) : -1;
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
  initialMenu = false,
  initialActive = -1,
}: {
  /** Every searchable item's tags. */
  items: string[][];
  on: string[];
  onOn: (next: string[]) => void;
  query: string;
  onQuery: (next: string) => void;
  initialMenu?: boolean;
  initialActive?: number;
}) {
  const [menu, setMenu] = useState(initialMenu);
  const [active, setActive] = useState(initialActive);
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);

  // Outside clicks rather than blur: a click on an option must not close it first.
  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const term = query.trim().toLowerCase();
  const options = optionsFor(items, term, on);
  const menuOpen = menu && options.length > 0;
  const grouped = options.some((option) => groupOf(option.tag) !== null);

  const take = (option: Option) => {
    onOn(option.swap ? [option.tag] : [...on, option.tag]);
    onQuery("");
    setActive(-1);
    setMenu(false);
    field.current?.focus();
  };
  const move = (event: KeyboardEvent, step: 1 | -1) => {
    event.preventDefault();
    if (!menuOpen) setMenu(true);
    setActive((current) => stepped(current, options.length, step));
  };
  const confirm = () => {
    const option = menuOpen ? options[active] : undefined;
    if (option) take(option);
    else setMenu(false);
  };
  const keys: Record<string, (event: KeyboardEvent) => void> = {
    ArrowDown: (event) => move(event, 1),
    ArrowUp: (event) => move(event, -1),
    Enter: confirm,
    Escape: () => {
      setMenu(false);
      setActive(-1);
    },
    Backspace: () => {
      if (query === "" && on.length > 0) onOn(on.slice(0, -1));
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
        <svg viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5" />
        </svg>
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
          aria-controls="label-search-menu"
          aria-activedescendant={menuOpen && active >= 0 ? `label-search-${active}` : undefined}
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
        <div
          className="label-search__menu"
          id="label-search-menu"
          role="listbox"
          aria-label="Labels"
        >
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
                  id={`label-search-${index}`}
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
