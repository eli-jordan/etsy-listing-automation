// The Listing Images locator: the shared search box, opening on the labels
// found in the listing's title. Nothing here is saved.
import { useState } from "react";
import { LabelSearch } from "./_snapshot/_LabelSearch";
import { hasTags, LISTING_TITLE, type PickerTemplate, templates } from "./_fixtures";
import { ImagesScreen, LocatorShell, TemplateRow, usePicker } from "./_ImagesScreen";

const allTags = [...new Set(templates.flatMap((t) => t.tags))];
/** Any template tag that appears word for word in the listing's title. */
const fromListing = allTags.filter((tag) => LISTING_TITLE.toLowerCase().includes(tag));
const tagLists = templates.map((t) => t.tags);

export function SuggestedScreen({
  focus,
  initialOpen = null,
  initialOn = fromListing,
  initialQuery = "",
  initialMenu = false,
  initialActive = -1,
}: {
  focus: string;
  initialOpen?: string | null;
  initialOn?: string[];
  initialQuery?: string;
  initialMenu?: boolean;
  initialActive?: number;
}) {
  const picker = usePicker(focus);
  const [on, setOn] = useState(initialOn);
  const [query, setQuery] = useState(initialQuery);
  const [showOthers, setShowOthers] = useState(false);
  const [open, setOpen] = useState(initialOpen);

  const term = query.trim().toLowerCase();
  const inTitle = (t: PickerTemplate) => t.name.includes(term);
  const shown = templates.filter((t) => hasTags(t, on) && inTitle(t));
  const others = templates.filter((t) => !hasTags(t, on) && inTitle(t));
  const fromTitle = on.some((tag) => fromListing.includes(tag));

  const row = (t: PickerTemplate) => (
    <TemplateRow
      key={t.name}
      template={t}
      picker={picker}
      open={open === t.name}
      onToggleOpen={() => setOpen((c) => (c === t.name ? null : t.name))}
    />
  );

  return (
    <ImagesScreen
      picker={picker}
      locator={
        <LocatorShell>
          <LabelSearch
            items={tagLists}
            on={on}
            onOn={setOn}
            query={query}
            onQuery={setQuery}
            initialMenu={initialMenu}
            initialActive={initialActive}
          />

          <div className="lf-result-line" role="status">
            <span>
              {shown.length} of {templates.length} templates
            </span>
            {fromTitle && <span>Label from the listing title</span>}
          </div>

          <div className="locator__list">
            {shown.map(row)}
            {shown.length === 0 && <p className="locator__empty">No template matches.</p>}
            {others.length > 0 && (
              <button
                type="button"
                className="lf-others"
                aria-expanded={showOthers}
                onClick={() => setShowOthers((v) => !v)}
              >
                {showOthers ? "Hide" : "Show"} {others.length} without{" "}
                {on.length === 1 ? "this label" : "these labels"}
              </button>
            )}
            {showOthers && others.map(row)}
          </div>
        </LocatorShell>
      }
    />
  );
}
