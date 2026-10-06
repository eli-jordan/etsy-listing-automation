import { useCallback, useEffect, useState } from "react";
import { followPreparation, getPreparation, type Preparation } from "../api/preparation";

/** Reattach to server work, including CPU rebuilds after save. Reconnection reads
 * status and resumes events; it never submits another preparation job. */
export function usePreparation(name: string | null, version: number) {
  const [entry, setEntry] = useState<{ name: string; value: Preparation } | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  useEffect(() => {
    if (!name) return;
    const template = name;
    let cancelled = false;
    let stream: ReturnType<typeof followPreparation> | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cursor: number | undefined;
    let followedId: string | undefined;
    let reading = false;
    async function read() {
      if (reading || cancelled) return;
      reading = true;
      try {
        const value = await getPreparation(template);
        if (cancelled) return;
        setEntry({ name: template, value });
        setError("");
        stream?.close();
        if (value.active_job) {
          const id = value.active_job.id;
          if (followedId !== id) cursor = undefined;
          followedId = id;
          stream = followPreparation(id, {
            ...(cursor === undefined ? {} : { lastEventId: cursor }),
            onEvent: (event) => {
              cursor =
                "resync" in event
                  ? undefined
                  : "sequence" in event
                    ? event.sequence
                    : event.last_event_sequence;
              void read();
            },
            onDone: () => {
              timer = setTimeout(() => void read(), 250);
            },
            onError: () => {
              cursor = undefined;
              timer = setTimeout(() => void read(), 1000);
            },
          });
        } else {
          // A save elsewhere can start a CPU rebuild. Status discovery has no side effect.
          timer = setTimeout(() => void read(), 3000);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not read map status");
          timer = setTimeout(() => void read(), 3000);
        }
      } finally {
        reading = false;
      }
    }
    void read();
    return () => {
      cancelled = true;
      stream?.close();
      if (timer) clearTimeout(timer);
    };
  }, [name, version, refresh]);
  return { preparation: entry?.name === name ? entry.value : null, error, reload };
}
