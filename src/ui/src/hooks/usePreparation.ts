import { useCallback, useEffect, useState } from "react";
import {
  followPreparation,
  getPreparation,
  type Preparation,
  type PreparationEvent,
} from "../api/preparation";

/** Where a reconnect resumes after `event`: nowhere in particular after a
 * resync, which asks for a fresh read. */
function eventCursor(event: PreparationEvent): number | undefined {
  if ("resync" in event) return undefined;
  return "sequence" in event ? event.sequence : event.last_event_sequence;
}

/** Reattach to server work, including CPU rebuilds after save. Reconnection reads
 * status and resumes events; it never submits another preparation job. Automatic
 * reads pause while the editor composite is pending, then resume with a fresh
 * snapshot so progress validation does not compete with the visible edit. */
export function usePreparation(name: string | null, version: number, previewPending = false) {
  const [entry, setEntry] = useState<{ name: string; value: Preparation } | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  useEffect(() => {
    if (!name || previewPending) return;
    const template = name;
    let cancelled = false;
    let stream: ReturnType<typeof followPreparation> | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let eventTimer: ReturnType<typeof setTimeout> | undefined;
    let cursor: number | undefined;
    let followedId: string | undefined;
    let reading = false;
    /** Streams the active job's events, resuming where the last stream for
     * the same job stopped, and reads again when the stream says so. */
    function follow(id: string) {
      if (followedId !== id) cursor = undefined;
      followedId = id;
      stream = followPreparation(id, {
        ...(cursor === undefined ? {} : { lastEventId: cursor }),
        onEvent: (event) => {
          cursor = eventCursor(event);
          // CPU checkpoints arrive in bursts. Reading all masks and map
          // readiness per event competes with interactive composition.
          if (!eventTimer)
            eventTimer = setTimeout(() => {
              eventTimer = undefined;
              void read();
            }, 250);
        },
        onDone: () => {
          timer = setTimeout(() => void read(), 250);
        },
        onError: () => {
          cursor = undefined;
          timer = setTimeout(() => void read(), 1000);
        },
      });
    }
    async function read() {
      if (reading || cancelled) return;
      reading = true;
      try {
        const value = await getPreparation(template);
        if (cancelled) return;
        setEntry({ name: template, value });
        setError("");
        stream?.close();
        if (value.active_job) follow(value.active_job.id);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not read map status");
          timer = setTimeout(() => void read(), 3000);
        }
      } finally {
        reading = false;
      }
    }
    const onFocus = () => void read();
    window.addEventListener("focus", onFocus);
    void read();
    return () => {
      window.removeEventListener("focus", onFocus);
      cancelled = true;
      stream?.close();
      if (timer) clearTimeout(timer);
      if (eventTimer) clearTimeout(eventTimer);
    };
  }, [name, version, refresh, previewPending]);
  return { preparation: entry?.name === name ? entry.value : null, error, reload };
}
