import { useCallback, useEffect, useRef, useState } from "react";
import { getPositionReadiness, queueCoverage } from "../../../api/preparation";

export const READINESS_POLL_MS = 3000;

const PREPARING = "This template is being prepared. Adjusting will be available soon.";
const UNAVAILABLE = "Preparation could not start. Check the Marigold setup in the calibrator.";

export interface PositionReadiness {
  waiting: boolean;
  note: string | null;
  attempt: number;
  refuse: () => void;
  recheck: () => void;
}

interface State {
  template: string | null;
  waiting: boolean;
  running: boolean;
  note: string | null;
  attempt: number;
}

const IDLE: State = { template: null, waiting: false, running: false, note: null, attempt: 0 };

async function readStatus(template: string): Promise<{ waiting: boolean; running: boolean }> {
  try {
    const status = await getPositionReadiness(template);
    return { waiting: !status.ready, running: status.preparing };
  } catch {
    return { waiting: false, running: false };
  }
}

function advanced(
  previous: State,
  template: string,
  read: Omit<State, "template" | "note" | "attempt">,
): State {
  const same = previous.template === template ? previous : { ...IDLE, template };
  return {
    ...same,
    ...read,
    note: read.waiting ? same.note : null,
    attempt: same.attempt + (same.waiting && !read.waiting ? 1 : 0),
  };
}

export function usePositionReadiness(template: string | null): PositionReadiness {
  const [state, setState] = useState<State>(IDLE);
  const shown = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const read = useCallback(
    async function poll() {
      if (template === null) return;
      if (timer.current !== null) clearTimeout(timer.current);
      const status = await readStatus(template);
      if (shown.current !== template) return;
      setState((previous) => advanced(previous, template, status));
      if (status.waiting) timer.current = setTimeout(() => void poll(), READINESS_POLL_MS);
    },
    [template],
  );

  useEffect(() => {
    shown.current = template;
    void read();
    return () => {
      shown.current = null;
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, [template, read]);

  const current = state.template === template ? state : IDLE;

  function refuse() {
    if (template === null) return;
    setState((previous) => ({ ...previous, note: PREPARING }));
    if (current.running) return;
    queueCoverage(template)
      .then((job) => {
        if (job === null) setState((previous) => ({ ...previous, note: UNAVAILABLE }));
        return read();
      })
      .catch(() => setState((previous) => ({ ...previous, note: UNAVAILABLE })));
  }

  return {
    waiting: current.waiting,
    note: current.note,
    attempt: current.attempt,
    refuse,
    recheck: () => void read(),
  };
}
