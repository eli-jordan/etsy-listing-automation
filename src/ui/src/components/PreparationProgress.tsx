import { useEffect, useState } from "react";
import { CheckCircleIcon } from "@phosphor-icons/react/dist/csr/CheckCircle";
import { ClockIcon } from "@phosphor-icons/react/dist/csr/Clock";
import type { PreparationJob } from "../api/preparation";
const stepLabels: Record<string, string> = {
  loading_models: "Loading models",
  normals: "Estimating surface direction",
  lighting: "Estimating garment lighting",
  depth: "Estimating depth",
  cpu_queued: "Waiting to build maps",
  building_maps: "Building maps",
  publication: "Publishing maps",
};
export function PreparationProgress({ job }: { job: PreparationJob }) {
  const [ticks, setTicks] = useState(0);
  const [base, setBase] = useState({ elapsed: job.elapsed, ticks });
  if (base.elapsed !== job.elapsed) setBase({ elapsed: job.elapsed, ticks });
  useEffect(() => {
    if (job.phase !== "running" && job.phase !== "cancelling") return;
    const timer = setInterval(() => setTicks((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [job.phase]);
  const step = job.step.toLowerCase();
  const active = step.includes("normal")
    ? 0
    : step.includes("lighting")
      ? 1
      : step.includes("depth")
        ? 2
        : step.includes("build") || step.includes("bake")
          ? 3
          : -1;
  return (
    <>
      <p className="mg-row">
        <strong>
          {job.phase === "queued"
            ? `Waiting in queue${job.queue_position ? ` · ${job.queue_position}` : ""}`
            : (stepLabels[job.step] ?? job.step.replaceAll("_", " "))}
        </strong>
        <span>{Math.floor(job.elapsed + ticks - base.ticks)}s</span>
      </p>
      <p className="mg-help">
        {job.placements_completed} / {job.placements_total} placements
      </p>
      <ol className="mg-steps">
        {["Surface direction", "Garment lighting", "Depth", "Build maps"].map((label, i) => (
          <li
            key={label}
            className={i === active ? "mg-step--active" : i < active ? "mg-step--done" : ""}
          >
            {i < active ? <CheckCircleIcon /> : <ClockIcon />}
            {label}
          </li>
        ))}
      </ol>
    </>
  );
}
