import { useEffect, useState } from "react";
import { getPreparation, type Preparation, type PreparationJob } from "../api/preparation";
import type { TemplateSummary } from "../types";

/** Fill catalog readiness one row at a time; selected status has its own event lifecycle. */
export function useTemplateReadiness(
  templates: TemplateSummary[],
  selected: string | null,
  jobs: PreparationJob[],
) {
  const names = templates.filter((t) => t.renderer === "marigold").map((t) => t.name);
  const key = JSON.stringify(names);
  const jobKey = jobs.map((job) => job.template + job.id + job.phase).join(",");
  const [facts, setFacts] = useState<Record<string, Preparation["maps"]>>({});
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const names: string[] = JSON.parse(key);
    async function read() {
      for (const name of names) {
        if (!active) return;
        if (name === selected) continue;
        try {
          const status = await getPreparation(name, controller.signal);
          if (!active) return;
          setFacts((current) => ({ ...current, [name]: status.maps }));
        } catch {
          // Keep the catalog row unknown. Selecting it exposes the actionable error.
        }
      }
    }
    void read();
    return () => {
      active = false;
      controller.abort();
    };
  }, [key, selected, jobKey]);
  return facts;
}
