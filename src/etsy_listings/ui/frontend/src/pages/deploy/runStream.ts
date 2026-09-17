import { runEventsUrl } from "../../api/runs";
import type { RunEvent } from "../../types";

/**
 * A typed reader over `GET /api/runs/{id}/events` (A33 decision 7's SSE
 * route), with `Last-Event-ID` resume (docs/deploy-changes.md decision 9:
 * reattaching sends "the SSE stream with the last event id").
 *
 * **Why this is a hand-rolled `fetch` reader and not the browser's
 * `EventSource`.** `EventSource`'s constructor takes a URL and nothing else
 * -- there is no way to set a request header on its first connection, only
 * on the *automatic* reconnect after a drop, which the UA does on its own
 * using whatever `id` it last saw. Decision 9's reattach case needs the
 * header on the *first* request this page ever makes to a run it did not
 * start (a reload, or *View progress*), because the server side already
 * implements exactly that (`ui/api/runs.py`'s `_last_event_id`, read from
 * the `Last-Event-ID` header). `EventSource` cannot ask for that; a plain
 * `fetch` with a header can. The frame format parsed below is the same one
 * `_sse_frame` writes: `id: <n>\nevent: <type>\ndata: <json>\n\n`.
 *
 * No reconnect-on-drop logic is implemented here -- the run belongs to the
 * server regardless (decision 8), so a dropped connection loses nothing a
 * page reload (which reattaches from `GET /api/runs/{id}` first, per
 * decision 9) does not already recover.
 */

export interface RunStreamOptions {
  /** The last event id already known -- from an earlier `GET /api/runs/{id}`
   * on reattach, or `undefined` for a run this page just started, where
   * nothing has been missed and the server should send everything. */
  lastEventId?: number | undefined;
  onEvent: (event: RunEvent) => void;
  /** The stream closed because the run reached a terminal phase (`ui/api/runs.py`'s
   * `_sse_events`: `if done: return`) -- there is nothing more to read. */
  onDone?: () => void;
  /** The request itself failed (network, or a non-200 status) -- distinct
   * from `onDone`, which means the run finished normally. */
  onError?: (error: unknown) => void;
}

export interface RunStreamHandle {
  /** Stops reading and aborts the underlying request. Safe to call more than
   * once, and safe to call after the stream has already finished on its
   * own. */
  close: () => void;
}

function parseFrame(block: string): RunEvent | null {
  let data: string | null = null;
  for (const line of block.split("\n")) {
    if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (data === null) return null;
  return JSON.parse(data) as RunEvent;
}

export function openRunStream(runId: string, options: RunStreamOptions): RunStreamHandle {
  const controller = new AbortController();
  const headers =
    options.lastEventId !== undefined ? { "Last-Event-ID": String(options.lastEventId) } : {};

  async function read(): Promise<void> {
    let response: Response;
    try {
      response = await fetch(runEventsUrl(runId), { headers, signal: controller.signal });
    } catch (error) {
      if (!controller.signal.aborted) options.onError?.(error);
      return;
    }
    if (!response.ok || response.body === null) {
      if (!controller.signal.aborted)
        options.onError?.(new Error(`run stream: HTTP ${response.status}`));
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        // The last element is either "" (the buffer ended exactly on a frame
        // boundary) or a partial frame still waiting on more bytes -- either
        // way it is not parsed yet, only kept for the next chunk.
        buffer = frames.pop() ?? "";
        for (const block of frames) {
          const event = parseFrame(block);
          if (event !== null) options.onEvent(event);
        }
      }
      options.onDone?.();
    } catch (error) {
      if (!controller.signal.aborted) options.onError?.(error);
    }
  }

  void read();

  return {
    close: () => controller.abort(),
  };
}
