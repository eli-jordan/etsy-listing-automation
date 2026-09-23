import type { SeoRationaleEntry, SeoWarningEntry } from "../../../types";
import { AiModeMark, AiSeoDisclosure } from "./AiChoiceDrawer";
import { canToggleTag, MAX_TAGS } from "./aiSeoTags";

/** The tag drawer (`docs/ui-listing-seo-interactions.md` section 4): 20
 * ranked candidates split into **Best 13** and **More options**, each a
 * toggle synchronized with the listing's real tag collection, plus
 * **Accept best 13** and **Close**. */
export function AiTagsDrawer({
  tags,
  selected,
  stale,
  rationale,
  warnings,
  observedText,
  onToggle,
  onAcceptBest,
  onClose,
  enter = false,
}: {
  tags: string[];
  selected: string[];
  stale: boolean;
  rationale: SeoRationaleEntry[];
  warnings: SeoWarningEntry[];
  observedText: string;
  onToggle: (tag: string) => void;
  onAcceptBest: () => void;
  onClose: () => void;
  /** Play the draw-out only when generation finishes while this page is open. */
  enter?: boolean;
}) {
  const relevantRationale = rationale.filter((entry) => entry.used_in.includes("tags"));
  const best13 = tags.slice(0, 13);
  const more = tags.slice(13);

  return (
    <div
      className={enter ? "seo-suggestion-slot seo-suggestion-slot--draw" : "seo-suggestion-slot"}
    >
      <aside
        className={stale ? "seo-suggestion seo-suggestion--stale" : "seo-suggestion"}
        role="region"
        aria-label="tag AI suggestions"
      >
        <div className="seo-suggestion__topline">
          <div className="seo-suggestion__identity">
            <AiModeMark />
            <span>{stale ? "Suggestions are out of date" : "20 ranked suggestions"}</span>
          </div>
          <div className="seo-suggestion__actions">
            <button className="seo-suggestion__quiet-action" onClick={onClose} type="button">
              Close
            </button>
            <button disabled={stale} onClick={onAcceptBest} type="button">
              Accept best 13
            </button>
          </div>
        </div>

        <TagPool
          label="Best 13"
          tags={best13}
          selected={selected}
          stale={stale}
          onToggle={onToggle}
        />
        <TagPool
          label="More options"
          tags={more}
          selected={selected}
          stale={stale}
          onToggle={onToggle}
        />

        <p className="seo-suggestion__count">
          {selected.length} of {MAX_TAGS} tags selected
        </p>

        <AiSeoDisclosure
          rationale={relevantRationale}
          warnings={warnings}
          observedText={observedText}
        />
      </aside>
    </div>
  );
}

function TagPool({
  label,
  tags,
  selected,
  stale,
  onToggle,
}: {
  label: string;
  tags: string[];
  selected: string[];
  stale: boolean;
  onToggle: (tag: string) => void;
}) {
  return (
    <div className="seo-tag-group">
      <small>{label}</small>
      <div className="seo-tag-pool">
        {tags.map((tag) => {
          const active = selected.includes(tag);
          const disabled = stale || !canToggleTag(selected, tag);
          return (
            <button
              aria-disabled={disabled}
              aria-pressed={active}
              className={active ? "seo-tag-choice seo-tag-choice--selected" : "seo-tag-choice"}
              disabled={disabled}
              key={tag}
              onClick={() => onToggle(tag)}
              type="button"
            >
              {`${active ? "✓" : "+"} ${tag}`}
            </button>
          );
        })}
      </div>
    </div>
  );
}
