// The chosen direction: the locator opens on templates that suit the listing,
// and search covers every template and offers the labels it matches.
import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useState } from "react";
import { hasTags, LISTING_TITLE, type PickerTemplate, tagCounts, templates } from "./_fixtures";
import { ImagesScreen, LocatorShell, TemplateRow, usePicker } from "./_ImagesScreen";

const allTags = [...new Set(templates.flatMap((t) => t.tags))].sort();
/** Any template tag that appears word for word in the listing's title. */
const fromListing = allTags.filter((tag) => LISTING_TITLE.toLowerCase().includes(tag));
/** One letter matches too much to be worth suggesting. */
const MIN_HINT_LENGTH = 2;

interface Hint {
  tag: string;
  count: number;
  /** Adding it would leave nothing, so taking it replaces the filter. */
  swap: boolean;
}

function hintsFor(term: string, on: string[]): Hint[] {
  if (term.length < MIN_HINT_LENGTH) return [];
  return allTags
    .filter((tag) => tag.includes(term) && !on.includes(tag))
    .map((tag) => {
      const narrowed = templates.filter((t) => hasTags(t, [...on, tag])).length;
      return narrowed > 0
        ? { tag, count: narrowed, swap: false }
        : { tag, count: templates.filter((t) => hasTags(t, [tag])).length, swap: true };
    });
}

const matchesTerm = (template: PickerTemplate, term: string) =>
  template.name.includes(term) || template.tags.some((tag) => tag.includes(term));

export function SuggestedScreen({
  focus,
  initialOpen = null,
  initialQuery = "",
}: {
  focus: string;
  initialOpen?: string | null;
  initialQuery?: string;
}) {
  const picker = usePicker(focus);
  const [on, setOn] = useState(fromListing);
  const [query, setQuery] = useState(initialQuery);
  const [adding, setAdding] = useState(false);
  const [showOthers, setShowOthers] = useState(false);
  const [open, setOpen] = useState(initialOpen);

  const term = query.trim().toLowerCase();
  const suited = templates.filter((t) => hasTags(t, on) && matchesTerm(t, term));
  const others = templates.filter((t) => !hasTags(t, on) && matchesTerm(t, term));
  const hints = hintsFor(term, on);
  const offered = tagCounts(
    templates.filter((t) => hasTags(t, on)),
    on,
  );
  const searching = term.length > 0;
  const row = (t: PickerTemplate) => (
    <TemplateRow
      key={t.name}
      template={t}
      picker={picker}
      open={open === t.name}
      onToggleOpen={() => setOpen((c) => (c === t.name ? null : t.name))}
    />
  );
  const take = (hint: Hint) => {
    setOn((current) => (hint.swap ? [hint.tag] : [...current, hint.tag]));
    setQuery("");
  };

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
              placeholder="Search templates and labels…"
              aria-label="Search templates and labels"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && hints[0]) take(hints[0]);
                if (event.key === "Escape") setQuery("");
              }}
            />
          </div>

          {hints.length > 0 && (
            <div className="lf-hints" role="status">
              <span className="lf-hints__lead">Filter by label</span>
              {hints.map((hint) => (
                <button
                  key={hint.tag}
                  type="button"
                  className="tag template-rail__pill"
                  onClick={() => take(hint)}
                >
                  {hint.tag}
                  {hint.swap ? " instead" : ""} {hint.count}
                </button>
              ))}
            </div>
          )}

          <div className="lf-suggest">
            <span className="lf-suggest__title">
              {on.length > 0 ? "Suits this listing" : "All templates"}
            </span>
            {on.length > 0 && (
              <span className="lf-suggest__why">Based on the listing title. Change it any time.</span>
            )}
            <div className="lf-pills lf-suggest__pills">
              {on.map((tag) => (
                <span key={tag} className="tag tag-neutral lf-chip">
                  {tag}
                  <button
                    type="button"
                    className="lf-chip__x"
                    aria-label={`Remove ${tag}`}
                    onClick={() => setOn((c) => c.filter((t) => t !== tag))}
                  >
                    <XIcon weight="bold" />
                  </button>
                </span>
              ))}
              <span className="lf-anchor">
                <button
                  type="button"
                  className="lf-add"
                  aria-expanded={adding}
                  onClick={() => setAdding((v) => !v)}
                >
                  <PlusIcon className="lf-icon" /> Add label
                </button>
                {adding && (
                  <div className="lf-pop" role="listbox" aria-label="Labels">
                    {offered.map(([tag, count]) => (
                      <button
                        key={tag}
                        type="button"
                        role="option"
                        aria-selected="false"
                        className="lf-option"
                        onClick={() => {
                          setOn((c) => [...c, tag]);
                          setAdding(false);
                        }}
                      >
                        {tag} <span className="lf-muted">{count}</span>
                      </button>
                    ))}
                  </div>
                )}
              </span>
            </div>
          </div>

          <div className="locator__list">
            {suited.map(row)}
            {searching && suited.length === 0 && others.length > 0 && (
              <p className="lf-group-empty">Nothing here matches “{query.trim()}”.</p>
            )}
            {searching && others.length > 0 && (
              <>
                <span className="loc-group__label">Other templates · {others.length}</span>
                {others.map(row)}
              </>
            )}
            {searching && suited.length === 0 && others.length === 0 && (
              <p className="locator__empty">No template or label matches “{query.trim()}”.</p>
            )}
            {!searching && others.length > 0 && (
              <button
                type="button"
                className="lf-others"
                aria-expanded={showOthers}
                onClick={() => setShowOthers((v) => !v)}
              >
                {showOthers ? "Hide" : "Show"} {others.length} other templates
              </button>
            )}
            {!searching && showOthers && others.map(row)}
          </div>
        </LocatorShell>
      }
    />
  );
}
