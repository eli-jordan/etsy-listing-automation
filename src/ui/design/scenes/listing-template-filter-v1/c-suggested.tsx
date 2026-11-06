import { PlusIcon } from "@phosphor-icons/react/dist/csr/Plus";
import { XIcon } from "@phosphor-icons/react/dist/csr/X";
import { useState } from "react";
import { hasTags, LISTING_TITLE, tagCounts, templates } from "./_fixtures";
import { ImagesScreen, LocatorShell, TemplateRow, usePicker } from "./_ImagesScreen";

export const meta = {
  title: "C · Suggested for this listing · v1",
  viewport: "laptop",
  description:
    "The locator starts filtered by tags found in the listing's own title, with the rest folded below. Chosen, before the search box came back.",
};

/** Any template tag that appears word for word in the listing's title. */
const allTags = [...new Set(templates.flatMap((t) => t.tags))];
const fromListing = allTags.filter((tag) => LISTING_TITLE.toLowerCase().includes(tag));

export default function Frame() {
  const picker = usePicker("cc1717-woman-with-peace-sign-and-mug");
  const [on, setOn] = useState(fromListing);
  const [adding, setAdding] = useState(false);
  const [showOthers, setShowOthers] = useState(false);
  const [open, setOpen] = useState<string | null>("cc1717-woman-with-peace-sign-and-mug");

  const suited = templates.filter((t) => hasTags(t, on));
  const others = templates.filter((t) => !hasTags(t, on));
  const offered = tagCounts(suited, on);
  const row = (name: string) => ({
    open: open === name,
    onToggleOpen: () => setOpen((c) => (c === name ? null : name)),
  });

  return (
    <ImagesScreen
      picker={picker}
      locator={
        <LocatorShell>
          <div className="lf-suggest">
            <span className="lf-suggest__title">Suits this listing</span>
            <span className="lf-suggest__why">
              {on.length > 0 ? "Based on the listing title. Change it any time." : "Showing every template."}
            </span>
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
            {suited.map((t) => (
              <TemplateRow key={t.name} template={t} picker={picker} {...row(t.name)} />
            ))}
            {others.length > 0 && (
              <button
                type="button"
                className="lf-others"
                aria-expanded={showOthers}
                onClick={() => setShowOthers((v) => !v)}
              >
                {showOthers ? "Hide" : "Show"} {others.length} other templates
              </button>
            )}
            {showOthers &&
              others.map((t) => <TemplateRow key={t.name} template={t} picker={picker} {...row(t.name)} />)}
          </div>
        </LocatorShell>
      }
    />
  );
}
