import { PreparationProgress } from "./PreparationProgress";
import { preparationLabel } from "./preparationLabel";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { getRuntime, type Preparation, type Runtime } from "../api/preparation";
import type { Renderer } from "../types";
export function RendererPanel({
  settings,
  reference,
  renderer,
  onRendererChange,
  preparation,
  onPrepare,
  onCancel,
  pending,
  error,
}: {
  reference?: string;
  settings: (runtime: Runtime | null) => ReactNode;
  renderer: Renderer;
  onRendererChange: (renderer: Renderer["type"]) => void;
  preparation: Preparation | null;
  onPrepare: (action: "prepare" | "prepare_again" | "retry", resetMasksForPhoto?: boolean) => void;
  onCancel: () => void;
  pending: boolean;
  error: string;
}) {
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [runtimeError, setRuntimeError] = useState("");
  useEffect(() => {
    if (renderer.type !== "marigold") return;
    let active = true;
    getRuntime()
      .then((value) => {
        if (active) setRuntime(value);
      })
      .catch((e) => {
        if (active) setRuntimeError(e instanceof Error ? e.message : "Could not check runtime");
      });
    return () => {
      active = false;
    };
  }, [renderer.type]);
  const job = preparation?.active_job;
  const label = preparationLabel(preparation);
  const recovery = preparation?.maps.reason === "photo_changed";
  const action =
    preparation?.latest_job?.phase === "failed"
      ? "retry"
      : recovery
        ? "prepare_again"
        : preparation?.maps.can_render
          ? "prepare_again"
          : "prepare";
  return (
    <section className="realism mg-preparation">
      <h3 className="realism__heading">Renderer</h3>
      <select
        id="template-renderer"
        aria-label="Renderer"
        value={renderer.type}
        onChange={(e) => onRendererChange(e.target.value as Renderer["type"])}
      >
        <option value="photo-warp">Photo warp</option>
        <option value="marigold">Marigold</option>
      </select>
      {renderer.type === "marigold" && (
        <>
          <div className="mg-row">
            <strong>Template maps</strong>
            <span
              className={`tag mg-status${label === "Ready" ? " mg-status--ready" : label === "Failed" ? " mg-status--failed" : ""}`}
            >
              {label}
            </span>
          </div>
          {reference && <p className="mg-help">{reference}</p>}
          {!job && preparation?.maps.state === "out_of_date" && preparation.maps.reason && (
            <p className="mg-help">{preparation.maps.message}</p>
          )}
          {job ? (
            <div className="mg-progress">
              <PreparationProgress job={job} />
              <button
                className="btn btn-secondary mg-wide"
                disabled={pending || job.phase === "cancelling"}
                onClick={onCancel}
              >
                {job.phase === "cancelling" ? "Cancelling…" : "Cancel preparation"}
              </button>
            </div>
          ) : (
            <button
              type="button"
              className={
                "btn mg-wide " +
                (action === "prepare_again" && !recovery ? "btn-secondary" : "btn-primary")
              }
              disabled={pending || !preparation || !runtime?.available}
              onClick={() => onPrepare(action, recovery && action !== "retry")}
            >
              {action === "retry"
                ? "Retry preparation"
                : recovery
                  ? "Reset masks and prepare"
                  : action === "prepare_again"
                    ? "Prepare again"
                    : "Prepare template"}
            </button>
          )}
          {(preparation?.latest_job?.error || error) && (
            <p role="alert" className="mg-error">
              {error || preparation?.latest_job?.error}
            </p>
          )}
          {(!runtime?.available || runtimeError) && (
            <p className="mg-help" role="status">
              {runtimeError || runtime?.problem || "Checking Marigold runtime…"}
            </p>
          )}
          {preparation?.maps.can_render &&
            preparation.prepared_engine &&
            runtime?.engine_version &&
            preparation.prepared_engine !== runtime.engine_version && (
              <p className="mg-help">
                These maps were prepared with {preparation.prepared_engine}. They remain usable.
                Prepare again to use {runtime.engine_version}.
              </p>
            )}
          <p className="mg-help">
            {job
              ? "You can close this browser. Preparation will continue."
              : action === "retry"
                ? "Completed steps will be reused."
                : "Prepare once, then reuse for every design and colour."}
          </p>
          {settings(runtime)}
        </>
      )}
    </section>
  );
}
