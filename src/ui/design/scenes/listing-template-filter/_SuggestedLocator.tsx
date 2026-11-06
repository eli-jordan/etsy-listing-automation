// The Listing Images locator with the shared search box. It opens empty, and
// the filter lasts until the seller leaves the listing. Nothing here is saved.
import { useState } from "react";
import { LabelSearch } from "../../components/_LabelSearch";
import { hasTags, type PickerTemplate, templates } from "./_fixtures";
import { ImagesScreen, LocatorShell, TemplateRow, usePicker } from "./_ImagesScreen";

const tagLists = templates.map((t) => t.tags);

export function SuggestedScreen({
  focus,
  initialOpen = null,
  initialOn = [],
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
  const [open, setOpen] = useState(initialOpen);

  const term = query.trim().toLowerCase();
  const shown = templates.filter((t) => hasTags(t, on) && t.name.includes(term));

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
            {shown.length} of {templates.length} templates
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
            {shown.length === 0 && <p className="locator__empty">No template matches.</p>}
          </div>
        </LocatorShell>
      }
    />
  );
}
