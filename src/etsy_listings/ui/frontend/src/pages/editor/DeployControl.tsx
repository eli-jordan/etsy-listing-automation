import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { currentRun } from "../../api/runs";
import type { RunSummary } from "../../types";

/**
 * The editor page-head's own control (docs/deploy-changes.md decision 8):
 * **Deploy changes →** when there is nothing to reattach to, or a link back
 * into whatever run this listing already has.
 *
 * | Run state for this listing | Control |
 * |---|---|
 * | none, or finished and seen | Deploy changes → |
 * | queued / planning / previewing / applying (and a plan resting at "ready", not yet acted on) | Deploying… View progress → |
 * | an `apply` run that landed on `applied`, not seen | Deployed ✓ View result → |
 * | an `apply` run that landed on `failed`/`stale`, not seen | Deploy failed — view |
 *
 * `cancelled` reads as "deploy changes" even before anything marks it
 * `seen`, because Back already means "I am done with that review" the
 * moment it is pressed. A plan resting at `"ready"` -- itself a terminal
 * phase, so `registry.cancel` refuses it just like it refuses an `apply` --
 * never dangles here either: `DeployPage` marks *any* terminal run seen the
 * moment its result renders, not only ones Back's own cancel call reaches,
 * so a reviewed-but-never-applied plan is already seen well before Back is
 * pressed.
 */

type PageHeadState = "deploy" | "progress" | "deployed" | "failed";

function pageHeadState(run: RunSummary | null): PageHeadState {
  if (run === null || run.seen || run.phase === "cancelled") return "deploy";
  if (run.kind === "apply" && run.phase === "applied") return "deployed";
  if (run.kind === "apply" && (run.phase === "failed" || run.phase === "stale")) return "failed";
  return "progress";
}

export function DeployControl({
  name,
  flush,
}: {
  name: string;
  /** Drains any edit still waiting on the autosave debounce -- the same
   * flush a tab switch already triggers, so a plan started the instant
   * after typing reviews the listing just written, not the one before it. */
  flush: () => Promise<void>;
}) {
  const navigate = useNavigate();
  const [run, setRun] = useState<RunSummary | null>(null);

  useEffect(() => {
    let current = true;
    currentRun(name)
      .then((found) => {
        if (current) setRun(found);
      })
      .catch(() => {
        if (current) setRun(null);
      });
    return () => {
      current = false;
    };
  }, [name]);

  const deployUrl = `/listings/${encodeURIComponent(name)}/deploy`;

  async function startDeploy() {
    await flush();
    navigate(deployUrl);
  }

  switch (pageHeadState(run)) {
    case "progress":
      return (
        <button type="button" className="btn btn-secondary" onClick={() => navigate(deployUrl)}>
          Deploying&hellip; View progress &rarr;
        </button>
      );
    case "deployed":
      return (
        <button type="button" className="btn btn-secondary" onClick={() => navigate(deployUrl)}>
          Deployed &#10003; View result &rarr;
        </button>
      );
    case "failed":
      return (
        <button type="button" className="btn btn-danger" onClick={() => navigate(deployUrl)}>
          Deploy failed &mdash; view
        </button>
      );
    case "deploy":
      return (
        <button type="button" className="btn btn-primary" onClick={() => void startDeploy()}>
          Deploy changes &rarr;
        </button>
      );
  }
}
