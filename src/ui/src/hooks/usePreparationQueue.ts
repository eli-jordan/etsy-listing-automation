import { useEffect, useState } from "react";
import { listPreparationJobs, type PreparationJob } from "../api/preparation";
export function usePreparationQueue() {
  const [jobs, setJobs] = useState<PreparationJob[]>([]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async () => {
      try {
        const result = await listPreparationJobs();
        if (active)
          setJobs(
            result.filter(
              (j) => j.phase === "queued" || j.phase === "running" || j.phase === "cancelling",
            ),
          );
      } catch {
        /* Status in the selected editor provides its actionable error. */
      } finally {
        if (active) timer = setTimeout(() => void read(), 3000);
      }
    };
    void read();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, []);
  return jobs;
}
