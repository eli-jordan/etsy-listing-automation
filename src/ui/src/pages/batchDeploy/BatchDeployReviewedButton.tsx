import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createRun, currentBatchRun, getRun, isReviewedScope } from "../../api/runs";
import type { RunSummary } from "../../types";
import { reviewRunAction } from "./reviewRunAction";

function runUrl(id: string): string {
  return `/listings/deploy/${encodeURIComponent(id)}`;
}

/** ADR-0059. */
export function BatchDeployReviewedButton({
  batchId,
  deployable,
  onError,
}: {
  batchId: string;
  deployable: number;
  onError: (message: string) => void;
}) {
  const navigate = useNavigate();
  const [current, setCurrent] = useState<RunSummary | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    let live = true;
    currentBatchRun(batchId)
      .then((run) => {
        if (live) setCurrent(run);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [batchId]);

  async function start() {
    setStarting(true);
    onError("");
    try {
      const result = await createRun({
        kind: "plan",
        scope: "batch",
        batch_id: batchId,
        publish: false,
      });
      if (result.kind === "created") {
        navigate(runUrl(result.run.id));
        return;
      }
      const active = await getRun(result.activeRun);
      if (isReviewedScope(active)) navigate(runUrl(active.id));
      else onError("A listing in this batch is already deploying. Open it to follow that run.");
    } catch {
      onError("Could not start a deploy of this batch's reviewed listings.");
    } finally {
      setStarting(false);
    }
  }

  const action = reviewRunAction(current);
  return (
    <>
      {action !== null && current !== null && (
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => navigate(runUrl(current.id))}
        >
          {action.prefix} · {action.label} →
        </button>
      )}
      <button
        type="button"
        className="btn btn-primary"
        disabled={deployable === 0 || starting}
        title={deployable === 0 ? "No reviewed listings have changes to deploy" : undefined}
        onClick={() => void start()}
      >
        Deploy reviewed ({deployable})
      </button>
    </>
  );
}
