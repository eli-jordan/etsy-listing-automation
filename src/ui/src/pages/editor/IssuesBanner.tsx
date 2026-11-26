import type { Issue, IssueTab } from "../../types";
import { removablePosition } from "./positions/document";
import { useState } from "react";
import { useIsPhone } from "../../phone/usePhone";

/**
 * Every row wears the warning icon, since nothing here stops the save; a
 * `block` row says in words that it prevents deploying. Info notes stay beside
 * what they are about rather than over every tab.
 */

interface Props {
  issues: Issue[];
  activeTab?: IssueTab;
  onJumpTo: (tab: IssueTab) => void;
  subject?: "listing" | "listing-template";
  when?: string;
  onRemovePosition?: (template: string, placement: string | null) => void;
}

function summarise(issues: Issue[], subject: Props["subject"]): string {
  const blocks = issues.filter((i) => i.severity === "block").length;
  const warns = issues.filter((i) => i.severity === "warn").length;
  const parts: string[] = [];
  const stops = subject === "listing-template" ? "this template saves" : "deploying";
  if (blocks > 0) parts.push(`${blocks} to fix before ${stops}`);
  const other = blocks > 0 ? "other " : "";
  if (warns > 0) parts.push(warns === 1 ? `1 ${other}warning` : `${warns} ${other}warnings`);
  return parts.join(" · ");
}

/** The colours live on the shapes so the icon never inherits the text colour. */
function WarnIcon() {
  return (
    <svg viewBox="0 0 24 24">
      <path
        d="M10.3 3.9a2 2 0 0 1 3.4 0l8.1 14.1A2 2 0 0 1 20.1 21H3.9a2 2 0 0 1-1.7-3z"
        fill="var(--color-warning)"
      />
      <path
        d="M12 9v4.6M12 17.2v.01"
        fill="none"
        stroke="var(--color-warning-ink)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function IssuesBanner({
  issues,
  activeTab,
  onJumpTo,
  subject = "listing",
  when = "Checked against this listing’s own configuration",
  onRemovePosition,
}: Props) {
  const phone = useIsPhone();
  const [unfolded, setUnfolded] = useState(false);
  const visible = issues.filter((issue) => issue.severity !== "info");
  if (visible.length === 0) return null;
  const folded = phone && !unfolded;
  const jumpTo = phone
    ? (tab: IssueTab) => {
        setUnfolded(false);
        onJumpTo(tab);
      }
    : onJumpTo;

  return (
    <div className="issues">
      <div className="issues__head">
        <span className="issues__summary issues__summary--warn">{summarise(visible, subject)}</span>
        <span className="issues__when">{when}</span>
        {phone && (
          <button
            type="button"
            className="issues__toggle"
            aria-expanded={!folded}
            onClick={() => setUnfolded(folded)}
          >
            {folded ? "Show" : "Hide"}
          </button>
        )}
      </div>
      {(folded ? [] : visible).map((issue, index) => (
        <div key={`${issue.tab}-${issue.where}-${index}`} className="issue issue--warn">
          <span className="issue__icon" aria-hidden="true">
            <WarnIcon />
          </span>
          <span className="issue__body">
            <span className="issue__text">{issue.message}</span>
            <span className="issue__where">
              {issue.where}
              {issue.severity === "block" && subject === "listing" && (
                <span className="issue__deploy">Prevents deploying</span>
              )}
            </span>
          </span>
          <RowAction
            issue={issue}
            activeTab={activeTab}
            onJumpTo={jumpTo}
            onRemovePosition={onRemovePosition}
          />
        </div>
      ))}
    </div>
  );
}

function RowAction({
  issue,
  activeTab,
  onJumpTo,
  onRemovePosition,
}: {
  issue: Issue;
  activeTab: IssueTab | undefined;
  onJumpTo: Props["onJumpTo"];
  onRemovePosition: Props["onRemovePosition"];
}) {
  const target = removablePosition(issue);
  if (onRemovePosition !== undefined && target !== null) {
    return (
      <button
        type="button"
        className="issue__fix"
        aria-label={`Remove ${issue.where}`}
        onClick={() => onRemovePosition(target.template, target.placement)}
      >
        Remove
      </button>
    );
  }
  if (issue.tab === activeTab) return <span className="issue__fix issue__fix--here">Below</span>;
  return (
    <button
      type="button"
      className="issue__fix"
      aria-label={`Fix: ${issue.message}`}
      onClick={() => onJumpTo(issue.tab)}
    >
      Fix &rarr;
    </button>
  );
}
