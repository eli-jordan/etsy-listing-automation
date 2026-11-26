import { useEffect, useRef, useState } from "react";
import { getPreparation, type Preparation, type PreparationJob } from "../api/preparation";
import type { TemplateSummary } from "../types";

export function useTemplateReadiness(
  templates: TemplateSummary[],
  selected: string | null,
  jobs: PreparationJob[],
) {
  const names = templates.filter((t) => t.renderer === "marigold").map((t) => t.name);
  const key = JSON.stringify(names);
  const jobKey = JSON.stringify(
    jobs
      .filter((job) => job.template !== selected)
      .map((job) => [job.template, job.id + job.phase]),
  );
  const checked = useRef(new Map<string, string>());
  const [facts, setFacts] = useState<Record<string, Preparation["maps"]>>({});
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const names: string[] = JSON.parse(key);
    const states = JSON.parse(jobKey) as [string, string][];
    for (const name of checked.current.keys())
      if (!names.includes(name)) checked.current.delete(name);
    if (selected) checked.current.delete(selected);
    async function readOne(name: string, token: string) {
      try {
        const status = await getPreparation(name, controller.signal);
        if (!active) return;
        checked.current.set(name, token);
        setFacts((current) => ({ ...current, [name]: status.maps }));
      } catch {
        // The row stays unknown; selecting it shows the error.
      }
    }
    async function read() {
      for (const name of names) {
        if (!active) return;
        const token = JSON.stringify(states.filter(([template]) => template === name));
        if (name === selected || checked.current.get(name) === token) continue;
        checked.current.delete(name);
        await readOne(name, token);
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
