import type { Issue, IssueTab } from "../../types";

/**
 * The validation banner above the tab strip (phase 5), from the mockup's
 * `issues` markup.
 *
 * Two things it must not do, both learned the hard way:
 *
 * * **Summarise only the blocks.** A one-item summary sitting above three
 *   rows, two of which it never mentioned, reads as a bug in the count. Both
 *   severities are counted and joined.
 * * **Offer an action that does nothing.** An issue already on the open tab
 *   gets the word "Below", not a "Fix →" button that would re-select the tab
 *   it is already on.
 *
 * The list itself is whatever the server returned -- `config/listing_validation.py`
 * owns which rules exist and what they say; nothing here re-derives an issue.
 *
 * **Every row is a warning, never an error (PRD 70).** Nothing in this list
 * stops the listing being saved -- naming it writes it -- so an error's red
 * circle, and a summary saying the problems "block this listing", told a
 * seller their work was being refused when it was on disk. What a `block`
 * issue actually stops is the *deploy*, and it says so in words on its own
 * row rather than through colour alone: the tag is what separates "fix this
 * before deploying" from a `warn` that is only advice (no tags, say), now
 * that both wear the same icon.
 */

interface Props {
  issues: Issue[];
  activeTab: IssueTab;
  onJumpTo: (tab: IssueTab) => void;
}

function summarise(issues: Issue[]): string {
  const blocks = issues.filter((i) => i.severity === "block").length;
  const warns = issues.length - blocks;
  const parts: string[] = [];
  if (blocks > 0) parts.push(`${blocks} to fix before deploying`);
  // "Other" only beside a blocker count, where it says these are the ones
  // that do not stop a deploy; on its own it would be other than nothing.
  const other = blocks > 0 ? "other " : "";
  if (warns > 0) parts.push(warns === 1 ? `1 ${other}warning` : `${warns} ${other}warnings`);
  return parts.join(" · ");
}

function WarnIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 4.2l9.2 16H2.8z" />
      <path d="M12 10.5v3.8M12 17.4v.01" />
    </svg>
  );
}

export function IssuesBanner({ issues, activeTab, onJumpTo }: Props) {
  if (issues.length === 0) return null;

  return (
    <div className="issues">
      <div className="issues__head">
        <span className="issues__summary issues__summary--warn">{summarise(issues)}</span>
        <span className="issues__when">Checked against this listing&rsquo;s own configuration</span>
      </div>
      {issues.map((issue, index) => (
        <div key={`${issue.tab}-${issue.where}-${index}`} className="issue issue--warn">
          <span className="issue__icon" aria-hidden="true">
            <WarnIcon />
          </span>
          <span className="issue__body">
            <span className="issue__text">{issue.message}</span>
            <span className="issue__where">
              {issue.where}
              {issue.severity === "block" && (
                <span className="issue__deploy">Prevents deploying</span>
              )}
            </span>
          </span>
          {issue.tab === activeTab ? (
            <span className="issue__fix issue__fix--here">Below</span>
          ) : (
            <button
              type="button"
              className="issue__fix"
              aria-label={`Fix: ${issue.message}`}
              onClick={() => onJumpTo(issue.tab)}
            >
              Fix &rarr;
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
