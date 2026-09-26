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
 *
 * An `info` row is neither: a note about what Etsy will do (it strips a
 * video's sound, PRD 72), with nothing for the seller to fix. It wears no
 * warning icon and is counted as a note, never as a warning -- a banner that
 * called it one would train a seller to skim past the real ones.
 */

interface Props {
  issues: Issue[];
  activeTab: IssueTab;
  onJumpTo: (tab: IssueTab) => void;
}

function summarise(issues: Issue[]): string {
  const blocks = issues.filter((i) => i.severity === "block").length;
  const warns = issues.filter((i) => i.severity === "warn").length;
  const notes = issues.length - blocks - warns;
  const parts: string[] = [];
  if (blocks > 0) parts.push(`${blocks} to fix before deploying`);
  // "Other" only beside a blocker count, where it says these are the ones
  // that do not stop a deploy; on its own it would be other than nothing.
  const other = blocks > 0 ? "other " : "";
  if (warns > 0) parts.push(warns === 1 ? `1 ${other}warning` : `${warns} ${other}warnings`);
  if (notes > 0) parts.push(notes === 1 ? "1 note" : `${notes} notes`);
  return parts.join(" · ");
}

/** A filled amber triangle with a dark mark, rather than an outline in the
 * text colour. The outline took `--color-accent-2-700`, which in this palette
 * is an olive that reads as grey -- a warning nobody recognises as one. The
 * colours live on the shapes themselves so the icon cannot drift back into
 * the surrounding text colour. */
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

export function IssuesBanner({ issues, activeTab, onJumpTo }: Props) {
  if (issues.length === 0) return null;

  return (
    <div className="issues">
      <div className="issues__head">
        <span className="issues__summary issues__summary--warn">{summarise(issues)}</span>
        <span className="issues__when">Checked against this listing&rsquo;s own configuration</span>
      </div>
      {issues.map((issue, index) => (
        <div
          key={`${issue.tab}-${issue.where}-${index}`}
          className={`issue ${issue.severity === "info" ? "issue--info" : "issue--warn"}`}
        >
          <span className="issue__icon" aria-hidden="true">
            {issue.severity !== "info" && <WarnIcon />}
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
