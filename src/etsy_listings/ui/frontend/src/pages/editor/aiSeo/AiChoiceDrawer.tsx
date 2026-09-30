import type { SeoRationaleEntry, SeoWarningEntry } from "../../../types";

/** The shared shape of the title and description-lead drawers
 * (`docs/features/ai-seo-20260922/interactions.md` sections 3 and 5): exactly three
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
  staleReason,
  rationale,
  warnings,
  observedText,
  onChoose,
  onReject,
  enter = false,
}: {
  field: Field;
  options: string[];
  /** Why the proposal no longer describes the saved listing, from the
   * server (A41), or `null` while it still does. */
  staleReason: string | null;
  rationale: SeoRationaleEntry[];
  warnings: SeoWarningEntry[];
  observedText: string;
  onChoose: (value: string) => void;
  onReject: () => void;
  /** Play the draw-out only when generation finishes while this page is open. */
  enter?: boolean;
}) {
  const relevantRationale = rationale.filter((entry) => entry.used_in.includes(usedInKey(field)));

  return (
    <div
      className={enter ? "seo-suggestion-slot seo-suggestion-slot--draw" : "seo-suggestion-slot"}
    >
      <aside
        className={staleReason ? "seo-suggestion seo-suggestion--stale" : "seo-suggestion"}
        role="region"
        aria-label={`${field} AI suggestions`}
      >
        <div className="seo-suggestion__topline">
          <div className="seo-suggestion__identity">
            <AiModeMark />
            <SuggestionHeading staleReason={staleReason}>Choose one suggestion</SuggestionHeading>
          </div>
          <button className="seo-suggestion__quiet-action" onClick={onReject} type="button">
            Reject all
          </button>
        </div>

        <div className="seo-choice-list">
          {options.map((option, index) => (
            <button key={option} onClick={() => onChoose(option)} type="button">
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
    </div>
  );
}

/** A drawer's heading: its own, or -- for an out-of-date proposal -- what
 * changed (UI doc §8; `features/ai-seo-20260922/interactions.md` §7). The choices
 * below stay clickable with no confirmation: the heading is the warning
 * (PRD 74). */
export function SuggestionHeading({
  staleReason,
  children,
}: {
  staleReason: string | null;
  children: string;
}) {
  return <span>{staleReason ? `Out of date: ${staleReason}. Still usable` : children}</span>;
}

export function AiModeMark() {
  return (
    <span className="seo-suggestion__brand">
      <svg aria-hidden="true" viewBox="0 0 20 20" width="13" height="13">
        <path
          className="seo-sparkle-primary"
          d="M8.2 2.2c.5 3.1 1.5 4.1 4.6 4.6-3.1.5-4.1 1.5-4.6 4.6-.5-3.1-1.5-4.1-4.6-4.6 3.1-.5 4.1-1.5 4.6-4.6Z"
        />
        <path
          className="seo-sparkle-secondary"
          d="M14.5 11.2c.3 2 1 2.7 3 3-2 .3-2.7 1-3 3-.3-2-1-2.7-3-3 2-.3 2.7-1 3-3Z"
        />
      </svg>
      AI Mode
    </span>
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
