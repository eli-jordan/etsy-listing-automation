import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { currentRun } from "../../api/runs";
import type { RunSummary } from "../../types";
import type { Settled } from "../../hooks/writeLoop";
import { useIsPhone } from "../../phone/usePhone";

type PageHeadState = "deploy" | "progress" | "deployed" | "failed";

function pageHeadState(run: RunSummary | null): PageHeadState {
  if (run === null || run.seen || run.phase === "cancelled") return "deploy";
  if (run.kind === "apply" && run.phase === "applied") return "deployed";
  if (run.kind === "apply" && (run.phase === "failed" || run.phase === "stale")) return "failed";
  return "progress";
}

export function DeployControl({ name, flush }: { name: string; flush: () => Promise<Settled> }) {
  const navigate = useNavigate();
  const [run, setRun] = useState<RunSummary | null>(null);
  const phone = useIsPhone();

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
    const settled = await flush();
    // A plan of the old file would review something the seller has moved on
    // from. The page head already says why it stayed.
    if (settled.written) navigate(deployUrl);
  }

  switch (pageHeadState(run)) {
    case "progress":
      return (
        <button type="button" className="btn btn-secondary" onClick={() => navigate(deployUrl)}>
          {phone ? <>Deploying&hellip; &rarr;</> : <>Deploying&hellip; View progress &rarr;</>}
        </button>
      );
    case "deployed":
      return (
        <button type="button" className="btn btn-secondary" onClick={() => navigate(deployUrl)}>
          {phone ? <>Deployed &#10003; &rarr;</> : <>Deployed &#10003; View result &rarr;</>}
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
        <button
          type="button"
          className="btn btn-primary"
          aria-label={phone ? "Deploy changes →" : undefined}
          onClick={() => void startDeploy()}
        >
          {phone ? <>Deploy &rarr;</> : <>Deploy changes &rarr;</>}
        </button>
      );
  }
}
