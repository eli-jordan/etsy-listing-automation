import type { Comparison, DriftedField } from "./comparison";
import { stageBlocked, stageWillRun, type PlanDTO } from "../../types";

function OkIcon() {
  return (
    <svg
      className="dv-callout__icon"
      viewBox="0 0 20 20"
      fill="none"
      stroke="var(--color-accent-2-700)"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m5 10.5 3.2 3L15 6.5" />
    </svg>
  );
}

function BlockedIcon() {
  return (
    <svg
      className="dv-callout__icon"
      viewBox="0 0 20 20"
      fill="none"
      stroke="var(--color-danger)"
      strokeWidth="1.8"
    >
      <circle cx="10" cy="10" r="7.5" />
      <path d="M4.8 15.2 15.2 4.8" />
    </svg>
  );
}

function DriftIcon() {
  return (
    <svg
      className="dv-callout__icon"
      viewBox="0 0 20 20"
      fill="none"
      stroke="var(--color-accent-700)"
      strokeWidth="1.8"
      strokeLinecap="round"
    >
      <path d="M3 7h11l-3-3M17 13H6l3 3" />
    </svg>
  );
}

function DriftWarning({
  drifted,
  onReveal,
}: {
  drifted: DriftedField[];
  onReveal: ((field: DriftedField) => void) | undefined;
}) {
  const where = [
    drifted.some((field) => field.source === "etsy") && "on Etsy",
    drifted.some((field) => field.source === "printify") && "in Printify",
  ]
    .filter(Boolean)
    .join(" and ");
  const count = drifted.length;

  return (
    <div className="dv-callout dv-callout--drift dv-drift-strip" role="status">
      <DriftIcon />
      <div className="dv-drift-strip__text">
        <strong>This listing has drifted from what&rsquo;s {where}.</strong> {count}{" "}
        {count === 1 ? "field" : "fields"} changed there since your last apply. Apply will set{" "}
        {count === 1 ? "it" : "them"} back.
      </div>
      {onReveal && (
        <div className="dv-drift-strip__links">
          {drifted.map((field) => (
            <button
              key={field.key}
              type="button"
              className="dv-drift-link"
              onClick={() => onReveal(field)}
            >
              {field.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Callouts({
  plan,
  comparison,
  applied,
  onRevealDrift,
}: {
  plan: PlanDTO;
  comparison: Comparison;
  applied: boolean;
  onRevealDrift?: (field: DriftedField) => void;
}) {
  const hasWork = plan.stage_plans.some(stageWillRun);
  const blocked = plan.stage_plans.filter((stage) => stageBlocked(stage) !== null);
  const { drifted } = comparison;

  if (applied) {
    return (
      <div className="dv-callout dv-callout--ok">
        <OkIcon />
        <div>
          <strong>Deployed.</strong> Printify and Etsy now match this listing, and the plan has been
          used up. Go back to keep editing.
        </div>
      </div>
    );
  }

  if (!hasWork && blocked.length === 0) {
    return (
      <div className="dv-callout dv-callout--ok">
        <OkIcon />
        <div>
          <strong>Nothing to deploy.</strong> The plan found Printify and Etsy already match this
          listing, and nothing has changed on either since the last apply.
        </div>
      </div>
    );
  }

  return (
    <div className="dv-stack">
      {hasWork ? (
        <div className="dv-banner">
          <h2>Apply will change what buyers see</h2>
          <div className="dv-impacts">
            {comparison.impacts.map((tag) => (
              <span key={tag} className="tag tag-accent">
                {tag}
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div className="dv-banner">
          <h2>This deploy can&rsquo;t go ahead yet</h2>
        </div>
      )}

      {blocked.map((stagePlan) => {
        const lines = (stageBlocked(stagePlan) ?? "").split("\n");
        return (
          <div key={stagePlan.stage} className="dv-callout dv-callout--blocked">
            <BlockedIcon />
            <div>
              <strong>{lines[0]}</strong>
              {lines.length > 1 && (
                <div className="dv-callout__remedy">{lines.slice(1).join(" ")}</div>
              )}
            </div>
          </div>
        );
      })}

      {drifted.length > 0 && <DriftWarning drifted={drifted} onReveal={onRevealDrift} />}
    </div>
  );
}
