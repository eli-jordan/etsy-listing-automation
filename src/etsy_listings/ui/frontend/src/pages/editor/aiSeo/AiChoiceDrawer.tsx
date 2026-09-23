import type { SeoRationaleEntry, SeoWarningEntry } from "../../../types";

/** The shared shape of the title and description-lead drawers
 * (`docs/ui-listing-seo-interactions.md` sections 3 and 5): exactly three
 * options, one click both decides and applies, **Reject all** closes it
 * unchanged, and there is no default selection or separate Accept step. */

type Field = "title" | "description lead";

/** `SeoRationaleEntry.used_in` uses the wire's field keys; this drawer is
 * labelled with the prose field name a seller reads. */
function usedInKey(field: Field): "title" | "description_lead" {
  return field === "title" ? "title" : "description_lead";
}

export function AiChoiceDrawer({
  field,
  options,
  stale,
  rationale,
  warnings,
  observedText,
  onChoose,
  onReject,
}: {
  field: Field;
  options: string[];
  stale: boolean;
  rationale: SeoRationaleEntry[];
  warnings: SeoWarningEntry[];
  observedText: string;
  onChoose: (value: string) => void;
  onReject: () => void;
}) {
  const relevantRationale = rationale.filter((entry) => entry.used_in.includes(usedInKey(field)));

  return (
    <aside
      className={stale ? "seo-suggestion seo-suggestion--stale" : "seo-suggestion"}
      role="region"
      aria-label={`${field} AI suggestions`}
    >
      <div className="seo-suggestion__topline">
        <span>{stale ? "Suggestions are out of date" : "Choose one suggestion"}</span>
        <button className="seo-suggestion__quiet-action" onClick={onReject} type="button">
          Reject all
        </button>
      </div>

      <div className="seo-choice-list">
        {options.map((option, index) => (
          <button disabled={stale} key={option} onClick={() => onChoose(option)} type="button">
            <span>{index + 1}</span>
            {option}
          </button>
        ))}
      </div>

      <AiSeoDisclosure
        rationale={relevantRationale}
        warnings={warnings}
        observedText={observedText}
      />
    </aside>
  );
}

/** Warnings, rationale, and observed OCR text as one collapsed disclosure
 * per drawer (implementation plan, PR7 item 2; the settled "Validation"
 * decision that trademark findings are warnings, never a hard refusal).
 * Rendered by every AI Mode drawer, so it lives here rather than being
 * duplicated in `AiTagsDrawer`. */
export function AiSeoDisclosure({
  rationale,
  warnings,
  observedText,
}: {
  rationale: SeoRationaleEntry[];
  warnings: SeoWarningEntry[];
  observedText: string;
}) {
  if (rationale.length === 0 && warnings.length === 0 && observedText === "") return null;

  return (
    <details className="seo-suggestion__why">
      <summary>Why these suggestions?</summary>
      {rationale.length > 0 && (
        <div>
          <p className="section-label">Rationale</p>
          <ul>
            {rationale.map((entry) => (
              <li key={entry.phrase}>
                <strong>{entry.phrase}</strong> — {entry.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {warnings.length > 0 && (
        <div>
          <p className="section-label">Warnings</p>
          <ul>
            {warnings.map((warning, index) => (
              <li key={index}>{warning.message}</li>
            ))}
          </ul>
        </div>
      )}
      {observedText !== "" && (
        <div>
          <p className="section-label">Observed image text</p>
          <p>{observedText}</p>
        </div>
      )}
    </details>
  );
}
