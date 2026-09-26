import type { Comparison } from "./comparison";
import { stageBlocked, stageWillRun, type DriftDTO, type PlanDTO } from "../../types";

/**
 * The headline, impact tags, and the blocked/drift/ok callouts above the
 * comparison (spec's "Summary and warnings" elements).
 *
 * **A stage that is blocked never disables the stages that are not.** The
 * mock's own demo script always hid the whole comparison behind a single
 * blocked/not-blocked switch, but the doc is explicit that a plan can be
 * part blocked and part runnable, and *that* is what decides Apply, not
 * "is anything blocked at all" (docs/deploy-changes.md, the note under the
 * control-states table). So the negative headline -- "This deploy can't go
 * ahead yet", no impact tags -- is reserved for the case nothing at all can
 * run; a plan that will do *something* gets the positive headline and its
 * tags, with the blocked stage's callout still shown underneath it.
 */

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

type SourcedDrift = DriftDTO & { stage: PlanDTO["stage_plans"][number]["stage"] };

function driftKey(drift: SourcedDrift): string {
  return JSON.stringify([
    drift.path,
    drift.last_applied,
    drift.live,
    drift.last_applied_label,
    drift.live_label,
  ]);
}

/** Printify republishes linked copy onto Etsy, so the same external edit can
 * appear in both stages. Show that event once, preferring the buyer-facing
 * Etsy observation when both sides are byte-for-byte identical. */
function uniqueDrifts(plan: PlanDTO): SourcedDrift[] {
  const found = new Map<string, SourcedDrift>();
  for (const stagePlan of plan.stage_plans) {
    for (const drift of stagePlan.drift) {
      const sourced = { ...drift, stage: stagePlan.stage };
      const key = driftKey(sourced);
      const previous = found.get(key);
      if (previous === undefined || previous.stage === "printify_product") {
        found.set(key, sourced);
      }
    }
  }
  return [...found.values()];
}

export function Callouts({
  plan,
  comparison,
  applied,
}: {
  plan: PlanDTO;
  comparison: Comparison;
  /** True once this run's outcome is "applied" -- the summary becomes a
   * single "Deployed" callout, per the spec's Applied element. */
  applied: boolean;
}) {
  const hasWork = plan.stage_plans.some(stageWillRun);
  const blocked = plan.stage_plans.filter((stage) => stageBlocked(stage) !== null);
  const drifts = uniqueDrifts(plan);

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

      {drifts.map((drift, index) => (
        <div key={`${drift.stage}-${drift.path}-${index}`} className="dv-callout dv-callout--drift">
          <DriftIcon />
          <div>
            <strong>
              Changed {drift.stage === "printify_product" ? "in Printify" : "on Etsy"} since your
              last apply:
            </strong>{" "}
            the {drift.path.replace(/_/g, " ")} is now &ldquo;
            {drift.live_label ?? String(drift.live)}
            &rdquo;, not &ldquo;
            {drift.last_applied_label ?? String(drift.last_applied)}&rdquo;.
            {drift.stage !== "printify_product" &&
              " Printify re-attaches its own settings when it republishes."}{" "}
            Apply will set it back.
          </div>
        </div>
      ))}
    </div>
  );
}
