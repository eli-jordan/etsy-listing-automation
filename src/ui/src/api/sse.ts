/**
 * A typed `text/event-stream` reader over `fetch`, shared by the two run
 * resources: plan/apply runs (`pages/deploy/runStream.ts`) and AI runs
 * (`api/aiRuns.ts`). Both servers write the same frame,
 * `id: <n>\nevent: <type>\ndata: <json>\n\n`, and both end the stream after
 * the run's last event.
 *
 * **Why a hand-rolled `fetch` reader and not the browser's `EventSource`.**
 * `EventSource`'s constructor takes a URL and nothing else -- there is no way
 * to set a request header on its first connection, only on the *automatic*
 * reconnect after a drop, which the UA does on its own using whatever `id` it
 * last saw. Reattaching needs the header on the *first* request this page
 * ever makes to a run it did not start (a reload, or *View progress*), and
 * the servers read exactly that header (`Last-Event-ID`). `EventSource`
 * cannot ask for it; a plain `fetch` with a header can.
 *
 * No reconnect-on-drop logic is implemented here -- a run belongs to the
 * server regardless of who is watching, so a dropped connection loses
 * nothing a page reload (which reattaches) does not already recover.
 */

export interface EventStreamOptions<Event> {
  /** The last event id already known -- `undefined` asks the server for
   * everything, which is what a caller that has seen nothing wants. */
  lastEventId?: number | undefined;
  onEvent: (event: Event) => void;
  /** The stream closed because the run reached its last event -- there is
   * nothing more to read. */
  onDone?: () => void;
  /** The request itself failed (network, or a non-200 status) -- distinct
   * from `onDone`, which means the run finished normally. */
  onError?: (error: unknown) => void;
}

export interface EventStreamHandle {
  /** Stops reading and aborts the underlying request. Safe to call more than
   * once, and safe to call after the stream has already finished on its
   * own. */
  close: () => void;
}

function parseFrame<Event>(block: string): Event | null {
  let data: string | null = null;
  for (const line of block.split("\n")) {
    if (line.startsWith("data: ")) data = line.slice("data: ".length);
  }
  if (data === null) return null;
  return JSON.parse(data) as Event;
}

export function openEventStream<Event>(
  url: string,
  options: EventStreamOptions<Event>,
): EventStreamHandle {
  const controller = new AbortController();
  const headers =
    options.lastEventId !== undefined ? { "Last-Event-ID": String(options.lastEventId) } : {};

  async function read(): Promise<void> {
    let response: Response;
    try {
      response = await fetch(url, { headers, signal: controller.signal });
    } catch (error) {
      if (!controller.signal.aborted) options.onError?.(error);
      return;
    }
    if (!response.ok || response.body === null) {
      if (!controller.signal.aborted)
        options.onError?.(new Error(`event stream: HTTP ${response.status}`));
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
          const event = parseFrame<Event>(block);
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
