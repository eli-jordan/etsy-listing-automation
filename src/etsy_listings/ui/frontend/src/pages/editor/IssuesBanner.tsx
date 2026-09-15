import type { Issue, IssueTab } from "../../types";

/**
 * The validation banner above the tab strip (phase 5), from the mockup's
 * `issues` markup.
 *
 * Two things it must not do, both learned the hard way:
 *
 * * **Summarise only the blocks.** "1 problem blocks this listing" sitting
 *   above three rows, two of which the summary never mentioned, reads as a
 *   bug in the count. Both severities are counted and joined.
 * * **Offer an action that does nothing.** An issue already on the open tab
 *   gets the word "Below", not a "Fix →" button that would re-select the tab
 *   it is already on.
 *
 * The list itself is whatever the server returned -- `config/listing_validation.py`
 * owns which rules exist and what they say; nothing here re-derives an issue.
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
  if (blocks > 0) {
    parts.push(
      blocks === 1 ? "1 problem blocks this listing" : `${blocks} problems block this listing`,
    );
  }
  if (warns > 0) parts.push(warns === 1 ? "1 warning" : `${warns} warnings`);
  return parts.join(" · ");
}

function BlockIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.4v.01" />
    </svg>
  );
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
  const blocking = issues.some((i) => i.severity === "block");

  return (
    <div className="issues">
      <div className="issues__head">
        <span
          className={
            blocking
              ? "issues__summary issues__summary--block"
              : "issues__summary issues__summary--warn"
          }
        >
          {summarise(issues)}
        </span>
        <span className="issues__when">Checked against this listing&rsquo;s own configuration</span>
      </div>
      {issues.map((issue, index) => (
        <div
          key={`${issue.tab}-${issue.where}-${index}`}
          className={issue.severity === "block" ? "issue issue--block" : "issue issue--warn"}
        >
          <span className="issue__icon" aria-hidden="true">
            {issue.severity === "block" ? <BlockIcon /> : <WarnIcon />}
          </span>
          <span className="issue__body">
            <span className="issue__text">{issue.message}</span>
            <span className="issue__where">{issue.where}</span>
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
